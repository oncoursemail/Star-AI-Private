"""Conservative cross-lane coherence checks for a PRIVATE local VTuber rehearsal.

These checks compare measurements that claim to describe ONE contiguous
recording. They cannot establish provenance, that OBS was not broadcasting,
that actions affected the game, or that a subject is human. Trusted host
assertions and independent owner review remain essential.

No input devices, files, recording paths, network, or model invocation.
"""
from __future__ import annotations

import math

from .stream_av_recording_host import RecordingAVResult
from .stream_obs_recording_artifact_probe import RecordingArtifactReport


def _finite_number(value: object, low: float, high: float) -> bool:
    if not isinstance(value, (float, int)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value) and low <= value <= high
    except OverflowError:
        return False


def _close(actual: float, reference: float, *, floor: float, portion: float) -> bool:
    return abs(actual - reference) <= max(floor, reference * portion)


def check_rehearsal_crosslane_coherence(
    *,
    recording: RecordingArtifactReport,
    av: RecordingAVResult,
    obs_duration_s: float,
    obs_output_frames: int,
) -> tuple[str, ...]:
    """Check matching *reported* clip/audio/OBS timelines; no authorizations.

    OBS counter deltas must first pass stream_private_rehearsal_scorecard's
    independent monotonic validation. An owner must assert these measurements
    were actually collected from the same immutable stopped private recording.
    This makes obviously contradictory reports fail rather than proving origin.
    """
    if type(recording) is not RecordingArtifactReport or type(av) is not RecordingAVResult:
        return ("crosslane_report_missing",)

    missing: list[str] = []
    duration = recording.duration_s
    frames = recording.video_frames
    if (not _finite_number(duration, 6.0, 120.0)
            or type(frames) is not int or not 180 <= frames <= 28800
            or not 8 <= frames / duration <= 240
            or type(recording.video_width) is not int
            or type(recording.video_height) is not int
            or not 160 <= recording.video_width <= 8192
            or not 120 <= recording.video_height <= 8192
            or type(recording.audio_streams) is not int
            or not 1 <= recording.audio_streams <= 16
            or type(recording.selected_audio_track) is not int
            or not 0 <= recording.selected_audio_track < recording.audio_streams):
        return ("private_recording_metadata_inconsistent",)

    if (not _finite_number(obs_duration_s, 6.0, 120.0)
            or type(obs_output_frames) is not int or obs_output_frames < 120):
        return ("crosslane_obs_timeline_missing",)

    if not _close(duration, obs_duration_s, floor=1.25, portion=0.10):
        missing.append("recording_obs_duration_mismatch")

    # For a single, continuous OBS output, frame totals should broadly agree.
    # Allow encoder start/stop transients and minor frame/timestamp rounding.
    # The OBS counters are not independent evidence of recording identity.
    if abs(frames - obs_output_frames) > max(12, round(max(frames, obs_output_frames) * .12)):
        missing.append("recording_obs_frame_count_mismatch")

    av_duration = av.report.duration_ms
    av_frames = av.observed_frames
    if (not _finite_number(av_duration, 6000.0, 120000.0)
            or type(av_frames) is not int or not 180 <= av_frames <= 3600):
        missing.append("recording_av_sample_timeline_missing")
    else:
        # AV host downsamples to 30 Hz. Matching reported seconds guards against
        # mixing a valid short speech clip with a different longer recording.
        if not _close(av_duration / 1000, duration, floor=.35, portion=.03):
            missing.append("recording_av_duration_mismatch")
        if not _close(av_frames, av_duration / 1000 * 30,
                      floor=5, portion=.07):
            missing.append("recording_av_frame_rate_mismatch")

    report = av.report
    if (type(report.sample_count) is not int
            or report.sample_count != av_frames
            or not _finite_number(av.calibration_separation, 0, 1)
            or not _finite_number(report.best_alignment_f1, 0, 1)
            or type(report.estimated_mouth_lag_ms) is not int
            or not -250 <= report.estimated_mouth_lag_ms <= 250
            or report.verified_humanlike is not False
            or report.automated_deployment_allowed is not False):
        missing.append("recording_av_alignment_statistics_invalid")

    return tuple(missing)


__all__ = ["check_rehearsal_crosslane_coherence"]
