"""Select turn-taking policies on calibration data and validate once on holdout.

This module prevents a fast-but-fragile voice policy from being selected on
and reported against the same pauses. It is an offline evaluator only: it
does not access audio, call a model, control playback, or promote a policy.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import math
import re
from statistics import NormalDist

from .stream_turntaking_cluster import (
    ClusteredTurnMetrics,
    evaluate_clustered_turn_policy,
    minimum_groups_for_zero_event_incidence,
)
from .stream_turntaking_eval import (
    ScoreSource,
    SilenceSpan,
    TurnPolicy,
    TurnPolicyResult,
    evaluate_turn_policy,
    sweep_turn_policies,
)
from .stream_holdout_ledger import HoldoutLedger

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_MAX_SPANS = 20_000
_MAX_DURATION_MS = 120_000


class ValidationStatus(str, Enum):
    """Outcome of a frozen-policy, held-out evaluation."""

    INSUFFICIENT_CALIBRATION = "INSUFFICIENT_CALIBRATION"
    NO_CALIBRATION_CANDIDATE = "NO_CALIBRATION_CANDIDATE"
    INCONCLUSIVE_HOLDOUT = "INCONCLUSIVE_HOLDOUT"
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True)
class TurnPolicyConstraints:
    """Predeclared acceptance limits for pause, session, and latency rates."""

    max_false_cutoff_rate: float = 0.05
    max_missed_final_rate: float = 0.05
    max_p95_latency_ms: int = 900
    max_latency_violation_session_rate: float = 0.05
    min_hold_pauses: int = 100
    min_final_turns: int = 100
    min_calibration_groups: int = 20
    min_holdout_groups: int = 20
    confidence_level: float = 0.95

    def __post_init__(self) -> None:
        for name in (
            "max_false_cutoff_rate",
            "max_missed_final_rate",
            "max_latency_violation_session_rate",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite fraction in 0..1")
            numeric = float(value)
            if not math.isfinite(numeric) or not 0 <= numeric <= 1:
                raise ValueError(f"{name} must be a finite fraction in 0..1")
        if type(self.max_p95_latency_ms) is not int or not 1 <= self.max_p95_latency_ms <= _MAX_DURATION_MS:
            raise ValueError("max_p95_latency_ms must be in 1..120000")
        for name in (
            "min_hold_pauses", "min_final_turns",
            "min_calibration_groups", "min_holdout_groups",
        ):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= _MAX_SPANS:
                raise ValueError(f"{name} must be in 1..20000")
        if isinstance(self.confidence_level, bool) or not isinstance(self.confidence_level, (int, float)):
            raise ValueError("confidence_level must be between 0.8 and 0.99")
        confidence = float(self.confidence_level)
        if not math.isfinite(confidence) or not 0.8 <= confidence <= 0.99:
            raise ValueError("confidence_level must be between 0.8 and 0.99")


@dataclass(frozen=True)
class TurnPolicyValidation:
    """Aggregate result only; source turn, group and span IDs are never returned."""

    status: ValidationStatus
    selected_policy: TurnPolicy | None
    calibration_metrics: TurnPolicyResult | None
    holdout_metrics: TurnPolicyResult | None
    holdout_silence_baseline: TurnPolicyResult | None
    calibration_policy_count: int
    calibration_eligible_count: int
    calibration_turn_count: int
    holdout_turn_count: int
    calibration_group_count: int
    holdout_group_count: int
    holdout_false_cutoff_upper_bound: float | None
    holdout_missed_final_upper_bound: float | None
    holdout_ledger_claimed: bool = False
    cluster_metrics: ClusteredTurnMetrics | None = None
    cluster_aware: bool = True


def _probe_partition(spans: Sequence[SilenceSpan], label: str) -> TurnPolicyResult:
    if not isinstance(spans, Sequence) or isinstance(spans, (str, bytes)):
        raise TypeError(f"{label} spans must be a sequence")
    if not 1 <= len(spans) <= _MAX_SPANS:
        raise ValueError(f"{label} spans must contain 1..20000 observations")
    rows = tuple(spans)
    if any(not isinstance(span, SilenceSpan) for span in rows):
        raise TypeError(f"{label} spans must contain SilenceSpan values")
    # A deliberately conservative probe validates the dataset contract. Its
    # metrics are discarded; it is never used to choose or accept a policy.
    return evaluate_turn_policy(rows, TurnPolicy(1.0, _MAX_DURATION_MS, _MAX_DURATION_MS))


def _validate_split(
    calibration_spans: Sequence[SilenceSpan],
    holdout_spans: Sequence[SilenceSpan],
    group_ids_by_turn: Mapping[str, str],
) -> tuple[TurnPolicyResult, TurnPolicyResult, int, int]:
    calibration_probe = _probe_partition(calibration_spans, "calibration")
    holdout_probe = _probe_partition(holdout_spans, "holdout")

    calibration_rows = tuple(calibration_spans)
    holdout_rows = tuple(holdout_spans)
    calibration_turns = {span.turn_id for span in calibration_rows}
    holdout_turns = {span.turn_id for span in holdout_rows}
    if calibration_turns & holdout_turns:
        raise ValueError("calibration and holdout turn IDs must be disjoint")

    calibration_span_ids = {span.span_id for span in calibration_rows}
    holdout_span_ids = {span.span_id for span in holdout_rows}
    if calibration_span_ids & holdout_span_ids:
        raise ValueError("calibration and holdout span IDs must be disjoint")

    if not isinstance(group_ids_by_turn, Mapping):
        raise TypeError("group_ids_by_turn must map every turn to an opaque group ID")
    all_turns = calibration_turns | holdout_turns
    if set(group_ids_by_turn) != all_turns:
        raise ValueError("group_ids_by_turn must contain exactly the supplied turn IDs")

    groups: dict[str, str] = {}
    for turn_id, group_id in group_ids_by_turn.items():
        if type(turn_id) is not str or _ID.fullmatch(turn_id) is None:
            raise ValueError("turn mapping keys must be bounded opaque IDs")
        if type(group_id) is not str or _ID.fullmatch(group_id) is None:
            raise ValueError("group IDs must be bounded opaque IDs")
        groups[turn_id] = group_id

    calibration_groups = {groups[turn_id] for turn_id in calibration_turns}
    holdout_groups = {groups[turn_id] for turn_id in holdout_turns}
    if calibration_groups & holdout_groups:
        raise ValueError("calibration and holdout groups must be disjoint")

    return calibration_probe, holdout_probe, len(calibration_groups), len(holdout_groups)


def _wilson_upper(successes: int, trials: int, confidence_level: float) -> float:
    """One-sided Wilson upper confidence bound for a binomial rate."""
    if type(successes) is not int or type(trials) is not int or not 0 <= successes <= trials or trials < 1:
        raise ValueError("Wilson counts must satisfy 0 <= successes <= trials and trials >= 1")
    z = NormalDist().inv_cdf(confidence_level)
    rate = successes / trials
    z2 = z * z
    denominator = 1.0 + z2 / trials
    center = rate + z2 / (2.0 * trials)
    spread = z * math.sqrt(rate * (1.0 - rate) / trials + z2 / (4.0 * trials * trials))
    return min(1.0, (center + spread) / denominator)


def _eligible(
    result: TurnPolicyResult,
    constraints: TurnPolicyConstraints,
) -> bool:
    false_upper = _wilson_upper(
        result.false_cutoffs, result.hold_pause_count, constraints.confidence_level
    )
    missed_upper = _wilson_upper(
        result.missed_final_turns, result.final_turn_count, constraints.confidence_level
    )
    return (
        false_upper <= constraints.max_false_cutoff_rate
        and missed_upper <= constraints.max_missed_final_rate
        and result.p95_observed_latency_ms <= constraints.max_p95_latency_ms
    )


def select_and_validate_turn_policy(
    calibration_spans: Sequence[SilenceSpan],
    holdout_spans: Sequence[SilenceSpan],
    *,
    group_ids_by_turn: Mapping[str, str],
    thresholds: Sequence[float],
    action_delays_ms: Sequence[int],
    timeouts_ms: Sequence[int],
    constraints: TurnPolicyConstraints,
    holdout_ledger: HoldoutLedger | None = None,
    cluster_aware: bool = True,
    cluster_bootstrap_replicates: int = 1_000,
    cluster_random_seed: int = 0,
) -> TurnPolicyValidation:
    """Choose a policy using calibration only, then evaluate it on held-out turns.

    Group IDs should be stable, opaque HMAC digests for conversation/session
    groups. All turns from one group must stay in one partition. The holdout is
    evaluated only after calibration selects a policy; callers must keep the
    holdout sealed and must not repeatedly tune against it.

    When a HoldoutLedger is supplied, the dataset and all holdout session groups
    are atomically consumed before scoring. A crash after that claim still burns
    the holdout. Without a ledger, one-use enforcement remains the caller's job.
    """
    if not isinstance(constraints, TurnPolicyConstraints):
        raise TypeError("constraints must be TurnPolicyConstraints")
    if holdout_ledger is not None and not isinstance(holdout_ledger, HoldoutLedger):
        raise TypeError("holdout_ledger must be HoldoutLedger or None")
    if type(cluster_aware) is not bool:
        raise ValueError("cluster_aware must be boolean")
    if cluster_aware:
        if (
            type(cluster_bootstrap_replicates) is not int
            or not 200 <= cluster_bootstrap_replicates <= 10_000
        ):
            raise ValueError("cluster_bootstrap_replicates must be in 200..10000")
        if (
            type(cluster_random_seed) is not int
            or not 0 <= cluster_random_seed <= 4_294_967_295
        ):
            raise ValueError("cluster_random_seed must be in 0..4294967295")
    (
        calibration_probe,
        holdout_probe,
        calibration_group_count,
        holdout_group_count,
    ) = _validate_split(calibration_spans, holdout_spans, group_ids_by_turn)

    if (
        calibration_probe.hold_pause_count < constraints.min_hold_pauses
        or calibration_probe.final_turn_count < constraints.min_final_turns
        or calibration_group_count < constraints.min_calibration_groups
    ):
        return TurnPolicyValidation(
            status=ValidationStatus.INSUFFICIENT_CALIBRATION,
            selected_policy=None,
            calibration_metrics=None,
            holdout_metrics=None,
            holdout_silence_baseline=None,
            calibration_policy_count=0,
            calibration_eligible_count=0,
            calibration_turn_count=calibration_probe.turn_count,
            holdout_turn_count=holdout_probe.turn_count,
            calibration_group_count=calibration_group_count,
            holdout_group_count=holdout_group_count,
            holdout_false_cutoff_upper_bound=None,
            holdout_missed_final_upper_bound=None,
            cluster_aware=cluster_aware,
        )

    sweep = sweep_turn_policies(
        tuple(calibration_spans),
        thresholds=thresholds,
        action_delays_ms=action_delays_ms,
        timeouts_ms=timeouts_ms,
        include_silence_baseline=False,
    )
    eligible = [
        result for result in sweep.evaluations
        if result.score_source is ScoreSource.MODEL and _eligible(result, constraints)
    ]
    if not eligible:
        return TurnPolicyValidation(
            status=ValidationStatus.NO_CALIBRATION_CANDIDATE,
            selected_policy=None,
            calibration_metrics=None,
            holdout_metrics=None,
            holdout_silence_baseline=None,
            calibration_policy_count=len(sweep.evaluations),
            calibration_eligible_count=0,
            calibration_turn_count=calibration_probe.turn_count,
            holdout_turn_count=holdout_probe.turn_count,
            calibration_group_count=calibration_group_count,
            holdout_group_count=holdout_group_count,
            holdout_false_cutoff_upper_bound=None,
            holdout_missed_final_upper_bound=None,
            cluster_aware=cluster_aware,
        )

    # Deterministic tie-breaks are predeclared and use calibration metrics only.
    selected_metrics = min(
        eligible,
        key=lambda result: (
            result.p95_observed_latency_ms,
            _wilson_upper(result.false_cutoffs, result.hold_pause_count, constraints.confidence_level),
            _wilson_upper(result.missed_final_turns, result.final_turn_count, constraints.confidence_level),
            result.mean_observed_latency_ms,
            result.action_delay_ms,
            result.timeout_ms,
            float(result.threshold if result.threshold is not None else 1.0),
        ),
    )
    if selected_metrics.threshold is None:
        raise RuntimeError("model policy unexpectedly has no threshold")
    selected_policy = TurnPolicy(
        selected_metrics.threshold,
        selected_metrics.action_delay_ms,
        selected_metrics.timeout_ms,
    )

    # Claim before scoring: even a crash after this point must not make the
    # same holdout available for repeated adaptive tuning.
    if holdout_ledger is not None:
        holdout_ledger.claim(holdout_spans, group_ids_by_turn)

    # This is the only holdout evaluation performed by this call. The same
    # frozen action delay/timeout are used for a silence-only reference.
    holdout_metrics = evaluate_turn_policy(tuple(holdout_spans), selected_policy)
    silence_baseline = evaluate_turn_policy(
        tuple(holdout_spans),
        TurnPolicy(0.0, selected_policy.action_delay_ms, selected_policy.timeout_ms),
        score_source=ScoreSource.SILENCE_ONLY,
    )
    false_upper = _wilson_upper(
        holdout_metrics.false_cutoffs,
        holdout_metrics.hold_pause_count,
        constraints.confidence_level,
    )
    missed_upper = _wilson_upper(
        holdout_metrics.missed_final_turns,
        holdout_metrics.final_turn_count,
        constraints.confidence_level,
    )

    cluster_metrics: ClusteredTurnMetrics | None = None
    if cluster_aware:
        cluster_metrics = evaluate_clustered_turn_policy(
            holdout_spans,
            selected_policy,
            group_ids_by_turn=group_ids_by_turn,
            bootstrap_replicates=cluster_bootstrap_replicates,
            confidence_level=constraints.confidence_level,
            random_seed=cluster_random_seed,
            latency_limit_ms=constraints.max_p95_latency_ms,
        )

    enough_basic_holdout = (
        holdout_metrics.hold_pause_count >= constraints.min_hold_pauses
        and holdout_metrics.final_turn_count >= constraints.min_final_turns
        and holdout_group_count >= constraints.min_holdout_groups
    )
    cluster_evidence_sufficient = True
    cluster_point_violation = False
    if cluster_metrics is not None:
        false_required_groups = minimum_groups_for_zero_event_incidence(
            constraints.max_false_cutoff_rate,
            constraints.confidence_level,
        )
        missed_required_groups = minimum_groups_for_zero_event_incidence(
            constraints.max_missed_final_rate,
            constraints.confidence_level,
        )
        latency_required_groups = minimum_groups_for_zero_event_incidence(
            constraints.max_latency_violation_session_rate,
            constraints.confidence_level,
        )
        cluster_evidence_sufficient = (
            false_required_groups is not None
            and missed_required_groups is not None
            and latency_required_groups is not None
            and cluster_metrics.false_cutoff_rate_effective_session_count
            >= false_required_groups
            and cluster_metrics.missed_final_rate_effective_session_count
            >= missed_required_groups
            and cluster_metrics.sessions_with_hold_pauses
            >= false_required_groups
            and cluster_metrics.session_count
            >= max(missed_required_groups, latency_required_groups)
            and holdout_group_count >= constraints.min_holdout_groups
        )
        cluster_point_violation = (
            cluster_metrics.pooled_false_cutoff_rate > constraints.max_false_cutoff_rate
            or cluster_metrics.pooled_missed_final_rate > constraints.max_missed_final_rate
            or cluster_metrics.false_cutoff_session_incidence > constraints.max_false_cutoff_rate
            or cluster_metrics.missed_final_session_incidence > constraints.max_missed_final_rate
            or cluster_metrics.latency_violation_session_incidence
            > constraints.max_latency_violation_session_rate
        )

    if (
        not enough_basic_holdout
        or (
            cluster_metrics is not None
            and not cluster_evidence_sufficient
            and not cluster_point_violation
        )
    ):
        status = ValidationStatus.INCONCLUSIVE_HOLDOUT
    elif cluster_metrics is not None:
        cluster_pass = (
            cluster_metrics.false_cutoff_rate_hoeffding_upper_bound
            <= constraints.max_false_cutoff_rate
            and cluster_metrics.missed_final_rate_hoeffding_upper_bound
            <= constraints.max_missed_final_rate
            and cluster_metrics.false_cutoff_session_incidence_hoeffding_upper_bound
            <= constraints.max_false_cutoff_rate
            and cluster_metrics.missed_final_session_incidence_hoeffding_upper_bound
            <= constraints.max_missed_final_rate
            and cluster_metrics.latency_violation_session_incidence_hoeffding_upper_bound
            <= constraints.max_latency_violation_session_rate
        )
        status = (
            ValidationStatus.PASS
            if (
                cluster_evidence_sufficient
                and cluster_pass
                and holdout_metrics.p95_observed_latency_ms
                <= constraints.max_p95_latency_ms
            )
            else ValidationStatus.FAIL
        )
    elif (
        false_upper <= constraints.max_false_cutoff_rate
        and missed_upper <= constraints.max_missed_final_rate
        and holdout_metrics.p95_observed_latency_ms <= constraints.max_p95_latency_ms
    ):
        status = ValidationStatus.PASS
    else:
        status = ValidationStatus.FAIL

    return TurnPolicyValidation(
        status=status,
        selected_policy=selected_policy,
        calibration_metrics=selected_metrics,
        holdout_metrics=holdout_metrics,
        holdout_silence_baseline=silence_baseline,
        calibration_policy_count=len(sweep.evaluations),
        calibration_eligible_count=len(eligible),
        calibration_turn_count=calibration_probe.turn_count,
        holdout_turn_count=holdout_probe.turn_count,
        calibration_group_count=calibration_group_count,
        holdout_group_count=holdout_group_count,
        holdout_false_cutoff_upper_bound=false_upper,
        holdout_missed_final_upper_bound=missed_upper,
        holdout_ledger_claimed=holdout_ledger is not None,
        cluster_metrics=cluster_metrics,
        cluster_aware=cluster_aware,
    )


__all__ = [
    "ValidationStatus",
    "TurnPolicyConstraints",
    "TurnPolicyValidation",
    "ClusteredTurnMetrics",
    "evaluate_clustered_turn_policy",
    "minimum_groups_for_zero_event_incidence",
    "select_and_validate_turn_policy",
]
