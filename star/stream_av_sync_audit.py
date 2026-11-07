"""Offline output-observed speech-to-avatar synchronization audit for STAR.

The trusted Windows host should sample audible PCM envelope and the *rendered*
OBS/VTube Studio mouth aperture against one monotonic capture clock. Never use
generated speech or commanded rig values as substitutes for actual output.

This analyzer has no microphone, camera, networking, OBS, TTS or game control.
It does not authenticate the capture host or declare an avatar humanlike.
All results are aggregate, bounded, advisory and require owner review.
"""
from __future__ import annotations

from typing import cast

from bisect import bisect_left
from dataclasses import dataclass
import math
from typing import Sequence

_MAX_CLOCK_MS = 1e13
_MIN_SAMPLES = 180
_MAX_SAMPLES = 8000
_MIN_DURATION_MS = 6000.0
_MAX_DURATION_MS = 120000.0
_SHIFT_RANGE_MS = range(-240, 241, 20)
_MATCH_TOLERANCE_MS = 50.0
_AUDIO_THRESHOLD = 0.20
_MOUTH_THRESHOLD = 0.28


def _bounded(value: object, name: str, low: float, high: float) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a finite numeric value")
    try:
        val = float(cast(int | float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} is out of range") from exc
    if not math.isfinite(val) or not low <= val <= high:
        raise ValueError(f"{name} must be within [{low}, {high}]")
    return val


@dataclass(frozen=True)
class OutputAVSample:
    """Host-attested synchronized OUTPUT measurements, never model estimates.

    at_ms is on one local monotonic clock. audio_rms is a normalized envelope
    from the actually played output; mouth_open is measured from rendered
    avatar pixels, not the parameter Star requested to send to the avatar.
    """

    at_ms: float
    audio_rms: float
    mouth_open: float

    def __post_init__(self) -> None:
        _bounded(self.at_ms, "at_ms", 0.0, _MAX_CLOCK_MS)
        _bounded(self.audio_rms, "audio_rms", 0.0, 1.0)
        _bounded(self.mouth_open, "mouth_open", 0.0, 1.0)


@dataclass(frozen=True)
class AVSyncReport:
    verdict: str  # eligible_for_owner_review | needs_improvement | insufficient_evidence
    reason: str
    sample_count: int
    duration_ms: float
    estimated_mouth_lag_ms: int | None = None
    best_alignment_f1: float | None = None
    zero_lag_f1: float | None = None
    voiced_mouth_coverage: float | None = None
    silent_mouth_rate: float | None = None
    audible_transitions: int = 0
    verified_humanlike: bool = False
    automated_deployment_allowed: bool = False


def _score(
    times: list[float], audio_active: list[bool],
    mouth_active: list[bool], shift_ms: int,
) -> tuple[float, int, int, int, int, int]:
    """Match audible(t) to rendered-mouth(t + shift), with no interpolation.

    Positive lag means the visible mouth follows audible speech; negative
    means the mouth leads. F1 penalizes both missed speech and false mouth
    movements without letting long quiet spans inflate accuracy.
    """
    tp = fp = fn = tn = observed = 0
    for t, active in zip(times, audio_active):
        target = t + shift_ms
        index = bisect_left(times, target)
        nearest = min(
            (i for i in (index - 1, index) if 0 <= i < len(times)),
            key=lambda i: abs(times[i] - target),
            default=None,
        )
        if nearest is None or abs(times[nearest] - target) > _MATCH_TOLERANCE_MS:
            continue
        visible = mouth_active[nearest]
        observed += 1
        if active and visible:
            tp += 1
        elif active:
            fn += 1
        elif visible:
            fp += 1
        else:
            tn += 1
    denominator = 2 * tp + fp + fn
    f1 = (2 * tp / denominator) if denominator else 0.0
    return f1, observed, tp, fp, fn, tn


def audit_output_av_sync(
    samples: Sequence[OutputAVSample], *,
    output_capture_attested: bool = False,
) -> AVSyncReport:
    """Assess one bounded OBS recording's A/V synchrony, without raw media.

    The host must independently attest that both envelopes came from the
    *same actual output capture*, not from planned TTS or avatar commands.
    A boolean is not cryptographic attestation: the analyzer cannot make
    a dishonest or broken capture host trustworthy.

    For reliability, clips need 6s+, 180+ roughly 10-100ms-spaced samples,
    several speech/quiet changes, and both speech and silence. A useful
    result is only eligible for manual review; it never alters any live rig.
    """
    if type(output_capture_attested) is not bool:
        raise ValueError("output_capture_attested must be a trusted host boolean")
    if type(samples) not in (tuple, list) or len(samples) > _MAX_SAMPLES:
        raise ValueError("samples must be a bounded tuple/list of output observations")
    if any(not isinstance(sample, OutputAVSample) for sample in samples):
        raise TypeError("each observation must be an OutputAVSample")
    length = len(samples)
    if length < _MIN_SAMPLES:
        return AVSyncReport("insufficient_evidence", "too_few_samples", length, 0.0)

    times = [float(row.at_ms) for row in samples]
    duration = times[-1] - times[0]
    # Reject reversed time, gaps that could conceal failures, and fabricated
    # high-frequency duplicates. A single output clock is mandatory.
    for current, following in zip(times, times[1:]):
        gap = following - current
        if not 8.0 <= gap <= 100.0:
            raise ValueError("output capture must be strictly ordered at 10-125 Hz")
    if not _MIN_DURATION_MS <= duration <= _MAX_DURATION_MS:
        return AVSyncReport("insufficient_evidence", "duration_outside_window",
                            length, round(max(duration, 0.0), 2))

    audio = [row.audio_rms >= _AUDIO_THRESHOLD for row in samples]
    mouth = [row.mouth_open >= _MOUTH_THRESHOLD for row in samples]
    audible_fraction = sum(audio) / length
    transitions = sum(before != after for before, after in zip(audio, audio[1:]))
    if not (0.15 <= audible_fraction <= 0.85) or transitions < 6:
        return AVSyncReport(
            "insufficient_evidence", "insufficient_speech_silence_transitions",
            length, round(duration, 2), audible_transitions=transitions,
        )

    scored = {shift: _score(times, audio, mouth, shift) for shift in _SHIFT_RANGE_MS}
    # A deterministic tie-break avoids spuriously declaring large latency
    # when several offsets have equal classification scores.
    best_shift = max(
        _SHIFT_RANGE_MS,
        key=lambda shift: (scored[shift][0], -abs(shift), -shift),
    )
    best_f1, matches, tp, fp, fn, tn = scored[best_shift]
    if matches < 0.80 * length or tp + fn == 0 or fp + tn == 0:
        return AVSyncReport(
            "insufficient_evidence", "alignment_coverage_too_small",
            length, round(duration, 2), audible_transitions=transitions,
        )
    coverage = tp / (tp + fn)
    silent_rate = fp / (fp + tn)
    baseline_f1 = scored[0][0]

    # The score remains useful for local diagnostics, but no evidence from
    # generated/estimated animation may be labeled as real output verification.
    if not output_capture_attested:
        verdict, reason = "insufficient_evidence", "actual_output_capture_not_attested"
    elif (abs(best_shift) <= 100 and best_f1 >= 0.85
          and coverage >= 0.85 and silent_rate <= 0.10):
        verdict, reason = "eligible_for_owner_review", "bounded_av_sync_targets_met"
    else:
        verdict, reason = "needs_improvement", "observed_sync_or_mouth_mismatch"
    return AVSyncReport(
        verdict=verdict, reason=reason, sample_count=length,
        duration_ms=round(duration, 2),
        estimated_mouth_lag_ms=best_shift,
        best_alignment_f1=round(best_f1, 4),
        zero_lag_f1=round(baseline_f1, 4),
        voiced_mouth_coverage=round(coverage, 4),
        silent_mouth_rate=round(silent_rate, 4),
        audible_transitions=transitions,
    )


__all__ = ["OutputAVSample", "AVSyncReport", "audit_output_av_sync"]
