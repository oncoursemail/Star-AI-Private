"""One-command, local-only private OBS rehearsal evidence audit for STAR.

Composes the existing FFmpeg decode and rendered-mouth/audio synchronization
auditors rather than using OBS byte counters as a substitute for actual output.
All consent/provenance statements must come from a *trusted local operator*;
CLI checkboxes are declarations, not authentication. No networking, recording,
live output, game control, uploads or stored media are performed.

Run (on the recording machine, once OBS has stopped):
    python -m star.stream_private_rehearsal_audit_cli --help
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import stat
from typing import Sequence

from .stream_obs_recording_artifact_probe import (
    RecordingArtifactError, inspect_private_obs_artifact,
)
from .stream_av_recording_host import (
    AVRecordingError, MouthROI, audit_local_obs_recording,
)


class PrivateRehearsalAuditError(RuntimeError):
    """Sanitized read-only audit error; never contains a media path."""


@dataclass(frozen=True)
class PrivateRehearsalEvidence:
    status: str  # decodable_only | av_review_candidate | av_needs_improvement | av_inconclusive
    duration_s: float
    decoded_video_frames: int
    audio_stream_count: int
    selected_audio_track: int
    av_verdict: str | None = None
    estimated_mouth_lag_ms: int | None = None
    voiced_mouth_coverage: float | None = None
    silent_mouth_rate: float | None = None
    best_alignment_f1: float | None = None
    observed_av_frames: int | None = None
    # These claims cannot be established from a selected file/decoder.
    recording_origin_verified: bool = False
    gameplay_verified: bool = False
    star_speech_identity_verified: bool = False
    humanlike_verified: bool = False
    broadcast_authorized: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)


def _admit(path: str | Path, *, root: Path) -> tuple[Path, tuple[int, ...]]:
    """Restrict source and calibration images to a finite local recording folder."""
    if not isinstance(path, (str, Path)) or len(str(path)) > 4096:
        raise PrivateRehearsalAuditError("invalid bounded local media path")
    selected = Path(path)
    if (not selected.is_absolute() or ".." in selected.parts
            or selected.is_symlink() or str(selected).startswith(("//", "\\\\"))):
        raise PrivateRehearsalAuditError("only approved absolute local media paths")
    try:
        full = selected.resolve(strict=True)
        if not full.is_relative_to(root):
            raise PrivateRehearsalAuditError("media outside the approved directory")
        info = selected.lstat()
    except PrivateRehearsalAuditError:
        raise
    except (OSError, RuntimeError) as exc:
        raise PrivateRehearsalAuditError("selected media is unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= 512 * 1024 * 1024:
        raise PrivateRehearsalAuditError("selected media is not a bounded regular file")
    return full, (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _unchanged(path: Path, fingerprint: tuple[int, ...]) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and
            (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            == fingerprint)


def audit_private_rehearsal(
    recording: str | Path, *, allowed_root: str | Path,
    owner_approved: bool = False,
    host_confirms_recording_stopped: bool = False,
    host_confirms_broadcast_inactive: bool = False,
    selected_audio_track: int = 0,
    closed_still: str | Path | None = None,
    open_still: str | Path | None = None,
    mouth_roi: MouthROI | None = None,
    host_confirms_isolated_star_audio: bool = False,
    host_attests_actual_output: bool = False,
    ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
) -> PrivateRehearsalEvidence:
    """Perform a privacy-bounded, read-only two-stage media audit.

    It cannot prove the selected media came from OBS, prove the audio is Star,
    or establish that a game was played. Do not expose this as an LLM tool.
    """
    if (owner_approved is not True
            or host_confirms_recording_stopped is not True
            or host_confirms_broadcast_inactive is not True):
        raise PermissionError("private stopped-recording consent is required")
    if not isinstance(allowed_root, (str, Path)) or len(str(allowed_root)) > 4096:
        raise PrivateRehearsalAuditError("invalid allowed local recording directory")
    requested_mouth = any(item is not None for item in (closed_still, open_still, mouth_roi))
    if requested_mouth and not all(
        item is not None for item in (closed_still, open_still, mouth_roi)
    ):
        raise PrivateRehearsalAuditError("mouth audit requires two calibration images and ROI")
    if not requested_mouth and (
        host_confirms_isolated_star_audio or host_attests_actual_output
    ):
        raise PrivateRehearsalAuditError("capture declarations require a mouth audit")
    if requested_mouth and (
        host_confirms_isolated_star_audio is not True
        or host_attests_actual_output is not True
    ):
        raise PermissionError("isolated Star audio and actual-output attestations required")
    if requested_mouth and not isinstance(mouth_roi, MouthROI):
        raise PrivateRehearsalAuditError("invalid mouth region")
    candidate_root = Path(allowed_root)
    if (not candidate_root.is_absolute() or ".." in candidate_root.parts
            or candidate_root.is_symlink()
            or str(candidate_root).startswith(("//", "\\\\"))):
        raise PrivateRehearsalAuditError("invalid local allowed recording directory")
    try:
        root = candidate_root.resolve(strict=True)
        if not root.is_dir():
            raise PrivateRehearsalAuditError("invalid local allowed recording directory")
    except (OSError, RuntimeError) as exc:
        raise PrivateRehearsalAuditError("invalid local allowed recording directory") from exc
    movie, before = _admit(recording, root=root)
    cfile: Path | None = None
    ofile: Path | None = None
    cbefore: tuple[int, ...] | None = None
    obefore: tuple[int, ...] | None = None
    if requested_mouth:
        assert closed_still is not None and open_still is not None
        cfile, cbefore = _admit(closed_still, root=root)
        ofile, obefore = _admit(open_still, root=root)
    result = inspect_private_obs_artifact(
        movie, allowed_root=root, owner_approved=True,
        host_confirms_recording_stopped=True,
        host_confirms_broadcast_inactive=True,
        selected_audio_track=selected_audio_track,
        ffprobe=ffprobe, ffmpeg=ffmpeg,
    )
    av = None
    if requested_mouth:
        assert cfile is not None and ofile is not None and mouth_roi is not None
        av = audit_local_obs_recording(
            movie, closed_still=cfile, open_still=ofile, roi=mouth_roi,
            audio_track=selected_audio_track,
            host_confirms_isolated_star_audio=True,
            host_attests_actual_output=True,
            ffmpeg=ffmpeg, ffprobe=ffprobe,
        )
        status = {
            "eligible_for_owner_review": "av_review_candidate",
            "needs_improvement": "av_needs_improvement",
            "insufficient_evidence": "av_inconclusive",
        }[av.report.verdict]
    else:
        status = "decodable_only"
    if (not _unchanged(movie, before)
            or (cfile is not None and cbefore is not None and not _unchanged(cfile, cbefore))
            or (ofile is not None and obefore is not None and not _unchanged(ofile, obefore))):
        raise PrivateRehearsalAuditError("media changed during private audit")
    return PrivateRehearsalEvidence(
        status=status, duration_s=result.duration_s,
        decoded_video_frames=result.video_frames,
        audio_stream_count=result.audio_streams,
        selected_audio_track=selected_audio_track,
        av_verdict=av.report.verdict if av is not None else None,
        estimated_mouth_lag_ms=av.report.estimated_mouth_lag_ms if av is not None else None,
        voiced_mouth_coverage=av.report.voiced_mouth_coverage if av is not None else None,
        silent_mouth_rate=av.report.silent_mouth_rate if av is not None else None,
        best_alignment_f1=av.report.best_alignment_f1 if av is not None else None,
        observed_av_frames=av.observed_frames if av is not None else None,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="STAR private OBS file and optional mouth/voice audit (READ ONLY)"
    )
    parser.add_argument("--recording", required=True)
    parser.add_argument("--allowed-root", required=True)
    parser.add_argument("--owner-approved", action="store_true")
    parser.add_argument("--recording-stopped", action="store_true")
    parser.add_argument("--broadcast-inactive", action="store_true")
    parser.add_argument("--audio-track", type=int, default=0)
    parser.add_argument("--closed-still")
    parser.add_argument("--open-still")
    parser.add_argument("--mouth-roi", nargs=4, type=int, metavar=("X", "Y", "W", "H"))
    parser.add_argument("--isolated-star-audio", action="store_true")
    parser.add_argument("--actual-output", action="store_true")
    options = parser.parse_args(argv)
    try:
        mouth = MouthROI(*options.mouth_roi) if options.mouth_roi else None
        report = audit_private_rehearsal(
            options.recording, allowed_root=options.allowed_root,
            owner_approved=options.owner_approved,
            host_confirms_recording_stopped=options.recording_stopped,
            host_confirms_broadcast_inactive=options.broadcast_inactive,
            selected_audio_track=options.audio_track,
            closed_still=options.closed_still,
            open_still=options.open_still,
            mouth_roi=mouth,
            host_confirms_isolated_star_audio=options.isolated_star_audio,
            host_attests_actual_output=options.actual_output,
        )
    except (PermissionError, ValueError, RecordingArtifactError,
            AVRecordingError, PrivateRehearsalAuditError, OSError):
        print(json.dumps({
            "status": "deferred",
            "reason": "local_private_media_audit_failed_or_not_authorized",
            "broadcast_authorized": False,
        }, sort_keys=True))
        return 2
    print(report.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PrivateRehearsalAuditError", "PrivateRehearsalEvidence",
    "audit_private_rehearsal", "main",
]
