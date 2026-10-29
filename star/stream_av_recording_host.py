"""Owner-opted, read-only OBS recording -> audible/rendered-mouth measurement.

FFmpeg/FFprobe decode only an explicit, local, short OBS recording plus two
owner-selected static mouth calibration stills. The host must independently
verify that this recording depicts Star's OBS output and that the selected
audio track contains ONLY Star's speech. No OBS, game, TTS, or rig is controlled.
No raw video/audio is written or returned; even good numbers are advisory.

This module is not a trustworthy capture host by itself: path ownership,
media authenticity, consent, and isolated-audio routing belong to the host.
"""
from __future__ import annotations

from array import array
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

from .stream_av_sync_audit import AVSyncReport, OutputAVSample, audit_output_av_sync

_FPS = 30
_AUDIO_HZ = 8000
_TILE = 24
_MAX_BYTES = 256 * 1024 * 1024
_MAX_TEMPLATE_BYTES = 10 * 1024 * 1024
_MAX_CLIP_S = 120.0
_ALLOWED_VIDEO = frozenset({".mkv", ".mp4", ".mov"})
_ALLOWED_IMAGE = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".pgm"})


class AVRecordingError(RuntimeError):
    """A sanitized failure (never include recording paths or FFmpeg output)."""


@dataclass(frozen=True)
class MouthROI:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        for name in ("x", "y", "width", "height"):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 8192:
                raise ValueError("ROI coordinates must be bounded positive integers")
        if not 8 <= self.width <= 1024 or not 8 <= self.height <= 1024:
            raise ValueError("ROI needs an 8..1024 pixel region")

    @property
    def ffmpeg_filter(self) -> str:
        return (f"crop={self.width}:{self.height}:{self.x}:{self.y},"
                f"scale={_TILE}:{_TILE}:flags=area,format=gray")


@dataclass(frozen=True)
class RecordingAVResult:
    report: AVSyncReport
    observed_frames: int
    audio_track: int
    calibration_separation: float
    captured_output_attested: bool
    isolated_star_audio_attested: bool
    provenance: str = "local_decoded_media_unverified_by_this_module"


def _local_file(path: str | Path, extensions: frozenset[str], max_bytes: int) -> tuple[Path, os.stat_result]:
    if not isinstance(path, (str, Path)) or len(str(path)) > 4096:
        raise ValueError("expected a bounded local path")
    candidate = Path(path)
    if candidate.suffix.lower() not in extensions or candidate.is_symlink() or not candidate.is_file():
        raise AVRecordingError("expected a regular, local media file of an approved type")
    try:
        resolved = candidate.resolve(strict=True)
        stat = resolved.stat()
    except OSError as exc:
        raise AVRecordingError("media file unavailable") from exc
    if not 1 <= stat.st_size <= max_bytes:
        raise AVRecordingError("media file outside size bounds")
    return resolved, stat


def _run(args: list[str], *, timeout: int = 45, max_output: int = 4_000_000) -> bytes:
    """No shell, network protocol, or user-controlled FFmpeg filter string."""
    try:
        proc = subprocess.run(
            args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AVRecordingError("local media decoder unavailable or timed out") from exc
    if proc.returncode != 0 or len(proc.stdout) > max_output:
        raise AVRecordingError("local media decoding failed or exceeded bounds")
    return proc.stdout


def _media_info(path: Path, ffprobe: str) -> dict:
    raw = _run([
        ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe",
        "-show_entries", "format=duration:stream=index,codec_type,start_time,width,height,avg_frame_rate",
        "-of", "json", str(path),
    ], timeout=20, max_output=32768)
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AVRecordingError("invalid local media metadata") from exc
    if type(payload) is not dict or type(payload.get("streams")) is not list:
        raise AVRecordingError("missing media stream metadata")
    return payload


def _number(value: object, label: str, low: float, high: float) -> float:
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise AVRecordingError(f"invalid media {label}") from exc
    if not math.isfinite(result) or not low <= result <= high:
        raise AVRecordingError(f"media {label} outside range")
    return result


def _check_rendered_timeline(path: Path, ffprobe: str, *, duration: float) -> None:
    """Reject large source frame gaps before resampling to 30 Hz hides them.

    Timestamp order is from decoded video presentation frames, not packet
    decode order (which can be different for H.264 B-frames). This cannot
    establish real-world monitor presentation or OBS scene identity.
    """
    raw = _run([
        ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe",
        "-select_streams", "v:0", "-show_frames",
        "-show_entries", "frame=best_effort_timestamp_time",
        "-of", "json", str(path),
    ], timeout=45, max_output=1_600_000)
    try:
        entries = json.loads(raw)["frames"]
    except (ValueError, TypeError, KeyError, UnicodeDecodeError) as exc:
        raise AVRecordingError("invalid frame timeline metadata") from exc
    if type(entries) is not list or not 180 <= len(entries) <= 14400:
        raise AVRecordingError("source recording has insufficient or excessive timed frames")
    times = [_number(entry.get("best_effort_timestamp_time"),
                     "presentation timestamp", 0, 1e10) for entry in entries]
    gaps = [b - a for a, b in zip(times, times[1:])]
    if any(not .001 <= gap <= .100 for gap in gaps):
        raise AVRecordingError("source video presentation discontinuity")
    if not duration - .160 <= times[-1] - times[0] <= duration + .160:
        raise AVRecordingError("decoded video timeline does not span media duration")


def _decode_still(path: Path, roi: MouthROI, ffmpeg: str) -> bytes:
    data = _run([
        ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
        "-i", str(path), "-map", "0:v:0", "-vf", roi.ffmpeg_filter,
        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
    ], timeout=20, max_output=_TILE * _TILE)
    if len(data) != _TILE * _TILE:
        raise AVRecordingError("calibration image missing ROI pixels")
    return data


def _unchanged(path: Path, before: os.stat_result) -> bool:
    try:
        after = path.stat()
    except OSError:
        return False
    return (after.st_size == before.st_size and after.st_mtime_ns == before.st_mtime_ns
            and after.st_ino == before.st_ino)


def _envelopes(pcm: bytes, count: int) -> list[float]:
    if len(pcm) % 2:
        raise AVRecordingError("truncated decoded PCM")
    data = array("h")
    data.frombytes(pcm)
    if sys.byteorder != "little":
        data.byteswap()
    audio_seconds = len(data) / _AUDIO_HZ
    video_seconds = count / _FPS
    if abs(audio_seconds - video_seconds) > 0.090:
        raise AVRecordingError("audio and rendered frames do not align in duration")
    levels = []
    for frame in range(count):
        lo = round(frame * _AUDIO_HZ / _FPS)
        hi = round((frame + 1) * _AUDIO_HZ / _FPS)
        chunk = data[lo:min(hi, len(data))]
        if len(chunk) < 150:
            raise AVRecordingError("missing audio evidence at end of recording")
        levels.append(math.sqrt(sum((x / 32768.0) ** 2 for x in chunk) / len(chunk)))
    # Use a robust within-clip amplitude reference; doesn't establish that
    # the voice is Star or exclude game sounds/music on an incorrectly routed track.
    ordered = sorted(levels)
    reference = ordered[max(0, math.ceil(.95 * len(ordered)) - 1)]
    if reference < 0.005:
        raise AVRecordingError("insufficient audible output for lip-sync measurement")
    return [min(1.0, v / reference) for v in levels]


def _mouth_scores(frames: bytes, closed: bytes, opened: bytes) -> tuple[list[float], float]:
    n = _TILE * _TILE
    if len(frames) % n:
        raise AVRecordingError("truncated rendered video")
    separation = sum(abs(a - b) for a, b in zip(closed, opened)) / n
    if separation < 12.0:
        raise AVRecordingError("mouth calibration has insufficient visual contrast")
    scores = []
    for start in range(0, len(frames), n):
        frame = frames[start:start+n]
        dc = sum(abs(a - b) for a, b in zip(frame, closed))
        do = sum(abs(a - b) for a, b in zip(frame, opened))
        scores.append(dc / (dc + do) if (dc + do) else 0.0)
    return scores, round(separation, 2)


def audit_local_obs_recording(
    recording: str | Path, *, closed_still: str | Path, open_still: str | Path,
    roi: MouthROI, audio_track: int = 0,
    host_confirms_isolated_star_audio: bool = False,
    host_attests_actual_output: bool = False,
    ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
) -> RecordingAVResult:
    """Observe a selected local OBS clip; never alter the original media.

    Only an authorized host may set either attestation; neither is checked by
    this decoder. A real positive verdict requires both attestations. The
    audio track MUST be Star speech alone, not game, viewers, music or mic.
    The open/closed reference stills must come from the *same* avatar and
    identical crop/lighting/background. This is pixel-template correlation,
    not phoneme recognition or proof of humanlike acting.
    """
    if not isinstance(roi, MouthROI):
        raise TypeError("expected owner-chosen MouthROI")
    if type(audio_track) is not int or not 0 <= audio_track <= 5:
        raise ValueError("audio_track must be an explicit 0-based track index, 0..5")
    if type(host_confirms_isolated_star_audio) is not bool or type(host_attests_actual_output) is not bool:
        raise ValueError("capture attestations must be explicit booleans")
    if not host_confirms_isolated_star_audio:
        raise PermissionError("trusted host must confirm a separate Star-only recording audio track")
    if not all(type(s) is str and re.fullmatch(r"[\w./\\:-]{1,250}", s) for s in (ffmpeg, ffprobe)):
        raise ValueError("invalid local decoder executable")
    movie, movie_stat = _local_file(recording, _ALLOWED_VIDEO, _MAX_BYTES)
    closed_path, closed_stat = _local_file(closed_still, _ALLOWED_IMAGE, _MAX_TEMPLATE_BYTES)
    opened_path, opened_stat = _local_file(open_still, _ALLOWED_IMAGE, _MAX_TEMPLATE_BYTES)
    info = _media_info(movie, ffprobe)
    duration = _number(info.get("format", {}).get("duration"), "duration", 6.0, _MAX_CLIP_S)
    streams = info["streams"]
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    if len(videos) != 1 or audio_track >= len(audios):
        raise AVRecordingError("expected one video and selected isolated audio track")
    video = videos[0]
    if not (0 <= roi.x <= int(video.get("width", 0)) - roi.width
            and 0 <= roi.y <= int(video.get("height", 0)) - roi.height):
        raise AVRecordingError("mouth ROI outside recorded video")
    # Reject media with a substantial audio/video stream onset mismatch. Small
    # start offsets (up to 20ms) remain a measurement uncertainty.
    start_v = _number(video.get("start_time"), "video start", 0, 1e10)
    start_a = _number(audios[audio_track].get("start_time"), "audio start", 0, 1e10)
    if abs(start_v - start_a) > 0.020:
        raise AVRecordingError("audio/video stream start times differ by more than 20ms")
    _check_rendered_timeline(movie, ffprobe, duration=duration)
    frame_filter = roi.ffmpeg_filter + f",fps=fps={_FPS}:start_time=0"
    closed = _decode_still(closed_path, roi, ffmpeg)
    opened = _decode_still(opened_path, roi, ffmpeg)
    video_bytes = _run([
        ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
        "-i", str(movie), "-map", "0:v:0", "-t", "120", "-vf", frame_filter,
        "-frames:v", str(int(_MAX_CLIP_S * _FPS)), "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
    ], max_output=int(_MAX_CLIP_S * _FPS) * _TILE * _TILE)
    if len(video_bytes) % (_TILE * _TILE):
        raise AVRecordingError("bad decoded frame length")
    count = len(video_bytes) // (_TILE * _TILE)
    if not 180 <= count <= int(_MAX_CLIP_S * _FPS):
        raise AVRecordingError("insufficient or excessive decoded video")
    audio_bytes = _run([
        ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
        "-i", str(movie), "-map", f"0:a:{audio_track}", "-t", "120",
        "-af", "aresample=async=1:first_pts=0", "-ac", "1", "-ar", str(_AUDIO_HZ),
        "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1",
    ], max_output=int(_MAX_CLIP_S * _AUDIO_HZ * 2) + 16384)
    if not all((_unchanged(movie, movie_stat), _unchanged(closed_path, closed_stat),
                _unchanged(opened_path, opened_stat))):
        raise AVRecordingError("source media changed during decoding")
    levels = _envelopes(audio_bytes, count)
    apertures, separation = _mouth_scores(video_bytes, closed, opened)
    samples = [OutputAVSample(1000.0 * i / _FPS, levels[i], apertures[i])
               for i in range(count)]
    return RecordingAVResult(
        report=audit_output_av_sync(samples, output_capture_attested=host_attests_actual_output),
        observed_frames=count, audio_track=audio_track,
        calibration_separation=separation,
        captured_output_attested=host_attests_actual_output,
        isolated_star_audio_attested=host_confirms_isolated_star_audio,
    )


__all__ = ["AVRecordingError", "MouthROI", "RecordingAVResult", "audit_local_obs_recording"]