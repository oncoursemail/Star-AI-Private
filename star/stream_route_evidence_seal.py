"""Host-only HMAC envelope for matched game/VTuber model route evaluations.

The key is generated and retained outside STAR's repository by the owner-run
offline evaluator. A signature authenticates the *reported* measurements and
artifact-manifest digest, not their factual correctness or hidden-test secrecy.
This module does not run a model, open an OBS stream, or authorize game input.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
import re

from .stream_quality_route_selector import (
    VerifiedPairedRouteCases, VerifiedRouteTrialSummary,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_DOMAIN = "STAR-ROUTE-EVAL-HMAC-SHA256-v1"
_MAX_EVIDENCE = 64
_MAX_SIGNING_DELAY_S = 600


def _digest(value: object, field: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} requires a lowercase SHA256")
    return value


def _key(value: object) -> bytes:
    if type(value) is not bytes or not 32 <= len(value) <= 4096:
        raise ValueError("host seal key must be 32..4096 bytes")
    return value


@dataclass(frozen=True)
class SealedRouteEvaluation:
    """Public metadata only; the secret key must never enter this record."""
    cohort_sha256: str
    evaluator_build_sha256: str
    artifact_manifest_sha256: str
    issued_unix_s: int
    signature_hmac_sha256: str

    def __post_init__(self) -> None:
        _digest(self.cohort_sha256, "cohort")
        _digest(self.evaluator_build_sha256, "evaluator build")
        _digest(self.artifact_manifest_sha256, "artifact manifest")
        _digest(self.signature_hmac_sha256, "signature")
        if type(self.issued_unix_s) is not int or not 1 <= self.issued_unix_s <= 10**11:
            raise ValueError("issued Unix time must be a bounded integer")


def _canonical_evidence(*, seal: SealedRouteEvaluation,
                        summaries: tuple[VerifiedRouteTrialSummary, ...],
                        paired_cases: tuple[VerifiedPairedRouteCases, ...]) -> bytes:
    """Encode every scored outcome and metric; forbid cross-cohort splicing."""
    if type(summaries) is not tuple or not 1 <= len(summaries) <= _MAX_EVIDENCE:
        raise ValueError("bounded immutable aggregate evidence required")
    if type(paired_cases) is not tuple or len(paired_cases) > _MAX_EVIDENCE:
        raise ValueError("bounded immutable paired evidence required")
    for item in (*summaries, *paired_cases):
        if type(item) not in (VerifiedRouteTrialSummary, VerifiedPairedRouteCases):
            raise ValueError("unexpected evidence record")
        if not item.host_verified or item.eval_cohort_sha256 != seal.cohort_sha256:
            raise ValueError("host-approved evidence must belong to one cohort")
        if not 0 <= seal.issued_unix_s - item.measured_unix_s <= _MAX_SIGNING_DELAY_S:
            raise ValueError("evaluation issuance does not follow measurement")
    # Sorting is for deterministic encoding, never for choosing which trial passes.
    sorted_summaries = sorted(
        summaries, key=lambda x: (x.route_alias, x.task_kind, x.workload, x.suite_sha256),
    )
    sorted_pairs = sorted(
        paired_cases, key=lambda x: (
            x.baseline_alias, x.candidate_alias, x.task_kind, x.workload, x.suite_sha256,
        ),
    )
    body = {
        "domain": _DOMAIN,
        "cohort_sha256": seal.cohort_sha256,
        "evaluator_build_sha256": seal.evaluator_build_sha256,
        "artifact_manifest_sha256": seal.artifact_manifest_sha256,
        "issued_unix_s": seal.issued_unix_s,
        "summaries": [asdict(item) for item in sorted_summaries],
        "paired_cases": [asdict(item) for item in sorted_pairs],
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sign_route_evaluation(*, host_key: bytes, cohort_sha256: str,
                          evaluator_build_sha256: str, artifact_manifest_sha256: str,
                          issued_unix_s: int,
                          summaries: tuple[VerifiedRouteTrialSummary, ...],
                          paired_cases: tuple[VerifiedPairedRouteCases, ...]
                          ) -> SealedRouteEvaluation:
    """Owner/evaluator-only signing. Do not expose this to an LLM tool."""
    key = _key(host_key)
    unsigned = SealedRouteEvaluation(
        cohort_sha256, evaluator_build_sha256, artifact_manifest_sha256,
        issued_unix_s, "0" * 64,
    )
    payload = _canonical_evidence(
        seal=unsigned, summaries=summaries, paired_cases=paired_cases,
    )
    return SealedRouteEvaluation(
        cohort_sha256, evaluator_build_sha256, artifact_manifest_sha256,
        issued_unix_s, hmac.new(key, payload, hashlib.sha256).hexdigest(),
    )


def verify_route_evaluation(*, host_key: bytes, seal: SealedRouteEvaluation,
                            summaries: tuple[VerifiedRouteTrialSummary, ...],
                            paired_cases: tuple[VerifiedPairedRouteCases, ...]) -> bool:
    """Return False for any malformed, altered, cross-run or forged evidence."""
    key = _key(host_key)
    if type(seal) is not SealedRouteEvaluation:
        return False
    try:
        payload = _canonical_evidence(
            seal=seal, summaries=summaries, paired_cases=paired_cases,
        )
    except (ValueError, TypeError, OverflowError):
        return False
    return hmac.compare_digest(
        hmac.new(key, payload, hashlib.sha256).hexdigest(),
        seal.signature_hmac_sha256,
    )


__all__ = ["SealedRouteEvaluation", "sign_route_evaluation", "verify_route_evaluation"]
