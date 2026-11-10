"""Governed, reversible proposals for consolidating STAR's long-term memory.

This is a pure offline policy gate. It accepts only host-signed, content-free
metadata and never reads or mutates a memory database. A passing proposal is
eligible for owner review only; it is not automatically promoted.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import hmac
import json
import re
from typing import Literal

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,95}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_TIERS = {"episodic", "semantic", "procedural", "causal"}
_PRIVACY = {"public", "project_private", "owner_private", "viewer_private", "raw_media"}
_MAX_COUNT = 1_000_000
_MAX_TIME_MS = 10**13
_MAX_KEY_BYTES = 128
_MIN_KEY_BYTES = 32
DecisionStatus = Literal[
    "eligible_for_owner_review", "insufficient_evidence", "revalidation_required", "quarantined", "blocked"
]


def _id(value: object, label: str) -> None:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"invalid {label}")


def _sha(value: object, label: str) -> None:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise ValueError(f"invalid {label}")


def _key_bytes(key: bytes) -> bytes:
    if type(key) is not bytes or not _MIN_KEY_BYTES <= len(key) <= _MAX_KEY_BYTES:
        raise ValueError("trusted host key must contain 32..128 bytes")
    return key


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("payload is not canonical JSON") from exc


def _mac(domain: bytes, payload: object, key: bytes) -> str:
    return hmac.new(_key_bytes(key), domain + b"\x00" + _canonical(payload), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class MemoryConsolidationPolicy:
    """Versioned evidence thresholds; changing any field changes the digest."""

    max_age_ms: int = 30 * 24 * 60 * 60 * 1000
    episodic_min_evidence: int = 1
    episodic_min_sources: int = 1
    episodic_min_verified: int = 1
    semantic_min_evidence: int = 2
    semantic_min_sources: int = 2
    semantic_min_verified: int = 2
    procedural_min_evidence: int = 2
    procedural_min_sources: int = 1
    procedural_min_verified: int = 2
    procedural_min_edge_cases: int = 1
    causal_min_evidence: int = 2
    causal_min_sources: int = 2
    causal_min_verified: int = 2

    def __post_init__(self) -> None:
        for name, value in self.payload().items():
            if name == "schema_version":
                continue
            if type(value) is not int or not 1 <= value <= _MAX_COUNT * 30 * 24 * 60 * 60 * 1000:
                raise ValueError(f"invalid policy field: {name}")
        for prefix in ("episodic", "semantic", "procedural", "causal"):
            evidence = getattr(self, f"{prefix}_min_evidence")
            sources = getattr(self, f"{prefix}_min_sources")
            verified = getattr(self, f"{prefix}_min_verified")
            if sources > evidence or verified > evidence:
                raise ValueError(f"{prefix} thresholds cannot exceed minimum evidence")
        if self.procedural_min_edge_cases > self.procedural_min_verified:
            raise ValueError("procedural edge-case threshold cannot exceed verified outcomes")

    def payload(self) -> dict[str, int]:
        return {
            "schema_version": 1,
            "max_age_ms": self.max_age_ms,
            "episodic_min_evidence": self.episodic_min_evidence,
            "episodic_min_sources": self.episodic_min_sources,
            "episodic_min_verified": self.episodic_min_verified,
            "semantic_min_evidence": self.semantic_min_evidence,
            "semantic_min_sources": self.semantic_min_sources,
            "semantic_min_verified": self.semantic_min_verified,
            "procedural_min_evidence": self.procedural_min_evidence,
            "procedural_min_sources": self.procedural_min_sources,
            "procedural_min_verified": self.procedural_min_verified,
            "procedural_min_edge_cases": self.procedural_min_edge_cases,
            "causal_min_evidence": self.causal_min_evidence,
            "causal_min_sources": self.causal_min_sources,
            "causal_min_verified": self.causal_min_verified,
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(b"star.memory-consolidation.policy.v1\x00" + _canonical(self.payload())).hexdigest()


@dataclass(frozen=True)
class MemoryConsolidationCandidate:
    """Host-created proposal containing digests and aggregate evidence only."""

    candidate_id: str
    candidate_sha256: str
    evidence_sha256: str
    tier: str
    privacy_scope: str
    dependency_manifest_sha256: str
    current_dependency_manifest_sha256: str
    host_clock_epoch_sha256: str
    previous_snapshot_sha256: str
    proposed_snapshot_sha256: str
    created_at_ms: int
    expires_at_ms: int
    evidence_count: int
    independent_source_count: int
    verified_outcome_count: int
    verified_edge_case_count: int
    unresolved_conflict_count: int
    untrusted_source_count: int
    stale_dependency_count: int
    signature: str = ""

    def __post_init__(self) -> None:
        _id(self.candidate_id, "candidate ID")
        for name in (
            "candidate_sha256", "evidence_sha256", "dependency_manifest_sha256",
            "current_dependency_manifest_sha256", "host_clock_epoch_sha256",
            "previous_snapshot_sha256", "proposed_snapshot_sha256",
        ):
            _sha(getattr(self, name), name)
        if self.tier not in _TIERS:
            raise ValueError("unknown memory tier")
        if self.privacy_scope not in _PRIVACY:
            raise ValueError("unknown privacy scope")
        if (type(self.created_at_ms) is not int or type(self.expires_at_ms) is not int
                or not 0 <= self.created_at_ms < self.expires_at_ms <= _MAX_TIME_MS):
            raise ValueError("invalid candidate validity window")
        counts = (
            self.evidence_count, self.independent_source_count, self.verified_outcome_count,
            self.verified_edge_case_count, self.unresolved_conflict_count,
            self.untrusted_source_count, self.stale_dependency_count,
        )
        if any(type(value) is not int or not 0 <= value <= _MAX_COUNT for value in counts):
            raise ValueError("evidence counts must be bounded nonnegative integers")
        if (self.independent_source_count > self.evidence_count
                or self.verified_outcome_count > self.evidence_count
                or self.verified_edge_case_count > self.verified_outcome_count
                or self.unresolved_conflict_count > self.evidence_count
                or self.untrusted_source_count > self.evidence_count):
            raise ValueError("evidence counts are internally inconsistent")
        if type(self.signature) is not str or (self.signature and _SHA.fullmatch(self.signature) is None):
            raise ValueError("invalid candidate signature")

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "candidate_id": self.candidate_id,
            "candidate_sha256": self.candidate_sha256,
            "evidence_sha256": self.evidence_sha256,
            "tier": self.tier,
            "privacy_scope": self.privacy_scope,
            "dependency_manifest_sha256": self.dependency_manifest_sha256,
            "current_dependency_manifest_sha256": self.current_dependency_manifest_sha256,
            "host_clock_epoch_sha256": self.host_clock_epoch_sha256,
            "previous_snapshot_sha256": self.previous_snapshot_sha256,
            "proposed_snapshot_sha256": self.proposed_snapshot_sha256,
            "created_at_ms": self.created_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "evidence_count": self.evidence_count,
            "independent_source_count": self.independent_source_count,
            "verified_outcome_count": self.verified_outcome_count,
            "verified_edge_case_count": self.verified_edge_case_count,
            "unresolved_conflict_count": self.unresolved_conflict_count,
            "untrusted_source_count": self.untrusted_source_count,
            "stale_dependency_count": self.stale_dependency_count,
        }


def seal_candidate(candidate: MemoryConsolidationCandidate, key: bytes) -> MemoryConsolidationCandidate:
    """Sign a host-constructed proposal; never expose the key to a model worker."""
    return replace(candidate, signature=_mac(b"star.memory-consolidation.candidate.v1", candidate.payload(), key))


@dataclass(frozen=True)
class ConsolidationDecision:
    status: DecisionStatus
    reasons: tuple[str, ...]
    candidate_sha256: str
    policy_sha256: str
    rollback_to_sha256: str
    signature: str

    @property
    def eligible_for_owner_review(self) -> bool:
        return self.status == "eligible_for_owner_review"

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "status": self.status,
            "reasons": list(self.reasons),
            "candidate_sha256": self.candidate_sha256,
            "policy_sha256": self.policy_sha256,
            "rollback_to_sha256": self.rollback_to_sha256,
        }


def evaluate_consolidation(
    candidate: MemoryConsolidationCandidate,
    policy: MemoryConsolidationPolicy,
    *,
    trusted_host_key: bytes,
    now_ms: int,
    current_host_clock_epoch_sha256: str,
) -> ConsolidationDecision:
    """Return a signed advisory decision; never mutates or promotes memory."""
    key = _key_bytes(trusted_host_key)
    if type(now_ms) is not int or not 0 <= now_ms <= _MAX_TIME_MS:
        raise ValueError("now_ms must be a bounded monotonic host timestamp")
    _sha(current_host_clock_epoch_sha256, "current host clock epoch")
    expected = _mac(b"star.memory-consolidation.candidate.v1", candidate.payload(), key)
    if not hmac.compare_digest(expected, candidate.signature):
        raise PermissionError("candidate host signature is invalid")

    reasons: list[str] = []
    status: DecisionStatus
    age = now_ms - candidate.created_at_ms
    if candidate.created_at_ms > now_ms or candidate.expires_at_ms <= now_ms or age > policy.max_age_ms:
        status = "revalidation_required"
        reasons.append("candidate_is_future_dated_or_expired")
    elif candidate.host_clock_epoch_sha256 != current_host_clock_epoch_sha256:
        status = "revalidation_required"
        reasons.append("host_clock_epoch_changed")
    elif (candidate.dependency_manifest_sha256 != candidate.current_dependency_manifest_sha256
          or candidate.stale_dependency_count > 0):
        status = "revalidation_required"
        reasons.append("dependency_state_changed_or_stale")
    elif candidate.privacy_scope in {"viewer_private", "raw_media"}:
        status = "blocked"
        reasons.append("private_viewer_or_raw_media_cannot_enter_durable_memory")
    elif candidate.unresolved_conflict_count > 0 or candidate.untrusted_source_count > 0:
        status = "quarantined"
        if candidate.unresolved_conflict_count > 0:
            reasons.append("unresolved_evidence_conflict")
        if candidate.untrusted_source_count > 0:
            reasons.append("untrusted_evidence_source")
    else:
        prefix = candidate.tier
        required_evidence = getattr(policy, f"{prefix}_min_evidence")
        required_sources = getattr(policy, f"{prefix}_min_sources")
        required_verified = getattr(policy, f"{prefix}_min_verified")
        insufficient: list[str] = []
        if candidate.evidence_count < required_evidence:
            insufficient.append("evidence_count_below_policy")
        if candidate.independent_source_count < required_sources:
            insufficient.append("independent_sources_below_policy")
        if candidate.verified_outcome_count < required_verified:
            insufficient.append("verified_outcomes_below_policy")
        if candidate.tier == "procedural" and candidate.verified_edge_case_count < policy.procedural_min_edge_cases:
            insufficient.append("procedural_edge_case_coverage_below_policy")
        if insufficient:
            status = "insufficient_evidence"
            reasons.extend(insufficient)
        else:
            status = "eligible_for_owner_review"
            reasons.append("all_policy_checks_passed_owner_review_required")

    unsigned = ConsolidationDecision(
        status=status,
        reasons=tuple(reasons),
        candidate_sha256=candidate.candidate_sha256,
        policy_sha256=policy.sha256,
        rollback_to_sha256=candidate.previous_snapshot_sha256,
        signature="",
    )
    signature = _mac(b"star.memory-consolidation.decision.v1", unsigned.payload(), key)
    return replace(unsigned, signature=signature)


def verify_decision(decision: ConsolidationDecision, key: bytes) -> bool:
    """Verify the trusted host's decision receipt."""
    expected = _mac(b"star.memory-consolidation.decision.v1", decision.payload(), key)
    return hmac.compare_digest(expected, decision.signature)
