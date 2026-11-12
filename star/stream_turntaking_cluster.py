"""Session-clustered uncertainty for STAR conversational turn evaluation.

Pauses inside one conversation are correlated. This module resamples complete
session groups, reports session-incidence guardrails, and never returns source
IDs or conversation content.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
import random
import re
from statistics import NormalDist, fmean

from .stream_turntaking_eval import (
    PauseKind,
    ScoreSource,
    SilenceSpan,
    TurnPolicy,
    _decision_elapsed,
    evaluate_turn_policy,
)

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_MAX_SPANS = 20_000
_MAX_GROUPS = 20_000
_MIN_BOOTSTRAP_REPLICATES = 200
_MAX_BOOTSTRAP_REPLICATES = 10_000
_MAX_RANDOM_SEED = 4_294_967_295


@dataclass(frozen=True)
class ClusteredTurnMetrics:
    """Aggregate-only cluster metrics; no session or turn identifiers escape."""

    session_count: int
    sessions_with_hold_pauses: int
    hold_pause_count: int
    false_cutoff_count: int
    final_turn_count: int
    missed_final_turn_count: int
    pooled_false_cutoff_rate: float
    pooled_missed_final_rate: float
    false_cutoff_session_count: int
    false_cutoff_session_incidence: float
    false_cutoff_session_incidence_upper_bound: float
    missed_final_session_count: int
    missed_final_session_incidence: float
    missed_final_session_incidence_upper_bound: float
    bootstrap_false_cutoff_rate_ci_low: float
    bootstrap_false_cutoff_rate_ci_high: float
    bootstrap_false_cutoff_rate_upper_bound: float
    bootstrap_missed_final_rate_ci_low: float
    bootstrap_missed_final_rate_ci_high: float
    bootstrap_missed_final_rate_upper_bound: float
    mean_session_p95_latency_ms: float
    mean_session_p95_latency_ci_low_ms: float
    mean_session_p95_latency_ci_high_ms: float
    mean_session_p95_latency_upper_bound_ms: float
    bootstrap_replicates: int
    confidence_level: float


@dataclass(frozen=True)
class _SessionSummary:
    hold_pause_count: int
    false_cutoff_count: int
    final_turn_count: int
    missed_final_turn_count: int
    p95_latency_ms: float


def _nearest_rank(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("percentile values must not be empty")
    ordered = sorted(values)
    rank = max(1, math.ceil(probability * len(ordered)))
    return float(ordered[rank - 1])


def _wilson_upper(successes: int, trials: int, confidence_level: float) -> float:
    """One-sided Wilson upper bound over independent session-level outcomes."""
    if (
        type(successes) is not int
        or type(trials) is not int
        or trials < 1
        or not 0 <= successes <= trials
    ):
        raise ValueError("Wilson counts must satisfy 0 <= successes <= trials")
    z = NormalDist().inv_cdf(confidence_level)
    rate = successes / trials
    z_squared = z * z
    denominator = 1.0 + z_squared / trials
    center = rate + z_squared / (2.0 * trials)
    spread = z * math.sqrt(
        rate * (1.0 - rate) / trials + z_squared / (4.0 * trials * trials)
    )
    return min(1.0, (center + spread) / denominator)


def minimum_groups_for_zero_event_incidence(
    maximum_rate: float,
    confidence_level: float = 0.95,
) -> int | None:
    """Return groups needed for a zero-event Wilson upper bound to meet a rate.

    None means the requested rate is exactly zero or cannot be demonstrated
    within the module's bounded maximum of 20,000 independent groups.
    """
    if isinstance(maximum_rate, bool) or not isinstance(maximum_rate, (int, float)):
        raise ValueError("maximum_rate must be a finite fraction in 0..1")
    rate = float(maximum_rate)
    if not math.isfinite(rate) or not 0.0 <= rate <= 1.0:
        raise ValueError("maximum_rate must be a finite fraction in 0..1")
    if (
        isinstance(confidence_level, bool)
        or not isinstance(confidence_level, (int, float))
    ):
        raise ValueError("confidence_level must be between 0.8 and 0.99")
    confidence = float(confidence_level)
    if not math.isfinite(confidence) or not 0.8 <= confidence <= 0.99:
        raise ValueError("confidence_level must be between 0.8 and 0.99")
    if rate == 0.0:
        return None
    for group_count in range(1, _MAX_GROUPS + 1):
        if _wilson_upper(0, group_count, confidence) <= rate:
            return group_count
    return None


def _bootstrap_interval(
    values: Sequence[float],
    confidence_level: float,
) -> tuple[float, float, float]:
    alpha = 1.0 - confidence_level
    low = _nearest_rank(values, alpha / 2.0)
    high = _nearest_rank(values, 1.0 - alpha / 2.0)
    upper = _nearest_rank(values, confidence_level)
    return low, high, upper


def evaluate_clustered_turn_policy(
    spans: Sequence[SilenceSpan],
    policy: TurnPolicy,
    *,
    group_ids_by_turn: Mapping[str, str],
    bootstrap_replicates: int = 1_000,
    confidence_level: float = 0.95,
    random_seed: int = 0,
) -> ClusteredTurnMetrics:
    """Evaluate a fixed policy with whole-session bootstrap resampling.

    False-cutoff bootstrap samples resample only sessions containing at least
    one observed HOLD pause, preserving each sampled session's complete pause
    cluster. Missed-turn samples resample all sessions. Latency uncertainty is
    reported as the mean of session-level p95 values, not as a population p95.

    Session-incidence Wilson bounds provide a separate guard against a
    zero-error bootstrap distribution falsely implying zero population risk.
    """
    if not isinstance(spans, (tuple, list)) or not 1 <= len(spans) <= _MAX_SPANS:
        raise ValueError("spans must contain 1..20000 observations")
    rows = tuple(spans)
    if any(not isinstance(span, SilenceSpan) for span in rows):
        raise TypeError("spans must contain SilenceSpan values")
    if not isinstance(policy, TurnPolicy):
        raise TypeError("policy must be TurnPolicy")
    if not isinstance(group_ids_by_turn, Mapping):
        raise TypeError("group_ids_by_turn must be a mapping")
    if (
        type(bootstrap_replicates) is not int
        or not _MIN_BOOTSTRAP_REPLICATES <= bootstrap_replicates <= _MAX_BOOTSTRAP_REPLICATES
    ):
        raise ValueError("bootstrap_replicates must be in 200..10000")
    if (
        isinstance(confidence_level, bool)
        or not isinstance(confidence_level, (int, float))
    ):
        raise ValueError("confidence_level must be between 0.8 and 0.99")
    confidence = float(confidence_level)
    if not math.isfinite(confidence) or not 0.8 <= confidence <= 0.99:
        raise ValueError("confidence_level must be between 0.8 and 0.99")
    if type(random_seed) is not int or not 0 <= random_seed <= _MAX_RANDOM_SEED:
        raise ValueError("random_seed must be in 0..4294967295")

    # Reuse the canonical evaluator's complete dataset validation.
    pooled = evaluate_turn_policy(rows, policy)
    turn_ids = {span.turn_id for span in rows}
    if set(group_ids_by_turn) != turn_ids:
        raise ValueError("group_ids_by_turn must contain exactly the supplied turn IDs")

    groups_by_id: dict[str, list[SilenceSpan]] = {}
    for turn_id in sorted(turn_ids):
        group_id = group_ids_by_turn[turn_id]
        if type(group_id) is not str or _ID.fullmatch(group_id) is None:
            raise ValueError("group IDs must be bounded opaque identifiers")
        groups_by_id.setdefault(group_id, [])

    for span in rows:
        group_id = group_ids_by_turn[span.turn_id]
        groups_by_id[group_id].append(span)

    if not 1 <= len(groups_by_id) <= _MAX_GROUPS:
        raise ValueError("holdout must contain 1..20000 session groups")

    summaries: list[_SessionSummary] = []
    for group_id in sorted(groups_by_id):
        group_spans = groups_by_id[group_id]
        holds = [span for span in group_spans if span.kind is PauseKind.HOLD]
        finals = [span for span in group_spans if span.kind is PauseKind.END_OF_TURN]
        false_cutoffs = sum(
            _decision_elapsed(span, policy, ScoreSource.MODEL) is not None
            for span in holds
        )
        latencies: list[float] = []
        missed = 0
        for span in finals:
            decision = _decision_elapsed(span, policy, ScoreSource.MODEL)
            if decision is None:
                missed += 1
                latencies.append(float(span.duration_ms))
            else:
                latencies.append(float(decision))
        if not latencies:
            raise ValueError("every session group must contain a final turn")
        summaries.append(
            _SessionSummary(
                hold_pause_count=len(holds),
                false_cutoff_count=false_cutoffs,
                final_turn_count=len(finals),
                missed_final_turn_count=missed,
                p95_latency_ms=_nearest_rank(latencies, 0.95),
            )
        )

    hold_groups = [summary for summary in summaries if summary.hold_pause_count > 0]
    if not hold_groups:
        raise ValueError("at least one session group must contain a HOLD pause")

    false_session_count = sum(
        summary.false_cutoff_count > 0 for summary in hold_groups
    )
    missed_session_count = sum(
        summary.missed_final_turn_count > 0 for summary in summaries
    )
    hold_count = sum(summary.hold_pause_count for summary in summaries)
    false_count = sum(summary.false_cutoff_count for summary in summaries)
    final_count = sum(summary.final_turn_count for summary in summaries)
    missed_count = sum(summary.missed_final_turn_count for summary in summaries)

    rng = random.Random(random_seed)
    false_bootstrap: list[float] = []
    missed_bootstrap: list[float] = []
    latency_bootstrap: list[float] = []
    for _ in range(bootstrap_replicates):
        sampled_hold_groups = [
            hold_groups[rng.randrange(len(hold_groups))]
            for _ in range(len(hold_groups))
        ]
        sampled_holds = sum(item.hold_pause_count for item in sampled_hold_groups)
        sampled_false = sum(item.false_cutoff_count for item in sampled_hold_groups)
        false_bootstrap.append(sampled_false / sampled_holds)

        sampled_sessions = [
            summaries[rng.randrange(len(summaries))]
            for _ in range(len(summaries))
        ]
        sampled_finals = sum(item.final_turn_count for item in sampled_sessions)
        sampled_missed = sum(item.missed_final_turn_count for item in sampled_sessions)
        missed_bootstrap.append(sampled_missed / sampled_finals)
        latency_bootstrap.append(
            fmean(item.p95_latency_ms for item in sampled_sessions)
        )

    false_low, false_high, false_upper = _bootstrap_interval(
        false_bootstrap, confidence
    )
    missed_low, missed_high, missed_upper = _bootstrap_interval(
        missed_bootstrap, confidence
    )
    latency_low, latency_high, latency_upper = _bootstrap_interval(
        latency_bootstrap, confidence
    )
    hold_group_count = len(hold_groups)
    session_count = len(summaries)

    # Sanity-check the aggregate counts against the canonical pooled evaluator.
    if (
        hold_count != pooled.hold_pause_count
        or false_count != pooled.false_cutoffs
        or final_count != pooled.final_turn_count
        or missed_count != pooled.missed_final_turns
    ):
        raise RuntimeError("cluster aggregation disagrees with canonical evaluator")

    return ClusteredTurnMetrics(
        session_count=session_count,
        sessions_with_hold_pauses=hold_group_count,
        hold_pause_count=hold_count,
        false_cutoff_count=false_count,
        final_turn_count=final_count,
        missed_final_turn_count=missed_count,
        pooled_false_cutoff_rate=false_count / hold_count,
        pooled_missed_final_rate=missed_count / final_count,
        false_cutoff_session_count=false_session_count,
        false_cutoff_session_incidence=false_session_count / hold_group_count,
        false_cutoff_session_incidence_upper_bound=_wilson_upper(
            false_session_count, hold_group_count, confidence
        ),
        missed_final_session_count=missed_session_count,
        missed_final_session_incidence=missed_session_count / session_count,
        missed_final_session_incidence_upper_bound=_wilson_upper(
            missed_session_count, session_count, confidence
        ),
        bootstrap_false_cutoff_rate_ci_low=false_low,
        bootstrap_false_cutoff_rate_ci_high=false_high,
        bootstrap_false_cutoff_rate_upper_bound=false_upper,
        bootstrap_missed_final_rate_ci_low=missed_low,
        bootstrap_missed_final_rate_ci_high=missed_high,
        bootstrap_missed_final_rate_upper_bound=missed_upper,
        mean_session_p95_latency_ms=fmean(
            item.p95_latency_ms for item in summaries
        ),
        mean_session_p95_latency_ci_low_ms=latency_low,
        mean_session_p95_latency_ci_high_ms=latency_high,
        mean_session_p95_latency_upper_bound_ms=latency_upper,
        bootstrap_replicates=bootstrap_replicates,
        confidence_level=confidence,
    )


__all__ = [
    "ClusteredTurnMetrics",
    "evaluate_clustered_turn_policy",
    "minimum_groups_for_zero_event_incidence",
]
