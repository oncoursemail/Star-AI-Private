"""Fail-closed, read-only verification of an owner-selected private OBS media artifact.

Designed to complement OBS's *live* status/counter probe. A trusted host must
independently establish the file came from its own private rehearsal, that OBS
is stopped, and that broadcasting stayed off. This module only checks whether
an allowlisted local artifact has decodable video and an audio stream.

No recording, streaming, playback, game control, capture, or network operations.
No media, paths, transcripts or raw decoder output are returned.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any

_MAX_BYTES = 512 * 1024 * 1024
_MIN_BYTES = 4096
_MAX_SECONDS = 120.0
_INPUT_FORMAT = {".mkv": "matroska", ".mp4": "mov", ".mov": "mov"}
_EXE = re.compile(r"[\w./\\:-]{1,250}\Z", re.ASCII)


class RecordingArtifactError(RuntimeError):
    """Sanitized verification failure; never include paths or decoder output."""


@dataclass(frozen=True)
class RecordingArtifactReport:
    status: str  # candidate_for_owner_review, never a broadcast authorization
    duration_s: float
    video_frames: int
    video_width: int
    video_height: int
    audio_streams: int
    selected_audio_track: int
    local_media_decoded: bool = True
    recording_origin_attested: bool = False
    star_only_audio_attested: bool = False
    gameplay_or_avatar_verified: bool = False
    broadcast_authorized: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)


def _validated_input(recording: str | Path, allowed_root: str | Path) -> tuple[Path, os.stat_result, str]:
    if (not isinstance(recording, (str, Path)) or not isinstance(allowed_root, (str, Path))
            or len(str(recording)) > 4096 or len(str(allowed_root)) > 4096):
        raise ValueError("invalid bounded local media selection")
    selected, root = Path(recording), Path(allowed_root)
    if (not selected.is_absolute() or not root.is_absolute()
            or str(selected).startswith(("//", "\\\\")) or str(root).startswith(("//", "\\\\"))
            or ".." in selected.parts or ".." in root.parts):
        raise ValueError("only absolute local paths without traversal are allowed")
    if root.is_symlink() or not root.is_dir() or selected.is_symlink():
        raise RecordingArtifactError("local recording directory or file is invalid")
    if selected.suffix.lower() not in _INPUT_FORMAT:
        raise RecordingArtifactError("unsupported private recording container")
    try:
        folder = root.resolve(strict=True)
        path = selected.resolve(strict=True)
        if not path.is_relative_to(folder):
            raise RecordingArtifactError("recording is outside approved directory")
        before = selected.lstat()
    except RecordingArtifactError:
        raise
    except (OSError, RuntimeError) as exc:
        raise RecordingArtifactError("recording unavailable") from exc
    if not stat.S_ISREG(before.st_mode) or not _MIN_BYTES <= before.st_size <= _MAX_BYTES:
        raise RecordingArtifactError("recording is not a bounded regular file")
    return path, before, _INPUT_FORMAT[selected.suffix.lower()]


def _run(args: list[str], timeout: int, *, json_output: bool) -> bytes:
    # All inputs are argv elements. Never expose stderr (which can contain paths).
    try:
        result = subprocess.run(
            args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE if json_output else subprocess.DEVNULL,
            stderr=subprocess.PIPE, check=False, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RecordingArtifactError("local media tool unavailable or timed out") from exc
    if result.returncode != 0:
        raise RecordingArtifactError("private media inspection or decoding failed")
    output = result.stdout if isinstance(result.stdout, bytes) else b""
    if len(output) > 32768:
        raise RecordingArtifactError("media metadata exceeds bounds")
    return output


def _int(value: Any, *, low: int, high: int, label: str) -> int:
    if type(value) is int:
        n = value
    elif type(value) is str and re.fullmatch(r"[0-9]{1,12}", value):
        n = int(value)
    else:
        raise RecordingArtifactError(f"invalid {label}")
    if not low <= n <= high:
        raise RecordingArtifactError(f"invalid {label}")
    return n


def _duration(value: Any) -> float:
    if type(value) not in (str, int, float):
        raise RecordingArtifactError("invalid media duration")
    try:
        seconds = float(value)
    except (ValueError, OverflowError):
        raise RecordingArtifactError("invalid media duration") from None
    if not math.isfinite(seconds) or not 4.0 <= seconds <= _MAX_SECONDS:
        raise RecordingArtifactError("media duration outside private test bounds")
    return seconds


def inspect_private_obs_artifact(
    recording: str | Path, *, allowed_root: str | Path,
    owner_approved: bool = False, host_confirms_recording_stopped: bool = False,
    host_confirms_broadcast_inactive: bool = False,
    selected_audio_track: int = 0, ffprobe: str = "ffprobe", ffmpeg: str = "ffmpeg",
) -> RecordingArtifactReport:
    """Check a stopped local OBS file; advisory evidence only, not provenance.

    Explicit host assertions are admission requirements, not facts established
    by this module. Check OBS's actual state and file origin independently;
    do not use this report to attest that the clip contains Star speaking.
    """
    if (owner_approved is not True or host_confirms_recording_stopped is not True
            or host_confirms_broadcast_inactive is not True):
        raise PermissionError("trusted host approval and private stopped recording required")
    if type(selected_audio_track) is not int or not 0 <= selected_audio_track <= 5:
        raise ValueError("selected audio track must be an integer 0..5")
    if any(type(exe) is not str or not _EXE.fullmatch(exe) for exe in (ffprobe, ffmpeg)):
        raise ValueError("invalid trusted decoder executable")

    file, before, container = _validated_input(recording, allowed_root)
    info_raw = _run([
        ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe",
        "-f", container, "-count_frames",
        "-show_entries", "format=duration:stream=index,codec_type,width,height,nb_read_frames,sample_rate",
        "-of", "json", str(file),
    ], 30, json_output=True)
    try:
        info = json.loads(info_raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise RecordingArtifactError("invalid local media metadata") from exc
    if type(info) is not dict or type(info.get("format")) is not dict or type(info.get("streams")) is not list:
        raise RecordingArtifactError("incomplete local media metadata")
    streams = info["streams"]
    if not 2 <= len(streams) <= 12 or any(type(s) is not dict for s in streams):
        raise RecordingArtifactError("unexpected media streams")
    seconds = _duration(info["format"].get("duration"))
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    if len(videos) != 1 or not 1 <= len(audios) <= 6 or selected_audio_track >= len(audios):
        raise RecordingArtifactError("recording needs one video and selected audio stream")
    video, audio = videos[0], audios[selected_audio_track]
    width = _int(video.get("width"), low=32, high=4096, label="video width")
    height = _int(video.get("height"), low=32, high=2304, label="video height")
    frames = _int(video.get("nb_read_frames"), low=40, high=30000, label="decoded frame count")
    if not 8 <= frames / seconds <= 240:
        raise RecordingArtifactError("video frame timeline outside private test bounds")
    _int(audio.get("sample_rate"), low=8000, high=192000, label="audio sample rate")

    # -xerror and -err_detect explode make decode errors fail closed. All
    # streams selected explicitly; a container header alone cannot pass.
    _run([
        ffmpeg, "-nostdin", "-v", "error", "-xerror", "-err_detect", "explode",
        "-protocol_whitelist", "file,pipe", "-f", container, "-i", str(file),
        "-map", "0:v:0", "-map", f"0:a:{selected_audio_track}",
        "-t", "125", "-threads", "2", "-f", "null", "-",
    ], 45, json_output=False)
    try:
        after = file.stat()
    except OSError as exc:
        raise RecordingArtifactError("recording disappeared during inspection") from exc
    if any((before.st_dev != after.st_dev, before.st_ino != after.st_ino,
            before.st_size != after.st_size, before.st_mtime_ns != after.st_mtime_ns)):
        raise RecordingArtifactError("recording changed during inspection")

    return RecordingArtifactReport(
        "candidate_for_owner_review", round(seconds, 3), frames, width, height,
        len(audios), selected_audio_track,
    )


__all__ = ["RecordingArtifactError", "RecordingArtifactReport", "inspect_private_obs_artifact"]
