"""Offline joined A/B guard: faster speech must NOT damage Star's visible VTuber.

Composes *existing* real-audio/game benchmark, OBS frame counters and decoded
recording->audio/mouth evidence. No OBS control, voice, inference, gameplay,
streaming, file reads, automatic model switching or permission changes here.

A trusted host must precommit pair IDs, isolate Star's audible audio, establish
one output capture clock, assign recording digest/OBS process ID, and ensure the
two clips really belong to their declared windows. This module cannot attest
that evidence itself. Results are advisory and never authorize publication.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Sequence

from .stream_av_recording_host import RecordingAVResult
from .stream_av_sync_audit import AVSyncReport
from .stream_obs_qos_gate import (
    ObsFrameWindow, ObsQoSReport, compare_realtime_with_obs,
)
from .stream_realtime_benchmark import RealtimeRun

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_CLOCK = 1e13


def _clock(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("capture clock must be host monotonic milliseconds")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError("invalid capture clock") from exc
    if not math.isfinite(result) or not 0 <= result <= _MAX_CLOCK:
        raise ValueError("invalid capture clock")
    return result


def _fraction(value: object, label: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a measured fraction")
    try:
        fraction = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"invalid {label}") from exc
    if not math.isfinite(fraction) or not 0 <= fraction <= 1:
        raise ValueError(f"invalid {label}")
    return fraction


@dataclass(frozen=True)
class OutputAVWindow:
    """One explicitly linked real OBS decoded clip; no raw recording/identities.

    capture_start_ms and capture_end_ms use the SAME host monotonic clock as
    ObsFrameWindow, not a decoder's media presentation timeline. A host must
    make that alignment, and keep its recording digest outside model prompts.
    """

    pair_id: str
    variant: str
    game_id: str
    game_version: str
    obs_session_id: str
    recording_sha256: str
    capture_start_ms: float
    capture_end_ms: float
    output_capture_attested: bool
    isolated_star_audio_attested: bool
    report: AVSyncReport

    def __post_init__(self) -> None:
        for name in ("pair_id", "game_id", "game_version", "obs_session_id"):
            value = getattr(self, name)
            if type(value) is not str or not _ID.fullmatch(value):
                raise ValueError(f"{name} must be a bounded symbolic ID")
        if type(self.variant) is not str or self.variant not in {"baseline", "candidate"}:
            raise ValueError("variant must be baseline or candidate")
        if type(self.recording_sha256) is not str or not _SHA.fullmatch(
            self.recording_sha256
        ):
            raise ValueError("recording digest must be lowercase SHA-256")
        start = _clock(self.capture_start_ms)
        end = _clock(self.capture_end_ms)
        if not 6000 <= end - start <= 120000:
            raise ValueError("capture duration must be 6..120 seconds")
        if (type(self.output_capture_attested) is not bool
                or type(self.isolated_star_audio_attested) is not bool):
            raise ValueError("host output/audio attestations must be booleans")
        if type(self.report) is not AVSyncReport:
            raise TypeError("expected a completed AVSyncReport")
        report = self.report
        if report.verdict not in {
            "eligible_for_owner_review", "needs_improvement", "insufficient_evidence",
        }:
            raise ValueError("unknown AV synchronization verdict")
        if type(report.verified_humanlike) is not bool or report.verified_humanlike:
            raise ValueError("no automatic humanlike claim can be accepted")
        if (type(report.automated_deployment_allowed) is not bool
                or report.automated_deployment_allowed):
            raise ValueError("no automatic deployment authorization is accepted")
        if type(report.sample_count) is not int or not 0 <= report.sample_count <= 8000:
            raise ValueError("invalid AV sample count")
        duration = _clock(report.duration_ms)
        if duration and abs(duration - (end - start)) > 150:
            raise ValueError("AV report duration does not match declared clip")
        if report.verdict != "insufficient_evidence":
            if report.sample_count < 180 or duration < 6000:
                raise ValueError("accepted AV metrics need a complete observation")
            if (type(report.estimated_mouth_lag_ms) is not int
                    or not -240 <= report.estimated_mouth_lag_ms <= 240
                    or report.estimated_mouth_lag_ms % 20):
                raise ValueError("invalid measured mouth lag")
            for name in ("best_alignment_f1", "zero_lag_f1",
                         "voiced_mouth_coverage", "silent_mouth_rate"):
                _fraction(getattr(report, name), name)
            if (type(report.audible_transitions) is not int
                    or report.audible_transitions < 6):
                raise ValueError("missing audible transitions")

    @classmethod
    def from_recording(
        cls, *, pair_id: str, variant: str, game_id: str, game_version: str,
        obs_session_id: str, recording_sha256: str, capture_start_ms: float,
        capture_end_ms: float, decoded: RecordingAVResult,
    ) -> OutputAVWindow:
        """Accept measured, previously decoded local media, not a model estimate.

        Caller supplies independent capture clock alignment and file digest.
        Decoder attestations are host assertions, NOT cryptographic proof.
        """
        if type(decoded) is not RecordingAVResult:
            raise TypeError("expected decoded recording observation")
        if decoded.provenance != "local_decoded_media_unverified_by_this_module":
            raise ValueError("unrecognized decoded-media provenance")
        return cls(
            pair_id, variant, game_id, game_version, obs_session_id,
            recording_sha256, capture_start_ms, capture_end_ms,
            decoded.captured_output_attested, decoded.isolated_star_audio_attested,
            decoded.report,
        )

    @property
    def duration_ms(self) -> float:
        return float(self.capture_end_ms - self.capture_start_ms)

    @property
    def independently_usable(self) -> bool:
        return (self.output_capture_attested and self.isolated_star_audio_attested
                and self.report.verdict != "insufficient_evidence")


@dataclass(frozen=True)
class StreamOutputQoEReport:
    """No pair IDs, files, times, secrets, recordings or viewer content."""

    verdict: str  # eligible_for_owner_review | regressed | inconclusive
    speed_and_obs_verdict: str
    complete_av_pairs: int
    missing_av_windows: int
    unverified_av_windows: int
    degraded_av_pairs: int
    worst_candidate_abs_mouth_lag_ms: int | None
    mean_candidate_alignment_f1: float | None
    mean_candidate_silent_mouth_rate: float | None
    note: str = (
        "offline matched-output guard; humanlike performance and source "
        "authenticity unproven; no automatic stream or model changes"
    )


def compare_stream_output_qoe(
    runs: Sequence[RealtimeRun],
    obs_windows: Sequence[ObsFrameWindow],
    av_windows: Sequence[OutputAVWindow],
    *, minimum_pairs: int = 20, gpu_budget_mib: float = 6656,
    max_extra_mouth_lag_ms: int = 40, max_f1_loss: float = 0.04,
    max_silent_mouth_increase: float = 0.025,
    max_coverage_loss: float = 0.06,
) -> StreamOutputQoEReport:
    """Require speed + game FPS + OBS frames + decoded avatar output all pass.

    Per-pair limits are conservative experimental thresholds, NOT a standard
    for perceived humanness. Missing/unauthenticated windows are inconclusive;
    independently observed candidate damage is regressed, even if faster.
    Both verdicts allow *owner review only*, never live configuration changes.
    """
    if (type(runs) not in (list, tuple) or type(obs_windows) not in (list, tuple)
            or type(av_windows) not in (list, tuple)):
        raise TypeError("expected materialized bounded paired measurements")
    if type(max_extra_mouth_lag_ms) is not int or not 0 <= max_extra_mouth_lag_ms <= 100:
        raise ValueError("invalid additional mouth lag tolerance")
    for label, value, maximum in (
        ("max_f1_loss", max_f1_loss, 0.25),
        ("max_silent_mouth_increase", max_silent_mouth_increase, 0.2),
        ("max_coverage_loss", max_coverage_loss, 0.25),
    ):
        if _fraction(value, label) > maximum:
            raise ValueError(f"{label} exceeds conservative bounds")

    obs: ObsQoSReport = compare_realtime_with_obs(
        runs, obs_windows, minimum_pairs=minimum_pairs,
        gpu_budget_mib=gpu_budget_mib,
    )
    expected = {(r.pair_id, r.variant): r for r in runs}
    witnesses = {(w.pair_id, w.variant): w for w in obs_windows}
    received: dict[tuple[str, str], OutputAVWindow] = {}
    recording_hashes: set[str] = set()
    if len(av_windows) > 1000:
        raise ValueError("too many AV observations")
    for clip in av_windows:
        if type(clip) is not OutputAVWindow:
            raise TypeError("expected OutputAVWindow")
        key = (clip.pair_id, clip.variant)
        if key not in expected or key not in witnesses:
            raise ValueError("unmatched AV recording")
        if key in received or clip.recording_sha256 in recording_hashes:
            raise ValueError("duplicate observation or reused AV recording")
        run, window = expected[key], witnesses[key]
        if (clip.game_id, clip.game_version) != (run.game_id, run.game_version):
            raise ValueError("AV recording game scope mismatch")
        if clip.obs_session_id != window.session_id:
            raise ValueError("AV capture OBS process mismatch")
        if not (window.start_ms <= clip.capture_start_ms < clip.capture_end_ms
                <= window.end_ms):
            raise ValueError("AV clip must be inside the paired OBS window")
        received[key] = clip
        recording_hashes.add(clip.recording_sha256)

    missing = len(expected) - len(received)
    unverified = sum(not row.independently_usable for row in received.values())
    groups = {
        pair_id: (received[(pair_id, "baseline")], received[(pair_id, "candidate")])
        for pair_id in {run.pair_id for run in runs}
        if (pair_id, "baseline") in received and (pair_id, "candidate") in received
    }
    valid_pairs = [pair for pair in groups.values()
                   if pair[0].independently_usable and pair[1].independently_usable]
    candidates = [pair[1].report for pair in valid_pairs]
    degraded = 0
    for baseline, candidate in valid_pairs:
        if abs(baseline.duration_ms - candidate.duration_ms) > (
            0.25 * max(baseline.duration_ms, candidate.duration_ms)
        ):
            raise ValueError("unfair A/B audio-video clip exposure")
        a, b = baseline.report, candidate.report
        assert a.estimated_mouth_lag_ms is not None
        assert b.estimated_mouth_lag_ms is not None
        assert a.best_alignment_f1 is not None and b.best_alignment_f1 is not None
        assert a.silent_mouth_rate is not None and b.silent_mouth_rate is not None
        assert a.voiced_mouth_coverage is not None
        assert b.voiced_mouth_coverage is not None
        if (b.verdict == "needs_improvement"
                or abs(b.estimated_mouth_lag_ms) - abs(a.estimated_mouth_lag_ms)
                > max_extra_mouth_lag_ms
                or a.best_alignment_f1 - b.best_alignment_f1 > max_f1_loss
                or b.silent_mouth_rate - a.silent_mouth_rate
                > max_silent_mouth_increase
                or a.voiced_mouth_coverage - b.voiced_mouth_coverage
                > max_coverage_loss):
            degraded += 1

    baseline_unfit = any(
        pair[0].report.verdict != "eligible_for_owner_review" for pair in valid_pairs
    )
    if degraded or obs.verdict == "regressed":
        verdict = "regressed"
    elif (missing or unverified or baseline_unfit or not expected
          or len(valid_pairs) < minimum_pairs or obs.verdict != "eligible_for_manual_pilot"):
        verdict = "inconclusive"
    else:
        verdict = "eligible_for_owner_review"

    return StreamOutputQoEReport(
        verdict=verdict,
        speed_and_obs_verdict=obs.verdict,
        complete_av_pairs=len(groups),
        missing_av_windows=missing,
        unverified_av_windows=unverified,
        degraded_av_pairs=degraded,
        worst_candidate_abs_mouth_lag_ms=(
            max(abs(r.estimated_mouth_lag_ms) for r in candidates
                if r.estimated_mouth_lag_ms is not None) if candidates else None
        ),
        mean_candidate_alignment_f1=(
            round(sum(r.best_alignment_f1 for r in candidates if r.best_alignment_f1 is not None)
                  / len(candidates), 4) if candidates else None
        ),
        mean_candidate_silent_mouth_rate=(
            round(sum(r.silent_mouth_rate for r in candidates if r.silent_mouth_rate is not None)
                  / len(candidates), 4) if candidates else None
        ),
    )


__all__ = ["OutputAVWindow", "StreamOutputQoEReport", "compare_stream_output_qoe"]
