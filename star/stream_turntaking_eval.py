"""Causal, content-free evaluation for STAR's live conversational turn policy.

The host supplies already-labeled silence spans and timestamped end-of-turn
scores. This module evaluates a fixed policy or sweeps thresholds, action
delays, and timeouts. It does not capture audio, identify speakers, infer
labels, call models, or control playback.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Sequence

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\\Z")
_MAX_SPANS = 20_000
_MAX_SCORE_POINTS_PER_SPAN = 2_048
_MAX_TOTAL_SCORE_POINTS = 1_000_000
_MAX_DURATION_MS = 120_000
_MAX_POLICY_COMBINATIONS = 256


class PauseKind(str, Enum):
    HOLD = "hold"
    END_OF_TURN = "end_of_turn"


class ScoreSource(str, Enum):
    MODEL = "model"
    SILENCE_ONLY = "silence_only"


@dataclass(frozen=True)
class EndOfTurnScore:
    """One causal model score available after this many ms of silence."""

    elapsed_ms: int
    score: float

    def __post_init__(self) -> None:
        if type(self.elapsed_ms) is not int or not 0 <= self.elapsed_ms <= _MAX_DURATION_MS:
            raise ValueError("elapsed_ms must be a bounded nonnegative integer")
        if type(self.score) not in (int, float):
            raise ValueError("score must be finite and in 0..1")
        if not math.isfinite(float(self.score)) or not 0 <= self.score <= 1:
            raise ValueError("score must be finite and in 0..1")


@dataclass(frozen=True)
class SilenceSpan:
    """One complete pause decision window, without audio or transcript content.

    HOLD spans end when the human resumes speaking. END_OF_TURN spans end at
    the replay's observation horizon. The adapter must ensure each score used
    at elapsed_ms was computed only from information available by that time.
    """

    span_id: str
    turn_id: str
    environment_id: str
    kind: PauseKind
    duration_ms: int
    scores: tuple[EndOfTurnScore, ...]

    def __post_init__(self) -> None:
        for name in ("span_id", "turn_id", "environment_id"):
            value = getattr(self, name)
            if type(value) is not str or _ID.fullmatch(value) is None:
                raise ValueError(f"{name} must be a bounded opaque identifier")
        if not isinstance(self.kind, PauseKind):
            raise ValueError("kind must be PauseKind")
        if type(self.duration_ms) is not int or not 1 <= self.duration_ms <= _MAX_DURATION_MS:
            raise ValueError("duration_ms must be in 1..120000")
        if type(self.scores) is not tuple or len(self.scores) > _MAX_SCORE_POINTS_PER_SPAN:
            raise ValueError("scores must be a bounded tuple")
        previous = -1
        for point in self.scores:
            if not isinstance(point, EndOfTurnScore):
                raise TypeError("scores must contain EndOfTurnScore values")
            if point.elapsed_ms <= previous:
                raise ValueError("score timestamps must be strictly increasing")
            if point.elapsed_ms > self.duration_ms:
                raise ValueError("score timestamp exceeds the observed silence span")
            previous = point.elapsed_ms


@dataclass(frozen=True)
class TurnPolicy:
    """One predeclared endpointing policy; timeout is a hard upper bound."""

    threshold: float
    action_delay_ms: int
    timeout_ms: int

    def __post_init__(self) -> None:
        if type(self.threshold) not in (int, float):
            raise ValueError("threshold must be finite and in 0..1")
        if not math.isfinite(float(self.threshold)) or not 0 <= self.threshold <= 1:
            raise ValueError("threshold must be finite and in 0..1")
        if type(self.action_delay_ms) is not int or not 0 <= self.action_delay_ms <= _MAX_DURATION_MS:
            raise ValueError("action_delay_ms must be a bounded nonnegative integer")
        if type(self.timeout_ms) is not int or not 1 <= self.timeout_ms <= _MAX_DURATION_MS:
            raise ValueError("timeout_ms must be in 1..120000")
        if self.timeout_ms < self.action_delay_ms:
            raise ValueError("timeout_ms cannot be shorter than action_delay_ms")


@dataclass(frozen=True)
class TurnPolicyResult:
    """Aggregate result for one policy; no individual turn IDs are returned."""

    score_source: ScoreSource
    threshold: float | None
    action_delay_ms: int
    timeout_ms: int
    turn_count: int
    hold_pause_count: int
    false_cutoffs: int
    false_cutoff_rate: float
    final_turn_count: int
    detected_final_turns: int
    missed_final_turns: int
    missed_final_rate: float
    mean_observed_latency_ms: float
    p50_observed_latency_ms: float
    p95_observed_latency_ms: float


@dataclass(frozen=True)
class TurnTakingSweep:
    """Deterministic policy sweep and its non-dominated operating points."""

    evaluations: tuple[TurnPolicyResult, ...]
    pareto_frontier: tuple[TurnPolicyResult, ...]


def _nearest_rank(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(probability * len(ordered)))
    return ordered[rank - 1]


def _validate_spans(spans: Sequence[SilenceSpan]) -> tuple[SilenceSpan, ...]:
    if not isinstance(spans, (tuple, list)) or not 1 <= len(spans) <= _MAX_SPANS:
        raise ValueError("spans must contain 1..20000 observations")
    rows = tuple(spans)
    seen_span_ids: set[str] = set()
    turns: dict[str, tuple[str, int]] = {}
    total_scores = 0
    hold_count = 0
    final_count = 0
    for span in rows:
        if not isinstance(span, SilenceSpan):
            raise TypeError("spans must contain SilenceSpan values")
        if span.span_id in seen_span_ids:
            raise ValueError("duplicate span_id")
        seen_span_ids.add(span.span_id)
        total_scores += len(span.scores)
        if total_scores > _MAX_TOTAL_SCORE_POINTS:
            raise ValueError("total score-point limit exceeded")
        previous = turns.get(span.turn_id)
        if previous is None:
            turns[span.turn_id] = (span.environment_id, 0)
        elif previous[0] != span.environment_id:
            raise ValueError("all spans in a turn must share an environment")
        if span.kind is PauseKind.HOLD:
            hold_count += 1
        else:
            final_count += 1
            env, count = turns[span.turn_id]
            turns[span.turn_id] = (env, count + 1)
    if hold_count == 0 or final_count == 0:
        raise ValueError("evaluation requires both hold pauses and final turns")
    if any(finals != 1 for _, finals in turns.values()):
        raise ValueError("each turn must contain exactly one END_OF_TURN span")
    return rows


def _decision_elapsed(
    span: SilenceSpan,
    policy: TurnPolicy,
    score_source: ScoreSource,
) -> int | None:
    """Return the first causal action time, or None when observation is censored."""
    exclusive_limit = span.duration_ms if span.kind is PauseKind.HOLD else span.duration_ms + 1
    if score_source is ScoreSource.MODEL:
        for point in span.scores:
            if point.elapsed_ms < policy.action_delay_ms:
                continue
            if point.elapsed_ms > policy.timeout_ms:
                break
            if point.elapsed_ms >= exclusive_limit:
                break
            if point.score >= policy.threshold:
                return point.elapsed_ms
    else:
        # Silence-only baseline: act as soon as the policy's minimum silence
        # delay is reached, without using a learned score.
        if policy.action_delay_ms < exclusive_limit and policy.action_delay_ms <= policy.timeout_ms:
            return policy.action_delay_ms

    # A timeout ends a final pause. On a HOLD span it only fires if it occurs
    # strictly before speech resumes; at the exact boundary the resumed speech wins.
    if span.kind is PauseKind.END_OF_TURN:
        if policy.timeout_ms <= span.duration_ms:
            return policy.timeout_ms
    elif policy.timeout_ms < span.duration_ms:
        return policy.timeout_ms
    return None


def evaluate_turn_policy(
    spans: Sequence[SilenceSpan],
    policy: TurnPolicy,
    *,
    score_source: ScoreSource = ScoreSource.MODEL,
) -> TurnPolicyResult:
    """Evaluate one endpointing policy on the same labeled causal pause set.

    Missed final turns are counted separately and assigned the observed horizon
    as a right-censored latency, so a system cannot look fast by failing to
    answer. False cutoffs are the fraction of HOLD spans that trigger an action
    before the human resumes.
    """
    rows = _validate_spans(spans)
    if not isinstance(policy, TurnPolicy):
        raise TypeError("policy must be TurnPolicy")
    if not isinstance(score_source, ScoreSource):
        raise TypeError("score_source must be ScoreSource")

    holds = [row for row in rows if row.kind is PauseKind.HOLD]
    finals = [row for row in rows if row.kind is PauseKind.END_OF_TURN]
    false_cutoffs = 0
    detected = 0
    observed_latencies: list[float] = []

    for span in holds:
        if _decision_elapsed(span, policy, score_source) is not None:
            false_cutoffs += 1

    for span in finals:
        decision = _decision_elapsed(span, policy, score_source)
        if decision is None:
            observed_latencies.append(float(span.duration_ms))
        else:
            detected += 1
            observed_latencies.append(float(decision))

    missed = len(finals) - detected
    return TurnPolicyResult(
        score_source=score_source,
        threshold=policy.threshold if score_source is ScoreSource.MODEL else None,
        action_delay_ms=policy.action_delay_ms,
        timeout_ms=policy.timeout_ms,
        turn_count=len({row.turn_id for row in rows}),
        hold_pause_count=len(holds),
        false_cutoffs=false_cutoffs,
        false_cutoff_rate=false_cutoffs / len(holds),
        final_turn_count=len(finals),
        detected_final_turns=detected,
        missed_final_turns=missed,
        missed_final_rate=missed / len(finals),
        mean_observed_latency_ms=sum(observed_latencies) / len(observed_latencies),
        p50_observed_latency_ms=_nearest_rank(observed_latencies, 0.50),
        p95_observed_latency_ms=_nearest_rank(observed_latencies, 0.95),
    )


def _dominates(left: TurnPolicyResult, right: TurnPolicyResult) -> bool:
    left_values = (
        left.false_cutoff_rate,
        left.p95_observed_latency_ms,
        left.missed_final_rate,
    )
    right_values = (
        right.false_cutoff_rate,
        right.p95_observed_latency_ms,
        right.missed_final_rate,
    )
    return all(a <= b for a, b in zip(left_values, right_values)) and any(
        a < b for a, b in zip(left_values, right_values)
    )


def pareto_frontier(
    results: Sequence[TurnPolicyResult],
) -> tuple[TurnPolicyResult, ...]:
    """Return policies not dominated on cutoff rate, p95 latency, and miss rate."""
    if not isinstance(results, (tuple, list)) or not results:
        raise ValueError("results must be a nonempty sequence")
    if any(not isinstance(item, TurnPolicyResult) for item in results):
        raise TypeError("results must contain TurnPolicyResult values")
    unique: dict[tuple[object, ...], TurnPolicyResult] = {}
    for item in results:
        key = (
            item.score_source,
            item.threshold,
            item.action_delay_ms,
            item.timeout_ms,
        )
        unique[key] = item
    candidates = tuple(unique.values())
    frontier = [
        item for item in candidates
        if not any(other is not item and _dominates(other, item) for other in candidates)
    ]
    frontier.sort(key=lambda item: (
        item.false_cutoff_rate,
        item.p95_observed_latency_ms,
        item.missed_final_rate,
        item.action_delay_ms,
        item.timeout_ms,
        item.score_source.value,
        -1.0 if item.threshold is None else item.threshold,
    ))
    return tuple(frontier)


def sweep_turn_policies(
    spans: Sequence[SilenceSpan],
    *,
    thresholds: Sequence[float],
    action_delays_ms: Sequence[int],
    timeouts_ms: Sequence[int],
    include_silence_baseline: bool = True,
) -> TurnTakingSweep:
    """Sweep a bounded policy grid and include a silence-only baseline.

    The same spans and labels are used for every policy. Thresholds are not
    inferred from the test set; callers should predeclare the grid and keep a
    separate held-out set for final acceptance.
    """
    rows = _validate_spans(spans)
    if type(include_silence_baseline) is not bool:
        raise ValueError("include_silence_baseline must be boolean")
    if not isinstance(thresholds, (tuple, list)) or not thresholds:
        raise ValueError("thresholds must be a nonempty sequence")
    if not isinstance(action_delays_ms, (tuple, list)) or not action_delays_ms:
        raise ValueError("action_delays_ms must be a nonempty sequence")
    if not isinstance(timeouts_ms, (tuple, list)) or not timeouts_ms:
        raise ValueError("timeouts_ms must be a nonempty sequence")
    combinations = len(thresholds) * len(action_delays_ms) * len(timeouts_ms)
    baseline_combinations = len(action_delays_ms) * len(timeouts_ms) if include_silence_baseline else 0
    if combinations + baseline_combinations > _MAX_POLICY_COMBINATIONS:
        raise ValueError("policy grid exceeds the bounded 256 combinations")

    results: list[TurnPolicyResult] = []
    for threshold in thresholds:
        for delay in action_delays_ms:
            for timeout in timeouts_ms:
                policy = TurnPolicy(threshold, delay, timeout)
                results.append(evaluate_turn_policy(rows, policy))
    if include_silence_baseline:
        for delay in action_delays_ms:
            for timeout in timeouts_ms:
                policy = TurnPolicy(0.0, delay, timeout)
                results.append(evaluate_turn_policy(
                    rows, policy, score_source=ScoreSource.SILENCE_ONLY
                ))
    ordered = tuple(sorted(results, key=lambda item: (
        item.score_source.value,
        -1.0 if item.threshold is None else item.threshold,
        item.action_delay_ms,
        item.timeout_ms,
    )))
    return TurnTakingSweep(ordered, pareto_frontier(ordered))


__all__ = [
    "PauseKind",
    "ScoreSource",
    "EndOfTurnScore",
    "SilenceSpan",
    "TurnPolicy",
    "TurnPolicyResult",
    "TurnTakingSweep",
    "evaluate_turn_policy",
    "pareto_frontier",
    "sweep_turn_policies",
]
