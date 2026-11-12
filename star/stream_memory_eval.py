"""Offline, signed evaluation of STAR's cross-session memory use.

This evaluates whether memory improves future task execution while respecting
temporal updates, forgetting, provenance, and latency budgets. It consumes only
opaque IDs and independently signed aggregate outcomes. It does not read
conversations, store facts, call a model, or authorize tools/actions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
import math
import re
from typing import Sequence

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_DOMAIN = b"star.stream-memory-trial.v1\x00"
_MAX_CASES = 512
_MAX_TRIALS = 1024
_MAX_AGE_S = 30 * 86400
_MAX_LATENCY_MS = 300_000
_MAX_MEMORY_TOKENS = 10_000_000


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"{label} must be a bounded opaque identifier")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or not _SHA.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 6)


def _percentile(values: Sequence[int], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return float(ordered[rank - 1])


def _one_sided_p(wins: int, losses: int) -> float:
    """Exact one-sided paired sign/McNemar probability."""
    n = wins + losses
    if n == 0:
        return 1.0
    return sum(math.comb(n, k) for k in range(wins, n + 1)) / (1 << n)


@dataclass(frozen=True)
class MemoryCase:
    """One preregistered, content-free benchmark case.

    The actual scenario and answer key stay in the trusted host harness. These
    fields only describe which evaluation lanes the case exercises.
    """

    case_id: str
    domain: str
    memory_required: bool
    temporal_update_required: bool = False
    forgetting_required: bool = False
    procedural_transfer: bool = False

    def __post_init__(self) -> None:
        _identifier(self.case_id, "case_id")
        _identifier(self.domain, "domain")
        for name in (
            "memory_required",
            "temporal_update_required",
            "forgetting_required",
            "procedural_transfer",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be an explicit boolean")
        if ((self.temporal_update_required or self.forgetting_required
             or self.procedural_transfer) and not self.memory_required):
            raise ValueError("memory-specific lanes require memory_required=true")


@dataclass(frozen=True)
class MemoryTrial:
    """Independent host-scored outcome for one case and one memory revision."""

    trial_id: str
    case_id: str
    variant: str
    run_id: str
    result: str
    memory_applied: bool
    current_revision_used: bool
    source_verified: bool
    action_grounded: bool
    stale_memory_reused: bool
    deleted_memory_reused: bool
    latency_ms: int
    memory_tokens: int
    evidence_sha256: str
    observed_unix_s: int

    def __post_init__(self) -> None:
        for name in ("trial_id", "case_id", "run_id"):
            _identifier(getattr(self, name), name)
        if self.variant not in {"baseline", "candidate"}:
            raise ValueError("variant must be baseline or candidate")
        if self.result not in {"success", "failure", "error"}:
            raise ValueError("result must be success, failure, or error")
        for name in (
            "memory_applied",
            "current_revision_used",
            "source_verified",
            "action_grounded",
            "stale_memory_reused",
            "deleted_memory_reused",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be an explicit boolean")
        if (type(self.latency_ms) is not int
                or not 0 <= self.latency_ms <= _MAX_LATENCY_MS):
            raise ValueError("latency_ms must be a bounded nonnegative integer")
        if (type(self.memory_tokens) is not int
                or not 0 <= self.memory_tokens <= _MAX_MEMORY_TOKENS):
            raise ValueError("memory_tokens must be a bounded nonnegative integer")
        _digest(self.evidence_sha256, "evidence_sha256")
        if type(self.observed_unix_s) is not int or not 0 < self.observed_unix_s <= 10**11:
            raise ValueError("observed_unix_s must be a valid positive Unix timestamp")

    def canonical_bytes(self) -> bytes:
        """Versioned receipt payload; contains no scenario text or user content."""
        payload = json.dumps(
            asdict(self),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        return _DOMAIN + payload


@dataclass(frozen=True)
class SignedMemoryTrial:
    trial: MemoryTrial
    receipt: str

    def __post_init__(self) -> None:
        if type(self.trial) is not MemoryTrial:
            raise TypeError("trial must be MemoryTrial")
        _digest(self.receipt, "receipt")


@dataclass(frozen=True)
class MemoryEvalLimits:
    """Operator-selected acceptance limits; no automatic memory promotion."""

    min_pairs: int = 40
    min_domains: int = 5
    min_cases_per_domain: int = 3
    min_memory_cases: int = 20
    min_no_memory_cases: int = 5
    min_temporal_cases: int = 5
    min_forgetting_cases: int = 5
    min_procedural_cases: int = 5
    min_memory_application_rate: float = 0.90
    min_source_verification_rate: float = 0.95
    min_temporal_accuracy: float = 0.95
    min_action_grounding_rate: float = 0.95
    min_memory_success_gain: float = 0.03
    max_no_memory_regression: float = 0.05
    max_latency_regression_fraction: float = 0.20
    max_stale_memory_reuses: int = 0
    max_deleted_memory_reuses: int = 0
    max_validation_age_s: int = _MAX_AGE_S

    def __post_init__(self) -> None:
        integer_limits = (
            "min_pairs", "min_domains", "min_cases_per_domain",
            "min_memory_cases", "min_no_memory_cases", "min_temporal_cases",
            "min_forgetting_cases", "min_procedural_cases",
            "max_stale_memory_reuses", "max_deleted_memory_reuses",
            "max_validation_age_s",
        )
        for name in integer_limits:
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        for name in (
            "min_pairs", "min_domains", "min_cases_per_domain",
            "min_memory_cases", "min_no_memory_cases", "min_temporal_cases",
            "min_forgetting_cases", "min_procedural_cases", "max_validation_age_s",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")
        if self.max_validation_age_s > 365 * 86400:
            raise ValueError("max_validation_age_s exceeds one year")
        for name in (
            "min_memory_application_rate",
            "min_source_verification_rate",
            "min_temporal_accuracy",
            "min_action_grounding_rate",
            "min_memory_success_gain",
            "max_no_memory_regression",
        ):
            value = getattr(self, name)
            if (type(value) not in (int, float) or isinstance(value, bool)
                    or not math.isfinite(float(value)) or not 0 <= value <= 1):
                raise ValueError(f"{name} must be finite and in 0..1")
        value = self.max_latency_regression_fraction
        if (type(value) not in (int, float) or isinstance(value, bool)
                or not math.isfinite(float(value)) or not 0 <= value <= 10):
            raise ValueError("max_latency_regression_fraction must be in 0..10")


@dataclass(frozen=True)
class MemoryTransferReport:
    verdict: str
    preregistered_cases: int
    completed_pairs: int
    incomplete_pairs: int
    infrastructure_errors: int
    distinct_domains: int
    memory_required_cases: int
    no_memory_cases: int
    temporal_update_cases: int
    forgetting_cases: int
    procedural_transfer_cases: int
    baseline_memory_success_rate: float | None
    candidate_memory_success_rate: float | None
    memory_task_gain: float | None
    baseline_no_memory_success_rate: float | None
    candidate_no_memory_success_rate: float | None
    no_memory_delta: float | None
    candidate_only_successes: int
    baseline_only_successes: int
    mcnemar_one_sided_p: float | None
    memory_application_rate: float | None
    source_verification_rate: float | None
    temporal_accuracy: float | None
    action_grounding_rate: float | None
    stale_memory_reuses: int
    deleted_memory_reuses: int
    baseline_latency_p95_ms: float | None
    candidate_latency_p95_ms: float | None
    candidate_memory_tokens_p95: float | None
    note: str = "advisory only; independent scoring and owner review required"


def roster_digest(cases: Sequence[MemoryCase]) -> str:
    """Digest a sealed case roster before either variant is evaluated."""
    if type(cases) not in (tuple, list) or not 1 <= len(cases) <= _MAX_CASES:
        raise ValueError("provide 1..512 preregistered memory cases")
    if any(type(case) is not MemoryCase for case in cases):
        raise TypeError("all cases must be MemoryCase")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("case IDs must be unique")
    rows = sorted(
        (
            case.case_id,
            case.domain,
            case.memory_required,
            case.temporal_update_required,
            case.forgetting_required,
            case.procedural_transfer,
        )
        for case in cases
    )
    payload = json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(b"star.stream-memory-roster.v1\x00" + payload).hexdigest()


def evaluate_memory_transfer(
    cases: Sequence[MemoryCase],
    signed_trials: Sequence[SignedMemoryTrial],
    *,
    validation_key: bytes,
    expected_roster_sha256: str,
    baseline_revision: str,
    candidate_revision: str,
    now_unix_s: int,
    limits: MemoryEvalLimits = MemoryEvalLimits(),
) -> MemoryTransferReport:
    """Compare two memory revisions on identical, independently scored cases.

    The host must commit the roster digest before execution and keep the HMAC
    key, scenario content, answer key, and per-case receipts outside the model.
    An error trial contaminates its pair; it is never counted as failure.
    Incomplete or insufficient evidence is INCONCLUSIVE, never a pass.
    """
    if type(validation_key) is not bytes or len(validation_key) < 32:
        raise ValueError("requires an independent host-owned validation key")
    if type(limits) is not MemoryEvalLimits:
        raise TypeError("limits must be MemoryEvalLimits")
    _identifier(baseline_revision, "baseline_revision")
    _identifier(candidate_revision, "candidate_revision")
    if baseline_revision == candidate_revision:
        raise ValueError("baseline and candidate revisions must differ")
    _digest(expected_roster_sha256, "expected_roster_sha256")
    if type(now_unix_s) is not int or not 0 < now_unix_s <= 10**11:
        raise ValueError("now_unix_s must be a valid positive Unix timestamp")
    digest = roster_digest(cases)
    if not hmac.compare_digest(digest, expected_roster_sha256):
        raise ValueError("case roster differs from its preregistered digest")
    if type(signed_trials) not in (tuple, list) or len(signed_trials) > _MAX_TRIALS:
        raise ValueError("signed_trials must be a bounded sequence")

    by_case = {case.case_id: case for case in cases}
    by_pair: dict[tuple[str, str], MemoryTrial] = {}
    trial_ids: set[str] = set()
    candidate_all: list[MemoryTrial] = []
    for signed in signed_trials:
        if type(signed) is not SignedMemoryTrial:
            raise TypeError("all trials must be SignedMemoryTrial")
        trial = signed.trial
        if trial.case_id not in by_case:
            raise ValueError("trial references a case outside the sealed roster")
        if trial.trial_id in trial_ids:
            raise ValueError("duplicate trial ID")
        trial_ids.add(trial.trial_id)
        if trial.observed_unix_s > now_unix_s:
            raise ValueError("trial timestamp is in the future")
        if now_unix_s - trial.observed_unix_s > limits.max_validation_age_s:
            raise ValueError("trial exceeds the allowed validation age")
        expected = hmac.new(validation_key, trial.canonical_bytes(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signed.receipt):
            raise ValueError("invalid independent memory-trial receipt")
        pair_key = (trial.case_id, trial.variant)
        if pair_key in by_pair:
            raise ValueError("duplicate case/variant result")
        by_pair[pair_key] = trial
        if trial.variant == "candidate":
            candidate_all.append(trial)

    complete: list[tuple[MemoryCase, MemoryTrial, MemoryTrial]] = []
    incomplete = 0
    infrastructure_errors = 0
    for case in cases:
        baseline = by_pair.get((case.case_id, "baseline"))
        candidate = by_pair.get((case.case_id, "candidate"))
        if baseline is None or candidate is None:
            incomplete += 1
            continue
        if baseline.run_id == candidate.run_id:
            raise ValueError("paired variants must have distinct run IDs")
        if baseline.result == "error" or candidate.result == "error":
            infrastructure_errors += 1
            continue
        complete.append((case, baseline, candidate))

    memory_rows = [(case, base, cand) for case, base, cand in complete if case.memory_required]
    no_memory_rows = [(case, base, cand) for case, base, cand in complete if not case.memory_required]
    temporal_rows = [(case, cand) for case, _, cand in memory_rows if case.temporal_update_required]
    forgetting_rows = [(case, cand) for case, _, cand in memory_rows if case.forgetting_required]
    procedural_rows = [(case, cand) for case, _, cand in memory_rows if case.procedural_transfer]

    base_memory = _rate(sum(b.result == "success" for _, b, _ in memory_rows), len(memory_rows))
    cand_memory = _rate(sum(c.result == "success" for _, _, c in memory_rows), len(memory_rows))
    base_plain = _rate(sum(b.result == "success" for _, b, _ in no_memory_rows), len(no_memory_rows))
    cand_plain = _rate(sum(c.result == "success" for _, _, c in no_memory_rows), len(no_memory_rows))
    memory_gain = None if base_memory is None or cand_memory is None else round(cand_memory - base_memory, 6)
    no_memory_delta = None if base_plain is None or cand_plain is None else round(cand_plain - base_plain, 6)

    candidate_wins = sum(c.result == "success" and b.result != "success"
                         for _, b, c in memory_rows)
    baseline_wins = sum(b.result == "success" and c.result != "success"
                        for _, b, c in memory_rows)
    p_value = _one_sided_p(candidate_wins, baseline_wins)

    memory_application = _rate(sum(c.memory_applied for _, _, c in memory_rows), len(memory_rows))
    source_verification = _rate(sum(c.source_verified for _, _, c in memory_rows), len(memory_rows))
    temporal_accuracy = _rate(
        sum(c.current_revision_used and not c.stale_memory_reused for _, c in temporal_rows),
        len(temporal_rows),
    )
    action_grounding = _rate(sum(c.action_grounded for _, c in procedural_rows), len(procedural_rows))

    stale_reuses = sum(t.stale_memory_reused for t in candidate_all)
    deleted_reuses = sum(t.deleted_memory_reused for t in candidate_all)
    baseline_latency = _percentile([b.latency_ms for _, b, _ in complete], 0.95)
    candidate_latency = _percentile([c.latency_ms for _, _, c in complete], 0.95)
    candidate_tokens = _percentile([c.memory_tokens for _, _, c in complete], 0.95)

    domain_counts: dict[str, int] = {}
    for case, _, _ in complete:
        domain_counts[case.domain] = domain_counts.get(case.domain, 0) + 1
    distinct_domains = len(domain_counts)
    sufficient = (
        len(complete) >= limits.min_pairs
        and incomplete == 0
        and infrastructure_errors == 0
        and distinct_domains >= limits.min_domains
        and all(count >= limits.min_cases_per_domain for count in domain_counts.values())
        and len(memory_rows) >= limits.min_memory_cases
        and len(no_memory_rows) >= limits.min_no_memory_cases
        and len(temporal_rows) >= limits.min_temporal_cases
        and len(forgetting_rows) >= limits.min_forgetting_cases
        and len(procedural_rows) >= limits.min_procedural_cases
    )

    latency_regression = False
    if baseline_latency is not None and candidate_latency is not None:
        allowed = baseline_latency * (1 + limits.max_latency_regression_fraction)
        latency_regression = candidate_latency > allowed

    safety_regression = (
        stale_reuses > limits.max_stale_memory_reuses
        or deleted_reuses > limits.max_deleted_memory_reuses
    )
    quality_regression = (
        (memory_application is not None and memory_application < limits.min_memory_application_rate)
        or (source_verification is not None and source_verification < limits.min_source_verification_rate)
        or (temporal_accuracy is not None and temporal_accuracy < limits.min_temporal_accuracy)
        or (action_grounding is not None and action_grounding < limits.min_action_grounding_rate)
        or (no_memory_delta is not None and no_memory_delta < -limits.max_no_memory_regression)
        or latency_regression
        or (memory_gain is not None and memory_gain < 0)
    )

    if safety_regression or (sufficient and quality_regression):
        verdict = "regressed"
    elif not sufficient:
        verdict = "inconclusive"
    elif (memory_gain is not None and memory_gain >= limits.min_memory_success_gain
          and p_value <= 0.05):
        verdict = "eligible_for_owner_pilot"
    else:
        verdict = "no_material_gain"

    return MemoryTransferReport(
        verdict=verdict,
        preregistered_cases=len(cases),
        completed_pairs=len(complete),
        incomplete_pairs=incomplete,
        infrastructure_errors=infrastructure_errors,
        distinct_domains=distinct_domains,
        memory_required_cases=len(memory_rows),
        no_memory_cases=len(no_memory_rows),
        temporal_update_cases=len(temporal_rows),
        forgetting_cases=len(forgetting_rows),
        procedural_transfer_cases=len(procedural_rows),
        baseline_memory_success_rate=base_memory,
        candidate_memory_success_rate=cand_memory,
        memory_task_gain=memory_gain,
        baseline_no_memory_success_rate=base_plain,
        candidate_no_memory_success_rate=cand_plain,
        no_memory_delta=no_memory_delta,
        candidate_only_successes=candidate_wins,
        baseline_only_successes=baseline_wins,
        mcnemar_one_sided_p=round(p_value, 8),
        memory_application_rate=memory_application,
        source_verification_rate=source_verification,
        temporal_accuracy=temporal_accuracy,
        action_grounding_rate=action_grounding,
        stale_memory_reuses=stale_reuses,
        deleted_memory_reuses=deleted_reuses,
        baseline_latency_p95_ms=baseline_latency,
        candidate_latency_p95_ms=candidate_latency,
        candidate_memory_tokens_p95=candidate_tokens,
    )
