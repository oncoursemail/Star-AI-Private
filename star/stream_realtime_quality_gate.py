"""Independent, privacy-minimal quality gate for STAR's paired VTuber speed trials.

Existing realtime benchmarking measures first audio, FPS and VRAM. Faster
speech is not an improvement if Star says wrong things, invents game wins, or
OBS fails to capture the audio. This optional read-only gate joins a bounded
host-reviewed quality witness to *every* baseline/candidate run before making
any manual-pilot recommendation.

Human/evaluator verdicts are operator attestations, NOT cryptographically
verified facts. No speech, images, transcripts, player IDs or recordings enter
this module; it never switches a model, broadcasts, or authorizes game input.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Iterable

from .stream_realtime_benchmark import RealtimeRun, compare_realtime

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


@dataclass(frozen=True)
class QualityWitness:
    """One independently assessed run, keyed to its benchmark pair/variant.

    correct means the response met a predeclared task rubric, and
    grounded means it made no unsupported gameplay/event claims.
    obs_audible and av_offset_ms are measured from an independent OBS
    playback recording, not inferred from TTS enqueue or device callbacks.
    The trusted host must ensure clocks are comparable and audio is captured.
    """

    pair_id: str
    variant: str
    correct: bool
    grounded: bool
    obs_audible: bool
    av_offset_ms: float | None

    def __post_init__(self) -> None:
        if type(self.pair_id) is not str or _ID.fullmatch(self.pair_id) is None:
            raise ValueError("witness needs a bounded pair_id")
        if type(self.variant) is not str or self.variant not in ("baseline", "candidate"):
            raise ValueError("variant must be baseline or candidate")
        if any(type(v) is not bool for v in (
            self.correct, self.grounded, self.obs_audible,
        )):
            raise ValueError("witness flags must be booleans")
        offset = self.av_offset_ms
        if self.obs_audible:
            if offset is None or type(offset) not in (float, int):
                raise ValueError("captured audio requires numeric A/V offset")
            if not -5000 <= offset <= 5000 or not math.isfinite(float(offset)):
                raise ValueError("captured audio requires bounded measured A/V offset")
        elif offset is not None:
            raise ValueError("uncaptured audio cannot have an A/V offset")


@dataclass(frozen=True)
class QualityGateReport:
    """Only summary counts; no private pair IDs or raw event contents."""

    status: str
    reason: str
    matched_pairs: int
    witness_coverage: int
    expected_witnesses: int
    baseline_correct: int
    candidate_correct: int
    candidate_ungrounded: int
    candidate_obs_missing: int
    candidate_av_p95_ms: float | None
    candidate_av_max_ms: float | None
    speed_verdict: str
    authorized_to_stream: bool = False
    note: str = ("Operator-attested review and recording metrics only; "
                 "not independently authenticated, live-tested or deployment authority.")


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[math.ceil(0.95 * len(ordered)) - 1], 2)


def assess_quality_gate(
    runs: Iterable[RealtimeRun], witnesses: Iterable[QualityWitness], *,
    minimum_pairs: int = 20, gpu_budget_mib: float = 6656,
    max_av_p95_ms: float = 100, minimum_correct_ratio: float = 0.95,
) -> QualityGateReport:
    """Advisory pilot gate: good speed PLUS no visible quality regression.

    All pairs must be present, every candidate must have captured audio and
    grounded event claims, the candidate must meet a minimum correct rate
    without losing to baseline, and A/V p95 must stay under its budget.
    Missing witness data never becomes a false quality success.
    """
    if (type(max_av_p95_ms) not in (int, float)
            or not 20 <= max_av_p95_ms <= 1000
            or not math.isfinite(float(max_av_p95_ms))):
        raise ValueError("A/V sync budget must be finite and 20..1000 ms")
    if (type(minimum_correct_ratio) not in (int, float)
            or not 0.5 <= minimum_correct_ratio <= 1.0
            or not math.isfinite(float(minimum_correct_ratio))):
        raise ValueError("correctness ratio must be between 0.5 and 1")
    # Bound materialization; compare_realtime independently rejects malformed
    # runs, cross-game comparisons, repeated pairs and insufficient frame data.
    observed_runs: list[RealtimeRun] = []
    for run in runs:
        if len(observed_runs) >= 1000:
            raise ValueError("too many benchmark runs")
        observed_runs.append(run)
    speed = compare_realtime(
        observed_runs, minimum_pairs=minimum_pairs,
        gpu_budget_mib=gpu_budget_mib,
    )
    expected = {(run.pair_id, run.variant) for run in observed_runs}
    seen: dict[tuple[str, str], QualityWitness] = {}
    for item in witnesses:
        if not isinstance(item, QualityWitness):
            raise TypeError("expected only bounded QualityWitness records")
        key = (item.pair_id, item.variant)
        if key in seen or len(seen) >= 1000:
            raise ValueError("duplicate or oversized quality witness batch")
        if key not in expected:
            raise ValueError("quality witness does not match a measured run")
        seen[key] = item
    complete = len(seen) == len(expected) and all(
        (pair, "baseline") in seen and (pair, "candidate") in seen
        for pair, _variant in expected
    )
    baseline = [v for (pair, variant), v in seen.items() if variant == "baseline"]
    candidate = [v for (pair, variant), v in seen.items() if variant == "candidate"]
    base_correct = sum(w.correct for w in baseline)
    candidate_correct = sum(w.correct for w in candidate)
    ungrounded = sum(not w.grounded for w in candidate)
    obs_missing = sum(not w.obs_audible for w in candidate)
    offsets = [abs(float(w.av_offset_ms)) for w in candidate
               if w.obs_audible and w.av_offset_ms is not None]
    av_p95 = _p95(offsets)
    av_max = round(max(offsets), 2) if offsets else None
    pairs = len({pair for pair, _variant in expected})
    def report(status: str, reason: str) -> QualityGateReport:
        return QualityGateReport(
            status, reason, pairs, len(seen), len(expected), base_correct,
            candidate_correct, ungrounded, obs_missing, av_p95, av_max, speed.verdict,
        )

    if not complete or pairs < minimum_pairs or speed.incomplete_pairs:
        return report("insufficient_evidence", "missing_or_unpaired_quality_witness")
    if any(not w.obs_audible for w in baseline):
        return report("insufficient_evidence", "baseline_obs_audio_not_verified")
    if (ungrounded or obs_missing or candidate_correct < base_correct
            or candidate_correct / pairs < float(minimum_correct_ratio)
            or av_p95 is None or av_p95 > float(max_av_p95_ms)
            or av_max is None or av_max > 2 * float(max_av_p95_ms)):
        return report("quality_regressed", "correctness_grounding_obs_or_av_guardrail")
    if speed.verdict != "eligible_for_manual_pilot":
        return report("speed_not_verified", "paired_latency_fps_or_gpu_gate_not_met")
    return report("eligible_for_manual_rehearsal", "all_measured_quality_guardrails_met")


__all__ = ["QualityWitness", "QualityGateReport", "assess_quality_gate"]
