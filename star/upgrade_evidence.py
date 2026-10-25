"""Independent, read-only comparison of end-to-end STAR upgrade evidence.

This is an *experimental reviewer aid*, not a production authorization system.
Run and grade tasks in a trusted host outside the model's write scope; callers
must authenticate provenance. A passed unit test, invented score or a boolean
supplied by an agent is not trusted evidence. This module performs no I/O.

Measured benchmark runs may contain sensitive test-case identifiers, so callers
must never place secret holdouts, test answers or owner chats in model context.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Literal

Mode = Literal["cold", "warm"]
Family = Literal["coding", "research", "studio_ui", "studio_scene", "studio_game"]
Status = Literal["insufficient", "regression", "inconclusive", "candidate_for_review"]
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
REQUIRED_CHECKS: dict[str, frozenset[str]] = {
    "coding": frozenset({"static", "isolated_unit", "end_to_end", "holdout_confirmation"}),
    "research": frozenset({"source_grounding", "end_to_end", "holdout_confirmation"}),
    "studio_ui": frozenset({"static", "studio_playtest", "visual_review", "device_layout", "end_to_end", "holdout_confirmation"}),
    "studio_scene": frozenset({"static", "studio_playtest", "visual_review", "collision_layout", "end_to_end", "holdout_confirmation"}),
    "studio_game": frozenset({"static", "studio_playtest", "visual_review", "device_layout", "multiplayer", "player_input", "end_to_end", "holdout_confirmation"}),
}


def _sha(s: str, name: str) -> str:
    if not isinstance(s, str) or not SHA_RE.fullmatch(s):
        raise ValueError(f"{name}: expected lowercase SHA-256 digest")
    return s


def _ms(v: int, name: str) -> int:
    if type(v) is not int or not 0 < v <= 86_400_000:
        raise ValueError(f"{name}: expected measured milliseconds in (0, 86400000]")
    return v


@dataclass(frozen=True)
class Trial:
    """One case, one first-attempt baseline/candidate pair in the same cache condition.

    Includes full runtime (generation, tools, verification, retries if the
    policy itself uses them), NOT just token generation time. Successful first
    attempts are provided by a separate grader and never inferred from text.
    """

    case_sha256: str
    mode: Mode
    baseline_ok: bool
    candidate_ok: bool
    baseline_total_ms: int
    candidate_total_ms: int
    baseline_ttft_ms: int
    candidate_ttft_ms: int
    infrastructure_verified: bool

    def __post_init__(self) -> None:
        _sha(self.case_sha256, "case")
        if self.mode not in ("cold", "warm"):
            raise ValueError("Only cold and warm cache states are supported")
        if type(self.baseline_ok) is not bool or type(self.candidate_ok) is not bool:
            raise ValueError("Task outcomes must be booleans")
        if type(self.infrastructure_verified) is not bool:
            raise ValueError("infrastructure_verified must be boolean")
        for n in ("baseline_total_ms", "candidate_total_ms", "baseline_ttft_ms", "candidate_ttft_ms"):
            _ms(getattr(self, n), n)
        if self.baseline_ttft_ms > self.baseline_total_ms or self.candidate_ttft_ms > self.candidate_total_ms:
            raise ValueError("First-token timing cannot exceed end-to-end latency")


@dataclass(frozen=True)
class Calibration:
    """Independent rubric results, verified outside STAR's generative agent.

    Counts are *aggregates*, not unredacted holdout cases. An attestation string
    alone does not authenticate the evaluator; verify signatures/identity
    outside this module before constructing an instance.
    """

    completed: frozenset[str]
    required_quality_regressions: int
    reviewer_consensus: bool
    holdout_cases: int = 0
    holdout_baseline_passes: int = 0
    holdout_candidate_passes: int = 0
    holdout_case_regressions: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.completed, frozenset) or not all(
            isinstance(x, str) and bool(x) and len(x) <= 48 for x in self.completed
        ):
            raise ValueError("completed must be a set of trusted check names")
        if type(self.required_quality_regressions) is not int or self.required_quality_regressions < 0:
            raise ValueError("required_quality_regressions must be nonnegative")
        if type(self.reviewer_consensus) is not bool:
            raise ValueError("reviewer_consensus must be boolean")
        for name in ("holdout_cases", "holdout_baseline_passes", "holdout_candidate_passes", "holdout_case_regressions"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if (self.holdout_baseline_passes > self.holdout_cases or
                self.holdout_candidate_passes > self.holdout_cases or
                self.holdout_case_regressions > self.holdout_baseline_passes):
            raise ValueError("Impossible blind holdout summary")


@dataclass(frozen=True)
class Comparison:
    """Only comparable runs from the same frozen suite, grader and device.

    A candidate may intentionally change model/prompt settings; those belong in
    its change description and in a new revision hash, but not in the frozen
    evaluator or hardware fingerprint. Case hashes must remain private.
    """

    family: Family
    suite_sha256: str
    grader_sha256: str
    device_sha256: str
    trials: tuple[Trial, ...]
    checks: Calibration

    def __post_init__(self) -> None:
        if self.family not in REQUIRED_CHECKS:
            raise ValueError("Unknown task family")
        for name in ("suite_sha256", "grader_sha256", "device_sha256"):
            _sha(getattr(self, name), name)
        if not isinstance(self.trials, tuple) or any(not isinstance(x, Trial) for x in self.trials):
            raise ValueError("trials must be an immutable sequence of trials")
        if not isinstance(self.checks, Calibration):
            raise ValueError("Checks must be an independent calibration record")
        # Pair identity is (case, cache condition): cold and warm runs of the
        # same task count as *one* statistical cluster in the quality sign test.
        seen = [(t.case_sha256, t.mode) for t in self.trials]
        if len(seen) != len(set(seen)):
            raise ValueError("Repeated or edited first-attempt trial")


@dataclass(frozen=True)
class Audit:
    status: Status
    can_request_owner_review: bool
    reasons: tuple[str, ...]
    trials: int
    distinct_cases: int
    first_attempt_baseline: float
    first_attempt_candidate: float
    baseline_p95_ms: dict[str, int]
    candidate_p95_ms: dict[str, int]
    baseline_p95_ttft_ms: dict[str, int]
    candidate_p95_ttft_ms: dict[str, int]
    baseline_tasks_per_minute: float
    candidate_tasks_per_minute: float
    baseline_successes_per_minute: float
    candidate_successes_per_minute: float


def _p95(items: list[int]) -> int:
    return sorted(items)[math.ceil(len(items) * .95) - 1]


def _sign_tail(wins: int, losses: int) -> float:
    """One-sided exact sign-test tail, numerically stable for larger datasets."""
    n = wins + losses
    if n == 0:
        return 1.0
    # Symmetry: P[X >= wins] equals P[X <= losses], X~Binom(n, 0.5).
    # log-sum-exp avoids giant binomial integers and is stable at large n.
    logs = [math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
            - n * math.log(2) for k in range(losses + 1)]
    vmax = max(logs)
    return min(1.0, math.exp(vmax) * math.fsum(math.exp(p - vmax) for p in logs))


def audit_comparison(data: Comparison, *, minimum_cases: int = 24, alpha: float = 0.01,
                     maximum_quality_slowdown: float = 1.05,
                     minimum_speed_gain: float = 0.10, candidate_count: int = 1) -> Audit:
    """Compare trial evidence. No model decision, automatic merge or deployment.

    Minimum 24 *distinct* tasks is a starting policy, not a power calculation.
    Quality differences are tested by case cluster, not by counting cold and
    warm runs of the same task as independent discoveries.
    """
    if not isinstance(data, Comparison):
        raise TypeError("Expected Comparison")
    if type(minimum_cases) is not int or minimum_cases < 12:
        raise ValueError("minimum_cases must be >= 12")
    if not isinstance(alpha, float) or not 0 < alpha <= .05:
        raise ValueError("alpha must be a float in (0, 0.05]")
    if not 1 <= maximum_quality_slowdown <= 1.5 or not 0 < minimum_speed_gain < .5:
        raise ValueError("Invalid performance bounds")
    if type(candidate_count) is not int or not 1 <= candidate_count <= 10000:
        raise ValueError("candidate_count must be an independently measured positive number")
    alpha /= candidate_count  # Bonferroni across proposals on this frozen development task family.

    trials = data.trials
    cases = {t.case_sha256 for t in trials}
    modes = {t.mode for t in trials}
    reasons: list[str] = []
    present = data.checks.completed
    missing_checks = REQUIRED_CHECKS[data.family] - present
    if missing_checks:
        reasons.append("missing independent checks: " + ", ".join(sorted(missing_checks)))
    if not data.checks.reviewer_consensus:
        reasons.append("missing calibrated independent reviewer agreement")
    if data.checks.required_quality_regressions:
        reasons.append(f"quality regression: {data.checks.required_quality_regressions} essential rubric dimensions")
    if data.checks.holdout_cases < 12:
        reasons.append("holdout confirmation requires at least 12 independent cases")
    if data.checks.holdout_candidate_passes < data.checks.holdout_baseline_passes:
        reasons.append("blind holdout success rate dropped")
    if data.checks.holdout_case_regressions:
        reasons.append(f"blind holdout: {data.checks.holdout_case_regressions} case regression(s)")
    if len(cases) < minimum_cases:
        reasons.append(f"insufficient independent cases: {len(cases)} < {minimum_cases}")
    if modes != {"cold", "warm"}:
        reasons.append("cold AND warm cache conditions must be measured")
    if any(not t.infrastructure_verified for t in trials):
        reasons.append("one or more benchmark trials have unverified infrastructure")
    # Cold/warm cannot contribute extra independent quality samples. Any case
    # that flips negatively in either environment counts as one regression.
    grouped: dict[str, list[Trial]] = {}
    for t in trials:
        grouped.setdefault(t.case_sha256, []).append(t)
    improvement = sum(all((not t.baseline_ok) and t.candidate_ok for t in ts)
                      for ts in grouped.values())
    regression = sum(any(t.baseline_ok and not t.candidate_ok for t in ts)
                     for ts in grouped.values())
    quality_p = _sign_tail(improvement, regression)
    if regression:
        reasons.append(f"{regression} first-attempt correctness regression(s)")
    baseline_passed = sum(t.baseline_ok for t in trials)
    candidate_passed = sum(t.candidate_ok for t in trials)
    n = len(trials)
    baseline_total = sum(t.baseline_total_ms for t in trials)
    candidate_total = sum(t.candidate_total_ms for t in trials)
    base_p95 = {mode: _p95([t.baseline_total_ms for t in trials if t.mode == mode]) for mode in modes}
    cand_p95 = {mode: _p95([t.candidate_total_ms for t in trials if t.mode == mode]) for mode in modes}
    base_ttft = {mode: _p95([t.baseline_ttft_ms for t in trials if t.mode == mode]) for mode in modes}
    cand_ttft = {mode: _p95([t.candidate_ttft_ms for t in trials if t.mode == mode]) for mode in modes}

    # Require both modes to have enough samples to make their p95 meaningful.
    for mode in sorted(modes):
        samples = sum(t.mode == mode for t in trials)
        if samples < minimum_cases:
            reasons.append(f"{mode}: only {samples} timing samples; need {minimum_cases}")

    quality_gain = improvement > 0 and regression == 0 and quality_p <= alpha
    unaltered_quality = improvement == 0 and regression == 0 and all(
        t.baseline_ok == t.candidate_ok for t in trials
    )
    stable_p95 = all(cand_p95[m] <= base_p95[m] * maximum_quality_slowdown for m in modes)
    faster_p95 = all(cand_p95[m] <= base_p95[m] * (1 - minimum_speed_gain) for m in modes)
    # Speed significance uses task clusters: both cold and warm must improve by
    # >=5% to count as one win, eliminating cherry-picking by cache condition.
    faster = sum(all(t.candidate_total_ms <= t.baseline_total_ms * .95 for t in ts)
                 and {t.mode for t in ts} == {"cold", "warm"} for ts in grouped.values())
    slower = sum(any(t.candidate_total_ms >= t.baseline_total_ms * 1.05 for t in ts)
                 for ts in grouped.values())
    speed_p = _sign_tail(faster, slower)
    stable_ttft = all(cand_ttft[m] <= base_ttft[m] * maximum_quality_slowdown for m in modes)
    speed_gain = unaltered_quality and baseline_passed > 0 and faster_p95 and stable_ttft and speed_p <= alpha
    proved = (quality_gain and stable_p95 and stable_ttft) or speed_gain
    if not proved:
        reasons.append("no statistically supported improvement without end-to-end or first-token latency regressions")
    critical_regression = bool(regression or data.checks.required_quality_regressions or
                               data.checks.holdout_case_regressions or
                               data.checks.holdout_candidate_passes < data.checks.holdout_baseline_passes)
    missing = (any(not t.infrastructure_verified for t in trials) or
               data.checks.holdout_cases < 12 or len(cases) < minimum_cases or modes != {"cold", "warm"} or
               any(sum(t.mode == mode for t in trials) < minimum_cases for mode in modes))
    qualified = proved and not (missing or missing_checks or critical_regression or
                                  not data.checks.reviewer_consensus)
    if critical_regression:
        status: Status = "regression"
    elif missing or missing_checks or not data.checks.reviewer_consensus:
        status = "insufficient"
    elif qualified:
        status = "candidate_for_review"
    else:
        status = "inconclusive"
    return Audit(
        status=status, can_request_owner_review=qualified, reasons=tuple(reasons),
        trials=n, distinct_cases=len(cases),
        first_attempt_baseline=baseline_passed / n if n else 0.0,
        first_attempt_candidate=candidate_passed / n if n else 0.0,
        baseline_p95_ms=base_p95, candidate_p95_ms=cand_p95,
        baseline_p95_ttft_ms=base_ttft, candidate_p95_ttft_ms=cand_ttft,
        baseline_tasks_per_minute=(n * 60000 / baseline_total if baseline_total else 0.0),
        candidate_tasks_per_minute=(n * 60000 / candidate_total if candidate_total else 0.0),
        baseline_successes_per_minute=(baseline_passed * 60000 / baseline_total if baseline_total else 0.0),
        candidate_successes_per_minute=(candidate_passed * 60000 / candidate_total if candidate_total else 0.0),
    )
