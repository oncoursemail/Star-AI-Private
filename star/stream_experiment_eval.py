"""Paired evaluation for STAR latency gains without hidden quality regressions.

The evaluator consumes content-free, paired observations from a trusted host
and independent quality labels. It never runs models, captures media, chooses
a winner automatically, or promotes a model/configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import math
import random
import re
from statistics import fmean, median
from typing import Callable, Sequence, cast

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_MAX_OBSERVATIONS = 20_000
_MAX_METRIC_MS = 1_000_000_000.0


class Variant(str, Enum):
    BASELINE = "baseline"
    CANDIDATE = "candidate"


class QualityEvidence(str, Enum):
    """Allowed independent evidence sources; model self-grading is excluded."""

    HUMAN = "human"
    HELD_OUT_TEST = "held_out_test"
    TOOL_ASSERTION = "tool_assertion"


class LatencyMetric(str, Enum):
    FIRST_CONTENT = "first_content_ms"
    FIRST_AUDIBLE = "first_audible_ms"
    INTER_TOKEN = "inter_token_ms"
    REQUEST = "request_ms"


@dataclass(frozen=True)
class ExperimentObservation:
    """One content-free measurement for one side of a matched task pair.

    IDs must be opaque and stable within the experiment. Do not put prompts,
    transcripts, usernames, paths, screenshots, audio, or model outputs here.
    """

    pair_id: str
    task_id: str
    environment_id: str
    variant: Variant
    quality_evidence: QualityEvidence
    quality_score: float
    first_content_ms: float | None = None
    first_audible_ms: float | None = None
    inter_token_ms: float | None = None
    request_ms: float | None = None
    game_frame_p99_ms: float | None = None
    audio_underrun_chunks: int | None = None
    audio_playback_chunks: int | None = None

    def __post_init__(self) -> None:
        for name in ("pair_id", "task_id", "environment_id"):
            value = getattr(self, name)
            if type(value) is not str or _ID.fullmatch(value) is None:
                raise ValueError(f"{name} must be a bounded opaque identifier")
        if not isinstance(self.variant, Variant):
            raise ValueError("variant must be Variant")
        if not isinstance(self.quality_evidence, QualityEvidence):
            raise ValueError("quality_evidence must be independent allowed evidence")
        if type(self.quality_score) not in (int, float):
            raise ValueError("quality_score must be a finite number in 0..1")
        if not math.isfinite(float(self.quality_score)) or not 0 <= self.quality_score <= 1:
            raise ValueError("quality_score must be a finite number in 0..1")

        for name in (
            "first_content_ms",
            "first_audible_ms",
            "inter_token_ms",
            "request_ms",
            "game_frame_p99_ms",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            if type(value) not in (int, float):
                raise ValueError(f"{name} must be a finite positive number")
            if not math.isfinite(float(value)) or not 0 < value <= _MAX_METRIC_MS:
                raise ValueError(f"{name} must be a finite positive number")

        underruns = self.audio_underrun_chunks
        playback = self.audio_playback_chunks
        if (underruns is None) != (playback is None):
            raise ValueError("audio underruns and playback chunks must be supplied together")
        if underruns is not None and playback is not None:
            if type(underruns) is not int or type(playback) is not int:
                raise ValueError("audio chunk counts must be integers")
            if not 0 <= underruns <= playback <= 1_000_000_000:
                raise ValueError("audio chunk counts are outside the supported range")
            if playback == 0:
                raise ValueError("audio playback_chunks must be positive when supplied")


@dataclass(frozen=True)
class ExperimentPolicy:
    """Predeclared decision policy; thresholds are not tuned after seeing results."""

    primary_latency: LatencyMetric = LatencyMetric.FIRST_AUDIBLE
    min_pairs: int = 30
    bootstrap_replicates: int = 2_000
    confidence_level: float = 0.95
    quality_noninferiority_margin: float = 0.02
    max_frame_time_regression_pct: float | None = None
    max_audio_underrun_rate_increase: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.primary_latency, LatencyMetric):
            raise ValueError("primary_latency must be LatencyMetric")
        if type(self.min_pairs) is not int or not 2 <= self.min_pairs <= 10_000:
            raise ValueError("min_pairs must be in 2..10000")
        if type(self.bootstrap_replicates) is not int or not 200 <= self.bootstrap_replicates <= 20_000:
            raise ValueError("bootstrap_replicates must be in 200..20000")
        if type(self.confidence_level) not in (int, float):
            raise ValueError("confidence_level must be between 0.8 and 0.99")
        if not math.isfinite(float(self.confidence_level)) or not 0.8 <= self.confidence_level <= 0.99:
            raise ValueError("confidence_level must be between 0.8 and 0.99")
        _margin(self.quality_noninferiority_margin, "quality_noninferiority_margin")
        if self.max_frame_time_regression_pct is not None:
            _margin(self.max_frame_time_regression_pct, "max_frame_time_regression_pct")
        if self.max_audio_underrun_rate_increase is not None:
            _margin(self.max_audio_underrun_rate_increase, "max_audio_underrun_rate_increase")


def _margin(value: object, label: str) -> None:
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite fraction in 0..1")
    numeric = float(cast(int | float, value))
    if not math.isfinite(numeric) or not 0 <= numeric <= 1:
        raise ValueError(f"{label} must be a finite fraction in 0..1")


def _seed(experiment_id: str, metric: str) -> int:
    digest = hashlib.sha256(f"{experiment_id}:{metric}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _nearest_rank(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(probability * len(ordered)))
    return ordered[rank - 1]


def _bootstrap_interval(
    values: list[float],
    *,
    confidence: float,
    replicates: int,
    seed: int,
    statistic: Callable[[list[float]], float],
) -> tuple[float, float] | None:
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    estimates: list[float] = []
    size = len(values)
    for _ in range(replicates):
        sample = [values[rng.randrange(size)] for _ in range(size)]
        estimates.append(statistic(sample))
    tail = (1.0 - confidence) / 2.0
    return (
        _nearest_rank(estimates, tail),
        _nearest_rank(estimates, 1.0 - tail),
    )


def _gate(name: str, status: str, observed: object, limit: object, note: str) -> dict[str, object]:
    return {
        "name": name,
        "status": status,
        "observed": observed,
        "limit": limit,
        "note": note,
    }


def evaluate_experiment(
    experiment_id: str,
    observations: Sequence[ExperimentObservation],
    policy: ExperimentPolicy | None = None,
) -> dict[str, object]:
    """Evaluate a paired baseline/candidate experiment with quality guardrails.

    The speed ratio is candidate/baseline; values below 1.0 are faster.
    Quality deltas are candidate minus baseline; positive values are better.
    All confidence intervals are deterministic paired bootstrap intervals.
    A result is only a recommendation for human review, never promotion.
    """
    if type(experiment_id) is not str or _ID.fullmatch(experiment_id) is None:
        raise ValueError("experiment_id must be a bounded opaque identifier")
    if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes)):
        raise TypeError("observations must be a bounded sequence")
    if len(observations) > _MAX_OBSERVATIONS:
        raise ValueError("observation count exceeds the bounded limit")
    active_policy = policy if policy is not None else ExperimentPolicy()
    if not isinstance(active_policy, ExperimentPolicy):
        raise TypeError("policy must be ExperimentPolicy")

    pairs: dict[str, dict[Variant, ExperimentObservation]] = {}
    for observation in observations:
        if not isinstance(observation, ExperimentObservation):
            raise TypeError("every observation must be ExperimentObservation")
        pair = pairs.setdefault(observation.pair_id, {})
        if observation.variant in pair:
            raise ValueError("duplicate variant for a paired task")
        pair[observation.variant] = observation

    matched: list[tuple[ExperimentObservation, ExperimentObservation]] = []
    for pair_id in sorted(pairs):
        pair = pairs[pair_id]
        if set(pair) != {Variant.BASELINE, Variant.CANDIDATE}:
            raise ValueError("every pair must contain exactly one baseline and one candidate")
        baseline = pair[Variant.BASELINE]
        candidate = pair[Variant.CANDIDATE]
        if (
            baseline.task_id != candidate.task_id
            or baseline.environment_id != candidate.environment_id
            or baseline.quality_evidence is not candidate.quality_evidence
        ):
            raise ValueError("paired observations must match task, environment, and evidence source")
        if getattr(baseline, active_policy.primary_latency.value) is None:
            raise ValueError("primary latency is missing from a baseline pair")
        if getattr(candidate, active_policy.primary_latency.value) is None:
            raise ValueError("primary latency is missing from a candidate pair")
        matched.append((baseline, candidate))

    if not matched:
        raise ValueError("at least one complete pair is required")

    quality_deltas = [
        float(candidate.quality_score) - float(baseline.quality_score)
        for baseline, candidate in matched
    ]
    latency_logs = [
        math.log(
            float(getattr(candidate, active_policy.primary_latency.value))
            / float(getattr(baseline, active_policy.primary_latency.value))
        )
        for baseline, candidate in matched
    ]
    count = len(matched)
    reps = active_policy.bootstrap_replicates
    confidence = float(active_policy.confidence_level)

    quality_ci = _bootstrap_interval(
        quality_deltas,
        confidence=confidence,
        replicates=reps,
        seed=_seed(experiment_id, "quality"),
        statistic=fmean,
    )
    latency_log_ci = _bootstrap_interval(
        latency_logs,
        confidence=confidence,
        replicates=reps,
        seed=_seed(experiment_id, "latency"),
        statistic=median,
    )
    latency_ratio = math.exp(median(latency_logs))
    latency_ratio_ci = (
        [math.exp(latency_log_ci[0]), math.exp(latency_log_ci[1])]
        if latency_log_ci is not None else None
    )

    gates: list[dict[str, object]] = []
    enough_pairs = count >= active_policy.min_pairs

    if not enough_pairs or quality_ci is None:
        quality_status = "INCONCLUSIVE"
    elif quality_ci[0] >= -active_policy.quality_noninferiority_margin:
        quality_status = "PASS"
    elif quality_ci[1] < -active_policy.quality_noninferiority_margin:
        quality_status = "FAIL"
    else:
        quality_status = "INCONCLUSIVE"
    gates.append(_gate(
        "quality_noninferiority",
        quality_status,
        {
            "mean_delta": round(fmean(quality_deltas), 6),
            "confidence_interval": [round(v, 6) for v in quality_ci] if quality_ci else None,
        },
        {"minimum_delta": -active_policy.quality_noninferiority_margin},
        "Independent quality evidence; model self-grading is not accepted.",
    ))

    if not enough_pairs or latency_log_ci is None:
        latency_status = "INCONCLUSIVE"
    elif latency_log_ci[1] < 0:
        latency_status = "PASS"
    elif latency_log_ci[0] > 0:
        latency_status = "FAIL"
    else:
        latency_status = "INCONCLUSIVE"
    gates.append(_gate(
        "primary_latency_improvement",
        latency_status,
        {
            "median_candidate_to_baseline_ratio": round(latency_ratio, 6),
            "ratio_confidence_interval": (
                [round(v, 6) for v in latency_ratio_ci] if latency_ratio_ci else None
            ),
        },
        {"ratio_below": 1.0},
        f"Primary metric: {active_policy.primary_latency.value}; below 1.0 is faster.",
    ))

    if active_policy.max_frame_time_regression_pct is not None:
        frame_logs: list[float] = []
        frame_complete = True
        for baseline, candidate in matched:
            if baseline.game_frame_p99_ms is None or candidate.game_frame_p99_ms is None:
                frame_complete = False
                break
            frame_logs.append(math.log(candidate.game_frame_p99_ms / baseline.game_frame_p99_ms))
        frame_ci = (
            _bootstrap_interval(
                frame_logs,
                confidence=confidence,
                replicates=reps,
                seed=_seed(experiment_id, "frame"),
                statistic=median,
            )
            if frame_complete else None
        )
        threshold = math.log1p(active_policy.max_frame_time_regression_pct)
        if not enough_pairs or frame_ci is None:
            frame_status = "INCONCLUSIVE"
        elif frame_ci[1] <= threshold:
            frame_status = "PASS"
        elif frame_ci[0] > threshold:
            frame_status = "FAIL"
        else:
            frame_status = "INCONCLUSIVE"
        frame_ratio_ci = [math.exp(v) for v in frame_ci] if frame_ci else None
        gates.append(_gate(
            "game_frame_time_guardrail",
            frame_status,
            {"ratio_confidence_interval": frame_ratio_ci},
            {"maximum_regression_ratio": 1.0 + active_policy.max_frame_time_regression_pct},
            "Requires paired p99 frame-time measurements from the same game workload.",
        ))

    if active_policy.max_audio_underrun_rate_increase is not None:
        audio_deltas: list[float] = []
        audio_complete = True
        for baseline, candidate in matched:
            if (
                baseline.audio_underrun_chunks is None
                or candidate.audio_underrun_chunks is None
                or baseline.audio_playback_chunks is None
                or candidate.audio_playback_chunks is None
            ):
                audio_complete = False
                break
            base_rate = baseline.audio_underrun_chunks / baseline.audio_playback_chunks
            candidate_rate = candidate.audio_underrun_chunks / candidate.audio_playback_chunks
            audio_deltas.append(candidate_rate - base_rate)
        audio_ci = (
            _bootstrap_interval(
                audio_deltas,
                confidence=confidence,
                replicates=reps,
                seed=_seed(experiment_id, "audio"),
                statistic=fmean,
            )
            if audio_complete else None
        )
        margin = active_policy.max_audio_underrun_rate_increase
        if not enough_pairs or audio_ci is None:
            audio_status = "INCONCLUSIVE"
        elif audio_ci[1] <= margin:
            audio_status = "PASS"
        elif audio_ci[0] > margin:
            audio_status = "FAIL"
        else:
            audio_status = "INCONCLUSIVE"
        gates.append(_gate(
            "audio_underrun_guardrail",
            audio_status,
            {
                "mean_rate_delta": round(fmean(audio_deltas), 6) if audio_deltas else None,
                "confidence_interval": [round(v, 6) for v in audio_ci] if audio_ci else None,
            },
            {"maximum_rate_increase": margin},
            "Uses underrun chunks divided by playback chunks for each paired run.",
        ))

    statuses = {gate["status"] for gate in gates}
    decision = (
        "REGRESSION" if "FAIL" in statuses
        else "IMPROVED" if statuses == {"PASS"}
        else "INCONCLUSIVE"
    )
    return {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "decision": decision,
        "pair_count": count,
        "required_pairs": active_policy.min_pairs,
        "primary_latency": active_policy.primary_latency.value,
        "quality_evidence": matched[0][0].quality_evidence.value,
        "metrics": {
            "mean_quality_delta": round(fmean(quality_deltas), 6),
            "median_latency_ratio": round(latency_ratio, 6),
            "latency_ratio_confidence_interval": (
                [round(v, 6) for v in latency_ratio_ci] if latency_ratio_ci else None
            ),
        },
        "gates": gates,
        "notes": [
            "Paired bootstrap intervals are descriptive decision aids, not a guarantee of future performance.",
            "Randomized or counterbalanced run order and identical workloads must be enforced by the experiment runner.",
            "The evaluator does not prove sensor provenance or label correctness.",
            "INCONCLUSIVE never authorizes promotion; candidate changes require human review.",
            "No prompts, transcripts, model outputs, viewer identities, audio, or screenshots are stored.",
        ],
    }
