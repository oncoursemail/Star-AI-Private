"""Answering a question about a LOCAL video file the owner attached. First slice.

What STAR actually gets from the file:
  - a bounded number of still frames, evenly spaced (ffmpeg), each with its time;
  - the audio track transcribed by the speech recogniser the voice pipeline already uses
    (faster-whisper through `star.voice.engines`), in 30-second pieces with their start times.
Both go to the vision model with the owner's question. STAR has not "watched" anything beyond
that, and every answer carries a line that says exactly what it was based on.

A link, a title or a file name is not a video: `link_only_note` gives the model the rule for
that case, and nothing in this module ever fetches a link.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.webm', '.avi'}
MAX_BYTES = 700_000_000
MAX_DURATION = 90 * 60
MAX_FRAMES = 6
FRAME_SIDE = 768                    # longest side sent to the model; keeps a CPU server's reading time bounded
AUDIO_SECONDS = 10 * 60             # only the first ten minutes of sound are transcribed
PIECE_SECONDS = 30
QUIET_LEVEL = 0.003                 # a piece quieter than this (about -50 dB) is not sent to the recogniser:
                                    # given silence, Whisper writes words that nobody said ("you", "thank you")
TRANSCRIPT_CHARS = 6000
_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class VideoError(RuntimeError):
    """A problem the owner can act on; the message is the whole explanation."""


def ffmpeg_tools(folder: str = '') -> tuple[str, str]:
    """(ffmpeg, ffprobe). Looks in `folder` (Settings), STAR_FFMPEG_DIR, then PATH."""
    for candidate in (folder, os.environ.get('STAR_FFMPEG_DIR', '')):
        if candidate:
            base = Path(candidate).expanduser()
            for directory in (base, base / 'bin'):
                found = [shutil.which(name, path=str(directory)) for name in ('ffmpeg', 'ffprobe')]
                if all(found):
                    return found[0], found[1]
    found = [shutil.which('ffmpeg'), shutil.which('ffprobe')]
    if all(found):
        return found[0], found[1]
    raise VideoError('FFmpeg was not found, so STAR cannot open video files. Install FFmpeg (ffmpeg and '
                     'ffprobe) and add it to PATH, or set its folder in Settings → Where STAR generates.')


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False,
                          creationflags=_NO_WINDOW, stdin=subprocess.DEVNULL)


def clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f'{seconds // 3600}:{seconds % 3600 // 60:02}:{seconds % 60:02}' if seconds >= 3600 \
        else f'{seconds // 60}:{seconds % 60:02}'


@dataclass
class Evidence:
    name: str
    duration: float
    width: int = 0
    height: int = 0
    frames: list[Path] = field(default_factory=list)
    times: list[float] = field(default_factory=list)
    has_audio: bool = False
    transcript: list[tuple[float, str]] = field(default_factory=list)   # (start seconds, text)
    audio_seconds: float = 0.0          # how much of the sound was transcribed
    audio_note: str = ''                # why there is no transcript, when there is none
    asr: str = ''                       # recogniser and where it ran, e.g. "small.en on cuda"
    timings: dict = field(default_factory=dict)
    frame_sampling: str = 'uniform'      # facts about sampling, never an accuracy claim

    def transcript_text(self) -> str:
        text = '\n'.join(f'[{clock(start)}] {line}' for start, line in self.transcript)
        return text if len(text) <= TRANSCRIPT_CHARS else text[:TRANSCRIPT_CHARS] + '\n[transcript cut here]'


def probe(path: Path, ffprobe: str) -> dict:
    done = _run([ffprobe, '-v', 'error', '-show_entries',
                 'format=duration:stream=codec_type,width,height', '-of', 'json', str(path)], 30)
    try:
        data = json.loads(done.stdout or '{}')
        duration = float(data['format']['duration'])
    except (ValueError, KeyError, TypeError) as exc:
        raise VideoError('FFmpeg could not read this file as a video.') from exc
    streams = data.get('streams') or []
    picture = next((s for s in streams if s.get('codec_type') == 'video'), None)
    if picture is None:
        raise VideoError('This file has no picture track. Attach it as audio instead.')
    return {'duration': duration, 'width': int(picture.get('width') or 0),
            'height': int(picture.get('height') or 0),
            'has_audio': any(s.get('codec_type') == 'audio' for s in streams)}


def sample_frames(path: Path, destination: Path, count: int, duration: float, ffmpeg: str, *,
                  cancelled: Callable[[], bool] | None = None) -> tuple[list[Path], list[float]]:
    destination.mkdir(parents=True, exist_ok=True)
    for old_index in range(1, MAX_FRAMES + 1):
        (destination / f'frame_{old_index:02}.jpg').unlink(missing_ok=True)
    frames, times = [], []
    for index in range(count):
        if cancelled is not None and cancelled():
            raise RuntimeError('STAR task cancelled by user')
        at = duration * (index + 0.5) / count
        out = destination / f'frame_{index + 1:02}.jpg'
        out.unlink(missing_ok=True)  # never mistake a previous turn's frame for this video
        _run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-ss', f'{at:.3f}', '-i', str(path),
              '-frames:v', '1', '-vf',
              f'scale={FRAME_SIDE}:{FRAME_SIDE}:force_original_aspect_ratio=decrease', '-q:v', '3',
              '-y', str(out)], 60)
        if cancelled is not None and cancelled():
            raise RuntimeError('STAR task cancelled by user')
        if out.is_file() and out.stat().st_size:
            frames.append(out)
            times.append(round(at, 1))
    if not frames:
        raise VideoError('FFmpeg could not decode any frame of this video.')
    return frames, times


def adaptive_frames(path: Path, destination: Path, count: int, duration: float, ffmpeg: str, *,
                    cancelled: Callable[[], bool] | None = None) -> tuple[list[Path], list[float]]:
    """Screen 3 tiny thumbnails per window, decode only representative frames at full size.

    The model sees no more than count images; nearly unchanged windows may produce
    fewer. No transcription, semantics or events between the samples are inferred.
    Uniform sampling remains the default and is the fallback when previews fail.
    """
    import tempfile
    from .video_sampling import candidate_times, inspect_candidate, choose_keyframes

    destination.mkdir(parents=True, exist_ok=True)
    for old_index in range(1, MAX_FRAMES + 1):
        (destination / f'frame_{old_index:02}.jpg').unlink(missing_ok=True)
    previews = []
    with tempfile.TemporaryDirectory(prefix='star-keyframes-', dir=destination) as folder:
        folder_path = Path(folder)
        for index, (window, second) in enumerate(candidate_times(duration, count)):
            if cancelled is not None and cancelled():
                raise RuntimeError('STAR task cancelled by user')
            thumbnail = folder_path / f'candidate_{index:02}.jpg'
            _run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-ss', f'{second:.3f}',
                  '-i', str(path), '-frames:v', '1',
                  '-vf', 'scale=160:160:force_original_aspect_ratio=decrease',
                  '-q:v', '8', '-y', str(thumbnail)], 25)
            if cancelled is not None and cancelled():
                raise RuntimeError('STAR task cancelled by user')
            if thumbnail.is_file() and thumbnail.stat().st_size:
                try:
                    previews.append(inspect_candidate(window, second, thumbnail))
                except (OSError, ValueError):
                    continue  # corrupt preview is not evidence
        if len({preview.window for preview in previews}) < max(1, count // 2):
            return sample_frames(path, destination, count, duration, ffmpeg, cancelled=cancelled)
        picks = choose_keyframes(previews, count)
        if not picks:
            return sample_frames(path, destination, count, duration, ffmpeg, cancelled=cancelled)
        frames, times = [], []
        for candidate in picks:
            if cancelled is not None and cancelled():
                raise RuntimeError('STAR task cancelled by user')
            out = destination / f'frame_{len(frames) + 1:02}.jpg'
            out.unlink(missing_ok=True)
            _run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-ss', f'{candidate.second:.3f}',
                  '-i', str(path), '-frames:v', '1', '-vf',
                  f'scale={FRAME_SIDE}:{FRAME_SIDE}:force_original_aspect_ratio=decrease',
                  '-q:v', '3', '-y', str(out)], 60)
            if cancelled is not None and cancelled():
                raise RuntimeError('STAR task cancelled by user')
            if out.is_file() and out.stat().st_size:
                frames.append(out)
                times.append(round(candidate.second, 1))
    if not frames:
        # Failed full-size extraction should not turn preview bytes into evidence.
        return sample_frames(path, destination, count, duration, ffmpeg, cancelled=cancelled)
    return frames, times


def extract_audio(path: Path, destination: Path, ffmpeg: str, seconds: int = AUDIO_SECONDS) -> Path | None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', str(path), '-vn', '-ac', '1', '-ar', '16000',
          '-t', str(seconds), '-c:a', 'pcm_s16le', '-y', str(destination)], 300)
    return destination if destination.is_file() and destination.stat().st_size > 1000 else None


def voice_asr():
    """The voice pipeline's recogniser (same engine, model choice and device rule as a call)."""
    from .voice import engines
    return engines.make_asr('faster-whisper', 'auto', 'auto')


def transcribe(wav: Path, asr, *, cancelled: Callable[[], bool] | None = None) -> tuple[list[tuple[float, str]], float]:
    """((start seconds, words) per 30-second piece that has sound, seconds of sound read)."""
    from .voice.pcm import rms
    with wave.open(str(wav), 'rb') as audio:
        rate, total = audio.getframerate(), audio.getnframes()
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
            raise VideoError('Unexpected audio format after extraction')
        lines, position = [], 0
        while position < total:
            if cancelled is not None and cancelled():
                raise RuntimeError('STAR task cancelled by user')
            pcm = audio.readframes(rate * PIECE_SECONDS)
            text = asr.transcribe(pcm, rate).strip() if pcm and rms(pcm) >= QUIET_LEVEL else ''
            if text:
                lines.append((position / rate, text))
            position += rate * PIECE_SECONDS
    return lines, total / rate


def prepare(path: Path, workdir: Path, *, frames: int = 4, ffmpeg_dir: str = '', asr=None,
            cancelled: Callable[[], bool] | None = None, frame_sampling: str = 'uniform') -> Evidence:
    """Open a local video and collect what the model will be given. Raises VideoError with the reason."""
    import time
    path = Path(path).expanduser().resolve(strict=True)
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise VideoError('Unsupported video type. Use MP4, MOV, MKV, WebM or AVI.')
    if path.stat().st_size > MAX_BYTES:
        raise VideoError('This video is larger than 700 MB.')
    if type(frames) is not int or not 1 <= frames <= MAX_FRAMES:
        raise ValueError(f'Use 1-{MAX_FRAMES} frames')
    if frame_sampling not in ('uniform', 'adaptive'):
        raise ValueError('Video frame sampling must be uniform or adaptive')
    ffmpeg, ffprobe = ffmpeg_tools(ffmpeg_dir)
    facts = probe(path, ffprobe)
    if not 0 < facts['duration'] <= MAX_DURATION:
        raise VideoError('Video length is outside the supported range (up to 90 minutes).')
    evidence = Evidence(name=path.name, duration=facts['duration'], width=facts['width'],
                        height=facts['height'], has_audio=facts['has_audio'])
    evidence.frame_sampling = frame_sampling
    started = time.monotonic()
    sampler = adaptive_frames if frame_sampling == 'adaptive' else sample_frames
    evidence.frames, evidence.times = sampler(path, workdir / 'frames', frames, facts['duration'], ffmpeg,
                                             cancelled=cancelled)
    evidence.timings['frames_seconds'] = round(time.monotonic() - started, 2)
    if not facts['has_audio']:
        evidence.audio_note = 'The file has no sound track.'
        return evidence
    started = time.monotonic()
    wav = extract_audio(path, workdir / 'audio.wav', ffmpeg)
    if wav is None:
        evidence.audio_note = 'The sound track could not be decoded.'
        return evidence
    try:
        recogniser = asr or voice_asr()
        evidence.transcript, evidence.audio_seconds = transcribe(wav, recogniser, cancelled=cancelled)
        evidence.asr = (f"{getattr(recogniser, 'model_name', 'speech recogniser')} on "
                        f"{getattr(recogniser, 'device', 'this PC')}")
        if not evidence.transcript:
            evidence.audio_note = 'The sound track is silent or has no words the speech recogniser could hear.'
    except RuntimeError:
        raise
    except Exception as exc:     # missing optional speech packages, model download failure, ...
        evidence.audio_note = ('The sound was not transcribed: the speech recogniser is unavailable '
                               f'({type(exc).__name__}). Voice extras are needed for it.')
    evidence.timings['audio_seconds'] = round(time.monotonic() - started, 2)
    return evidence


def evidence_text(evidence: Evidence) -> str:
    """The description of the material that goes into the prompt, before the owner's question."""
    count = len(evidence.frames)
    parts = [f'VIDEO FILE "{evidence.name}" (length {clock(evidence.duration)}'
             + (f', {evidence.width}x{evidence.height}' if evidence.width else '') + ').',
             f'You are given {count} still frame{"s" if count != 1 else ""} sampled at '
             + ', '.join(clock(t) for t in evidence.times)
             + ' (attached as images, in that order). You have NOT seen what happens between them.']
    if evidence.frame_sampling == 'adaptive':
        parts.append('Adaptive screening considered low-resolution thumbnail candidates; uniform spacing '
                     'may be used as a fallback if previews cannot be decoded. Neither method establishes '
                     'which moments matter.')
    if evidence.transcript:
        covered = min(evidence.audio_seconds, evidence.duration)
        parts.append(f'Machine transcript of the first {clock(covered)} of the sound '
                     f'(may contain mistakes):\n{evidence.transcript_text()}')
    else:
        parts.append(f'No transcript of the sound: {evidence.audio_note or "not available."}')
    parts.append('Answer only from these frames and this transcript. Say which frame time or transcript '
                 'time supports each point. If the answer is not in them, say so plainly; never fill a gap '
                 'by guessing what the video probably shows.')
    return '\n'.join(parts)


def footer(evidence: Evidence) -> str:
    """The line STAR adds to the answer itself, so the basis is stated whatever the model wrote."""
    count = len(evidence.frames)
    sound = (f'a machine transcript of {clock(min(evidence.audio_seconds, evidence.duration))} of its sound'
             if evidence.transcript else f'no transcript ({(evidence.audio_note or "not available").rstrip(".").lower()})')
    return (f'\n\n_Based on {count} sampled frame{"s" if count != 1 else ""} of "{evidence.name}" '
            f'({", ".join(clock(t) for t in evidence.times)}) and {sound}; '
            f'the rest of the video was not seen._')


_VIDEO_LINK = re.compile(
    r'https?://(?:www\.|m\.)?(?:youtube\.com|youtu\.be|vimeo\.com|tiktok\.com|twitch\.tv|dailymotion\.com|'
    r'streamable\.com|x\.com|twitter\.com|facebook\.com|instagram\.com)/\S+'
    r'|https?://\S+\.(?:mp4|mov|mkv|webm|avi)\b', re.I)

LINK_RULE = ('The message refers to a video, but no video file is attached, so you have no frames and no '
             'sound from it. You have NOT watched it. Do not describe, summarise or judge its content, and '
             'do not imply you have seen it. Say in one sentence that you only have the link or title, and '
             'that you can answer if the owner attaches the video file. You may still help with anything '
             'the message itself states in words.')


def link_only_note(prompt: str, has_video_file: bool) -> str:
    """The rule for a turn that talks about a video STAR was not given. '' when it does not apply."""
    if has_video_file or not isinstance(prompt, str):
        return ''
    if _VIDEO_LINK.search(prompt):
        return LINK_RULE
    return ''
