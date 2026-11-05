"""Offline host adapter: independently scored game/VTuber attempts -> sealed evidence.

A protected evaluator, NOT an LLM or viewer input, must preregister the rubric,
observe the game/OBS workload, independently decide pass/fail, and hash the raw
scoring artifacts. This adapter computes honest statistics from complete ordered
trials; the HMAC attests to the *host's report*, not that the report is true.

No model is launched, no game input is sent, no TTS/OBS stream is started, and
no secrets, screenshots, prompts or player identities are stored in the bundle.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
import re
import secrets
from typing import cast

from .stream_host_model_catalog import HostInferenceCatalog
from .stream_quality_route_selector import VerifiedPairedRouteCases, VerifiedRouteTrialSummary
from .stream_route_evidence_seal import SealedRouteEvaluation, sign_route_evaluation

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_WORKLOADS = frozenset({"game_recording", "game_stream", "offline"})
_MAX_CASES = 2000
_DOMAIN_SUITE = "STAR-ROUTE-REGISTERED-SUITE-v1"
_DOMAIN_ARTIFACTS = "STAR-ROUTE-MEASURED-ARTIFACTS-v1"


def _digest(value: object, field: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise ValueError(f"{field} requires a lowercase SHA256")
    return value


def _id(value: object, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{field} must be an opaque bounded identifier")
    return value


def _timestamp(value: object, field: str) -> int:
    if type(value) is not int or not 1 <= value <= 10**11:
        raise ValueError(f"{field} must be a bounded integer Unix timestamp")
    return value


def _number(value: object, field: str, *, minimum: float, maximum: float) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{field} must be finite")
    try:
        number = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be finite") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{field} must be finite and within permitted range")
    return number


def _canonical_sha(obj: object) -> str:
    return sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                            allow_nan=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RegisteredRouteCase:
    """A preregistered opaque case commitment, never the task text itself."""
    case_sha256: str
    critical: bool

    def __post_init__(self) -> None:
        _digest(self.case_sha256, "case")
        if type(self.critical) is not bool:
            raise ValueError("critical flag must be a strict boolean")


@dataclass(frozen=True)
class RegisteredRouteSuite:
    """Frozen ordered evaluation manifest committed before any model attempt."""
    task_kind: str
    workload: str
    rubric_sha256: str
    preregistered_unix_s: int
    cases: tuple[RegisteredRouteCase, ...]

    def __post_init__(self) -> None:
        _id(self.task_kind, "task kind")
        if type(self.workload) is not str or self.workload not in _WORKLOADS:
            raise ValueError("unknown measured workload")
        _digest(self.rubric_sha256, "rubric")
        _timestamp(self.preregistered_unix_s, "preregistration")
        if (type(self.cases) is not tuple or not 1 <= len(self.cases) <= _MAX_CASES
                or any(type(case) is not RegisteredRouteCase for case in self.cases)):
            raise ValueError("bounded immutable preregistered cases required")
        hashes = tuple(case.case_sha256 for case in self.cases)
        if len(set(hashes)) != len(hashes):
            raise ValueError("preregistered cases must be unique")

    @property
    def suite_sha256(self) -> str:
        return _canonical_sha({
            "domain": _DOMAIN_SUITE,
            "task_kind": self.task_kind,
            "workload": self.workload,
            "rubric_sha256": self.rubric_sha256,
            "preregistered_unix_s": self.preregistered_unix_s,
            "cases": [asdict(case) for case in self.cases],
        })


@dataclass(frozen=True)
class IndependentlyScoredAttempt:
    """Host-scorer verdict and a digest of its raw independent evidence."""
    case_sha256: str
    scoring_artifact_sha256: str
    passed: bool
    end_to_end_ms: float
    total_gpu_peak_mib: float

    def __post_init__(self) -> None:
        _digest(self.case_sha256, "case")
        _digest(self.scoring_artifact_sha256, "scoring artifact")
        if type(self.passed) is not bool:
            raise ValueError("scorer verdict must be a strict boolean")
        _number(self.end_to_end_ms, "end-to-end time", minimum=0.001, maximum=120_000)
        _number(self.total_gpu_peak_mib, "GPU peak", minimum=0, maximum=262_144)


@dataclass(frozen=True)
class IndependentlyScoredRouteRun:
    route_alias: str
    route_profile: str
    completed_unix_s: int
    attempts: tuple[IndependentlyScoredAttempt, ...]

    def __post_init__(self) -> None:
        _id(self.route_alias, "route alias")
        _id(self.route_profile, "route profile")
        _timestamp(self.completed_unix_s, "run completion")
        if (type(self.attempts) is not tuple or not 1 <= len(self.attempts) <= _MAX_CASES
                or any(type(case) is not IndependentlyScoredAttempt for case in self.attempts)):
            raise ValueError("bounded immutable independent scorer attempts required")


@dataclass(frozen=True)
class MeasuredSealedRouteEvidence:
    """No secret key; only sealed aggregates, matched outcomes and artifact digest."""
    summaries: tuple[VerifiedRouteTrialSummary, VerifiedRouteTrialSummary]
    paired_cases: tuple[VerifiedPairedRouteCases, ...]
    seal: SealedRouteEvaluation


def assemble_measured_route_evidence(*, host_key: bytes,
                                     catalog: HostInferenceCatalog,
                                     suite: RegisteredRouteSuite,
                                     expected_suite_sha256: str,
                                     baseline: IndependentlyScoredRouteRun,
                                     candidate: IndependentlyScoredRouteRun,
                                     evaluator_build_sha256: str,
                                     issued_unix_s: int) -> MeasuredSealedRouteEvidence:
    """Seal a *complete*, independently scored paired run under an exact suite.

    ``expected_suite_sha256`` MUST come from the host's separately committed
    preregistration log. Do not calculate it from runtime model outputs.
    Fresh random cohort IDs prevent accidental cross-run mixing; a persistent
    consumption ledger is still required before one-shot promotion is allowed.
    """
    if type(catalog) is not HostInferenceCatalog:
        raise TypeError("host catalog required")
    if type(suite) is not RegisteredRouteSuite:
        raise TypeError("host-registered suite required")
    _digest(expected_suite_sha256, "expected suite")
    _digest(evaluator_build_sha256, "evaluator build")
    _timestamp(issued_unix_s, "issuance")
    if suite.suite_sha256 != expected_suite_sha256:
        raise ValueError("registered suite differs from committed suite digest")
    if type(baseline) is not IndependentlyScoredRouteRun or type(candidate) is not IndependentlyScoredRouteRun:
        raise TypeError("two host-scored route runs required")
    if baseline.route_alias == candidate.route_alias:
        raise ValueError("baseline and candidate must be different routes")
    for run in (baseline, candidate):
        try:
            actual = catalog.route_for(run.route_alias)
        except KeyError as exc:
            raise ValueError("host-scored run names unknown route") from exc
        if actual.route_profile != run.route_profile or actual.kind != suite.task_kind:
            raise ValueError("measured route is not the exact deployed host worker")
        if not suite.preregistered_unix_s <= run.completed_unix_s <= issued_unix_s:
            raise ValueError("run must finish after preregistration and before signing")
        if issued_unix_s - run.completed_unix_s > 600:
            raise ValueError("stale scored run cannot be signed")
        if tuple(item.case_sha256 for item in run.attempts) != tuple(
            case.case_sha256 for case in suite.cases
        ):
            raise ValueError("missing, reordered, duplicated or unregistered case attempts")
    artifacts = [item.scoring_artifact_sha256 for run in (baseline, candidate) for item in run.attempts]
    if len(set(artifacts)) != len(artifacts):
        raise ValueError("same scoring artifact cannot justify multiple attempts")
    # All failed attempts count toward the denominator. Never filter by success,
    # end-to-end time or GPU usage: this would misreport real-time performance.
    cohort = secrets.token_hex(32)
    raw_manifest = {
        "domain": _DOMAIN_ARTIFACTS,
        "cohort_sha256": cohort,
        "suite_sha256": suite.suite_sha256,
        "baseline": asdict(baseline),
        "candidate": asdict(candidate),
    }
    manifest_sha256 = _canonical_sha(raw_manifest)

    def summary(run: IndependentlyScoredRouteRun) -> VerifiedRouteTrialSummary:
        latencies = sorted(item.end_to_end_ms for item in run.attempts)
        # Nearest-rank p95 measures tail response time, not mean token speed.
        p95_ms = latencies[math.ceil(0.95 * len(latencies)) - 1]
        return VerifiedRouteTrialSummary(
            route_alias=run.route_alias,
            route_profile=run.route_profile,
            task_kind=suite.task_kind,
            workload=suite.workload,
            suite_sha256=suite.suite_sha256,
            trials=len(run.attempts),
            verified_successes=sum(item.passed for item in run.attempts),
            p95_end_to_end_ms=p95_ms,
            total_gpu_peak_mib=max(item.total_gpu_peak_mib for item in run.attempts),
            measured_unix_s=run.completed_unix_s,
            host_verified=True,  # A statement by the separate trusted host, not cryptographic proof.
            eval_cohort_sha256=cohort,
        )

    summaries = (summary(baseline), summary(candidate))
    pairs = (VerifiedPairedRouteCases(
        baseline_alias=baseline.route_alias,
        candidate_alias=candidate.route_alias,
        baseline_profile=baseline.route_profile,
        candidate_profile=candidate.route_profile,
        task_kind=suite.task_kind,
        workload=suite.workload,
        suite_sha256=suite.suite_sha256,
        baseline_outcomes=tuple(item.passed for item in baseline.attempts),
        candidate_outcomes=tuple(item.passed for item in candidate.attempts),
        critical_cases=tuple(case.critical for case in suite.cases),
        measured_unix_s=max(baseline.completed_unix_s, candidate.completed_unix_s),
        host_verified=True,
        eval_cohort_sha256=cohort,
    ),)
    seal = sign_route_evaluation(
        host_key=host_key, cohort_sha256=cohort,
        evaluator_build_sha256=evaluator_build_sha256,
        artifact_manifest_sha256=manifest_sha256,
        issued_unix_s=issued_unix_s, summaries=summaries, paired_cases=pairs,
    )
    return MeasuredSealedRouteEvidence(summaries, pairs, seal)


__all__ = [
    "RegisteredRouteCase", "RegisteredRouteSuite", "IndependentlyScoredAttempt",
    "IndependentlyScoredRouteRun", "MeasuredSealedRouteEvidence", "assemble_measured_route_evidence",
]
