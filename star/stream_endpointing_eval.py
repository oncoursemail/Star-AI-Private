"""Offline, privacy-minimal end-of-turn benchmark for STAR's VTuber voice.

The trusted host supplies matched, independently reviewed pause decisions.
A mid-turn pause is NOT a true end-of-turn; early response can interrupt humans.
This module holds only opaque IDs, relative timings and classifications, never
audio, transcripts or identities. It neither loads models nor controls streams.

Modeled after LiveKit eot-bench's latency / false-cutoff tradeoff; external host
attestation and pre-registration are required for meaningful measurements.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Iterable, cast

_CASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_VARIANTS = frozenset({"baseline", "candidate"})
_PAUSES = frozenset({"mid_turn", "final_turn"})


def _ms(value: object, field: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{field} requires finite numeric milliseconds")
    try:
        number = float(cast(int | float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{field} requires finite numeric milliseconds") from exc
    if not math.isfinite(number) or not 0 <= number <= 10_000:
        raise ValueError(f"{field} must be within 0..10000ms")
    return number


@dataclass(frozen=True)
class EndpointPause:
    """Reviewer-labeled pause; timing relative to pause onset only.

    For mid_turn, decision_after_pause_ms must be None if the detector did
    not emit an endpoint *before speaker resumption*. For final_turn, None
    means it failed to detect a true end. Never infer this from text alone.
    """

    case_id: str
    variant: str
    pause_type: str
    decision_after_pause_ms: float | None
    mid_turn_pause_ms: float | None = None
    independently_reviewed: bool = False
    # All pauses from the same real conversation turn share this opaque ID.
    # Unique case IDs do NOT prove trials are independent.
    source_turn_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.case_id) is not str or _CASE.fullmatch(self.case_id) is None:
            raise ValueError("bounded opaque case identifier required")
        if type(self.variant) is not str or self.variant not in _VARIANTS:
            raise ValueError("variant must be baseline or candidate")
        if type(self.pause_type) is not str or self.pause_type not in _PAUSES:
            raise ValueError("pause_type must be mid_turn or final_turn")
        if type(self.independently_reviewed) is not bool:
            raise ValueError("independently_reviewed must be boolean")
        if self.source_turn_id is not None and (
            type(self.source_turn_id) is not str
            or _CASE.fullmatch(self.source_turn_id) is None
        ):
            raise ValueError("source_turn_id must be a bounded opaque identifier")
        decision = (None if self.decision_after_pause_ms is None else
                    _ms(self.decision_after_pause_ms, "decision_after_pause_ms"))
        if self.pause_type == "final_turn":
            if self.mid_turn_pause_ms is not None:
                raise ValueError("final_turn cannot contain a mid-turn length")
        else:
            if self.mid_turn_pause_ms is None:
                raise ValueError("mid_turn needs a reviewed pause length")
            duration = _ms(self.mid_turn_pause_ms, "mid_turn_pause_ms")
            if not 100 <= duration <= 5000:
                raise ValueError("mid_turn pause must be 100..5000ms")
            if decision is not None and decision > duration:
                raise ValueError("mid-turn endpoint must precede speaker resumption")


@dataclass(frozen=True)
class EndpointReport:
    status: str
    reason: str
    complete_pairs: int
    mid_turn_pairs: int
    final_turn_pairs: int
    baseline_false_cutoffs: int
    candidate_false_cutoffs: int
    new_false_cutoffs: int
    candidate_missed_true_ends: int
    baseline_final_p95_ms: float | None
    candidate_final_p95_ms: float | None
    candidate_false_cutoff_rate: float | None
    final_pair_latency_regressions: int
    authorized_to_stream: bool = False
    note: str = ("Offline evidence only; not authority to select a model, "
                 "claim human-level speech or initiate a broadcast")
    # Appended fields preserve prior positional EndpointReport arguments.
    # One-sided 95% exact bound assumes independent, preregistered source turns.
    candidate_false_cutoff_upper_95: float | None = None
    independent_mid_turns: int = 0
    candidate_turns_with_false_cutoff: int = 0


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[math.ceil(0.95 * len(ordered)) - 1], 3)


def _false_cutoff_upper_95(events: int, trials: int) -> float | None:
    """One-sided exact Clopper-Pearson upper limit for independent source turns.

    A reported 0/20 false-cutoff rate does NOT establish a <=5% true risk.
    The upper limit solves BinomCDF(events; trials, upper) == 0.05.
    This is a screening bound for preregistered holdout data, not evidence
    of independence, actual speech quality, or permission to broadcast.
    """
    if trials <= 0:
        return None
    if events == trials:
        return 1.0
    if events == 0:
        # Stable near zero: 1 - 0.05 ** (1/trials).
        return -math.expm1(math.log(0.05) / trials)

    log_choose = [
        math.lgamma(trials + 1) - math.lgamma(i + 1)
        - math.lgamma(trials - i + 1)
        for i in range(events + 1)
    ]

    def cdf(probability: float) -> float:
        if probability <= 0:
            return 1.0
        if probability >= 1:
            return 0.0
        log_p = math.log(probability)
        log_q = math.log1p(-probability)
        terms = [
            combination + i * log_p + (trials - i) * log_q
            for i, combination in enumerate(log_choose)
        ]
        peak = max(terms)
        return math.exp(peak) * math.fsum(math.exp(t - peak) for t in terms)

    low, high = 0.0, 1.0
    for _ in range(60):
        mid = (low + high) / 2
        if cdf(mid) > 0.05:
            low = mid
        else:
            high = mid
    return high


def assess_endpointing(
    pauses: Iterable[EndpointPause], *, minimum_per_type: int = 20,
    max_false_cutoff_rate: float = 0.05,
    max_final_p95_ms: float = 900.0,
    max_p95_regression_ms: float = 100.0,
    max_pair_regression_ms: float = 250.0,
) -> EndpointReport:
    """Screen paired, hidden conversation pauses for MANUAL rehearsal only.

    A detector must be BOTH fast after true turn ends and cautious about
    mid-turn hesitation. Caller must preregister the cases and thresholds
    and independently verify actual stream audio/capture behavior.
    Each independently sampled real conversation turn needs an opaque
    source_turn_id shared across all its pauses and both detector variants.
    The returned statistical bound is per-turn (ANY premature cutoff in
    that turn), not per-pause, and is not valid for duplicated/replayed
    or adaptively selected holdout turns.
    """
    if type(minimum_per_type) is not int or not 10 <= minimum_per_type <= 200:
        raise ValueError("minimum_per_type must be 10..200")
    if type(max_false_cutoff_rate) not in (float, int):
        raise ValueError("false cutoff rate must be 0..0.25")
    try:
        cutoff_budget = float(max_false_cutoff_rate)
    except (OverflowError, ValueError) as exc:
        raise ValueError("false cutoff rate must be 0..0.25") from exc
    if not math.isfinite(cutoff_budget) or not 0 <= cutoff_budget <= 0.25:
        raise ValueError("false cutoff rate must be 0..0.25")
    for label, value in (
        ("max_final_p95_ms", max_final_p95_ms),
        ("max_p95_regression_ms", max_p95_regression_ms),
        ("max_pair_regression_ms", max_pair_regression_ms),
    ):
        if not 0 < _ms(value, label) <= 2000:
            raise ValueError(f"invalid {label}")

    matched: dict[str, dict[str, EndpointPause]] = {}
    for sample in pauses:
        if not isinstance(sample, EndpointPause):
            raise TypeError("EndpointPause evidence required")
        if len(matched) >= 500 and sample.case_id not in matched:
            raise ValueError("maximum 500 paired cases")
        variants = matched.setdefault(sample.case_id, {})
        if sample.variant in variants:
            raise ValueError("duplicate variant in case")
        if variants:
            other = next(iter(variants.values()))
            if (other.pause_type != sample.pause_type
                    or other.mid_turn_pause_ms != sample.mid_turn_pause_ms
                    or other.source_turn_id != sample.source_turn_id):
                raise ValueError("paired pause context and source turn must match")
        variants[sample.variant] = sample

    paired = sum(len(rows) == 2 for rows in matched.values())
    mid_pairs = final_pairs = base_false = cand_false = new_false = missing = 0
    regressions = 0
    baseline_delays: list[float] = []
    candidate_delays: list[float] = []
    all_reviewed = bool(matched)
    source_turn_cutoffs: dict[str, bool] = {}
    final_source_turns: set[str] = set()
    for versions in matched.values():
        if set(versions) != _VARIANTS:
            all_reviewed = False
            continue
        base, cand = versions["baseline"], versions["candidate"]
        if (not base.independently_reviewed or not cand.independently_reviewed
                or cand.source_turn_id is None):
            all_reviewed = False
            continue
        source = cand.source_turn_id
        if cand.pause_type == "mid_turn":
            mid_pairs += 1
            b = base.decision_after_pause_ms is not None
            c = cand.decision_after_pause_ms is not None
            base_false += int(b)
            cand_false += int(c)
            new_false += int(c and not b)
            # Multiple hesitations from ONE turn contribute ONE Bernoulli trial.
            source_turn_cutoffs[source] = source_turn_cutoffs.get(source, False) or c
        else:
            if source in final_source_turns:
                raise ValueError("duplicate final endpoint for source turn")
            final_source_turns.add(source)
            final_pairs += 1
            if base.decision_after_pause_ms is None:
                all_reviewed = False
            else:
                baseline_delays.append(base.decision_after_pause_ms)
            if cand.decision_after_pause_ms is None:
                missing += 1
            else:
                candidate_delays.append(cand.decision_after_pause_ms)
                if (base.decision_after_pause_ms is not None
                        and cand.decision_after_pause_ms
                        > base.decision_after_pause_ms + max_pair_regression_ms):
                    regressions += 1

    base_p95 = _p95(baseline_delays)
    cand_p95 = _p95(candidate_delays)
    rate = round(cand_false / mid_pairs, 5) if mid_pairs else None
    turn_trials = len(source_turn_cutoffs)
    turn_false = sum(source_turn_cutoffs.values())
    upper = _false_cutoff_upper_95(turn_false, turn_trials)

    def report(status: str, reason: str) -> EndpointReport:
        return EndpointReport(
            status, reason, paired, mid_pairs, final_pairs,
            base_false, cand_false, new_false, missing,
            base_p95, cand_p95, rate, regressions,
            candidate_false_cutoff_upper_95=(round(upper, 8) if upper is not None else None),
            independent_mid_turns=turn_trials,
            candidate_turns_with_false_cutoff=turn_false,
        )

    if (not all_reviewed or mid_pairs < minimum_per_type
            or turn_trials < minimum_per_type
            or final_pairs < minimum_per_type
            or len(baseline_delays) != final_pairs):
        return report("insufficient_evidence", "missing_pairs_review_or_turn_provenance")
    if (missing or cand_p95 is None or base_p95 is None
            or cand_false / mid_pairs > cutoff_budget + 1e-12
            or turn_false / turn_trials > cutoff_budget + 1e-12
            or new_false or regressions
            or cand_p95 > max_final_p95_ms
            or cand_p95 > base_p95 + max_p95_regression_ms):
        return report("naturalness_regressed", "false_cutoffs_missing_ends_or_latency")
    # A low observed event rate on a tiny holdout must not silently qualify.
    # Even 0/20 has a ~13.9% one-sided upper bound at 95% confidence.
    if upper is None or upper > cutoff_budget + 1e-12:
        return report("insufficient_evidence", "false_cutoff_uncertainty_exceeds_budget")
    return report("eligible_for_manual_rehearsal", "paired_turn_tradeoff_meets_budget")


__all__ = ["EndpointPause", "EndpointReport", "assess_endpointing"]
