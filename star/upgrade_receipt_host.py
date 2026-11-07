"""Host-sealed, pre-registered evidence envelopes for Star Core Forge upgrades.

This *verifier* sits in front of upgrade_evidence_gate.compare_upgrade. A trusted
offline coordinator must issue the precommit BEFORE trials; a separate outcome
observer signs each real measurement AFTER inspecting independently retained
evidence. Do not import signing keys into the LLM, plugins, chat, or stream.

HMAC authenticates a key holder and the exact fields it signed. It does NOT prove
measurements are true, that a trial ran, or that a manifest was genuinely issued
before the experiments. Independent host processes and a durable run/nonce
registry are required for those properties. Nothing here can change a model,
operate Roblox, control a stream, or authorize deployment.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import hmac
import json
import math
import re
from typing import Sequence

from star.upgrade_evidence_gate import (
    CATEGORIES, MAX_CASES, UpgradeComparison, UpgradeObservation,
    UpgradePlan, compare_upgrade,
)

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_PLAN_DOMAIN = b"star.upgrade.plan.v1\x00"
_PRECOMMIT_DOMAIN = b"star.upgrade.precommit.v1\x00"
_TRIAL_DOMAIN = b"star.upgrade.observation.v1\x00"
_MAX_WINDOW_S = 7 * 86400


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _digest(domain: bytes, value: object) -> str:
    return hashlib.sha256(domain + _json_bytes(value)).hexdigest()


def _signature(domain: bytes, payload: object, key: bytes) -> str:
    return hmac.new(key, domain + _json_bytes(payload), hashlib.sha256).hexdigest()


def _secret(key: bytes) -> bytes:
    if type(key) is not bytes or not 32 <= len(key) <= 4096:
        raise ValueError("host keys must be 32..4096 random bytes")
    return key


def _timestamp(value: object, label: str) -> int:
    if type(value) is not int or not 1 <= value <= 10**11:
        raise ValueError(f"{label} must be an integer Unix timestamp")
    return value


def _hash(value: object, label: str) -> str:
    if type(value) is not str or not _HEX.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def plan_digest(plan: UpgradePlan) -> str:
    """Reproducible canonical digest of all task and model/scorer identities."""
    if type(plan) is not UpgradePlan:
        raise TypeError("expected an UpgradePlan")
    return _digest(_PLAN_DOMAIN, asdict(plan))


@dataclass(frozen=True)
class Precommit:
    experiment_id: str
    nonce: str
    plan_sha256: str
    issued_unix_s: int
    expires_unix_s: int
    # Ordered by the UpgradePlan's case list; AB/BA is fixed before any trials.
    case_orders: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if type(self.experiment_id) is not str or not _NAME.fullmatch(self.experiment_id):
            raise ValueError("bounded experiment_id required")
        if type(self.nonce) is not str or not _NONCE.fullmatch(self.nonce):
            raise ValueError("nonce must be 16 random bytes encoded as lowercase hex")
        _hash(self.plan_sha256, "plan_sha256")
        start = _timestamp(self.issued_unix_s, "issued_unix_s")
        end = _timestamp(self.expires_unix_s, "expires_unix_s")
        if not 0 < end - start <= _MAX_WINDOW_S:
            raise ValueError("precommit window must be at most seven days")
        if (type(self.case_orders) is not tuple
                or not 1 <= len(self.case_orders) <= MAX_CASES):
            raise ValueError("bounded immutable case order required")
        for pair in self.case_orders:
            if (type(pair) is not tuple or len(pair) != 2
                    or type(pair[0]) is not str or not _NAME.fullmatch(pair[0])
                    or type(pair[1]) is not str or pair[1] not in ("AB", "BA")):
                raise ValueError("invalid precommitted case/order pair")

    @property
    def digest(self) -> str:
        return _digest(_PRECOMMIT_DOMAIN, asdict(self))


@dataclass(frozen=True)
class SignedPrecommit:
    precommit: Precommit
    signature: str

    def __post_init__(self) -> None:
        if type(self.precommit) is not Precommit:
            raise TypeError("expected Precommit")
        _hash(self.signature, "precommit signature")


@dataclass(frozen=True)
class SignedObservation:
    observation: UpgradeObservation
    precommit_sha256: str
    evidence_sha256: str
    observed_unix_s: int
    signature: str

    def __post_init__(self) -> None:
        if type(self.observation) is not UpgradeObservation:
            raise TypeError("expected UpgradeObservation")
        _hash(self.precommit_sha256, "precommit_sha256")
        _hash(self.evidence_sha256, "evidence_sha256")
        _timestamp(self.observed_unix_s, "observed_unix_s")
        _hash(self.signature, "observation signature")

    def signed_payload(self) -> dict:
        return {
            "observation": asdict(self.observation),
            "precommit_sha256": self.precommit_sha256,
            "evidence_sha256": self.evidence_sha256,
            "observed_unix_s": self.observed_unix_s,
        }


@dataclass(frozen=True)
class SealedUpgradeReview:
    verdict: str  # eligible_for_owner_review | regressed | inconclusive
    reason: str
    verified_observations: int
    comparison: UpgradeComparison | None
    authorized_to_deploy: bool = False


def _schedule_reason(plan: UpgradePlan, precommit: Precommit) -> str | None:
    if not plan.heldout or not plan.preregistered:
        return "independent_holdout_precommit_not_declared"
    if precommit.plan_sha256 != plan_digest(plan):
        return "plan_digest_mismatch"
    if len(precommit.case_orders) != len(plan.cases):
        return "case_schedule_incomplete"
    case_ids = [case.case_id for case in plan.cases]
    ordered_ids = [item[0] for item in precommit.case_orders]
    if ordered_ids != case_ids:
        return "case_schedule_changed"
    for category in CATEGORIES:
        orders = [
            precommit.case_orders[i][1]
            for i, case in enumerate(plan.cases) if case.category == category
        ]
        if not orders:
            continue
        ab = orders.count("AB")
        if ab < math.ceil(0.30 * len(orders)) or ab > math.floor(0.70 * len(orders)):
            return "unbalanced_precommitted_order"
    return None


def sign_precommit(precommit: Precommit, *, coordinator_key: bytes) -> SignedPrecommit:
    """TRUSTED COORDINATOR ONLY: perform before any experimental observations.

    Caller must create an unpredictable fresh nonce and record it in an
    append-only host ledger. The signature cannot attest to wall-clock truth.
    """
    if type(precommit) is not Precommit:
        raise TypeError("expected Precommit")
    return SignedPrecommit(
        precommit,
        _signature(_PRECOMMIT_DOMAIN, asdict(precommit), _secret(coordinator_key)),
    )


def sign_observation(
    observation: UpgradeObservation, *,
    precommit_sha256: str, evidence_sha256: str,
    observed_unix_s: int, observer_key: bytes,
) -> SignedObservation:
    """TRUSTED OUTCOME OBSERVER ONLY; not a model-facing capability.

    The observer must independently score the real trial and retain the
    underlying evidence outside this module. Never sign LLM supplied results.
    """
    record = SignedObservation(
        observation, precommit_sha256, evidence_sha256, observed_unix_s,
        "0" * 64,
    )
    return replace(record, signature=_signature(
        _TRIAL_DOMAIN, record.signed_payload(), _secret(observer_key),
    ))


def review_sealed_upgrade(
    plan: UpgradePlan,
    sealed: SignedPrecommit,
    rows: Sequence[SignedObservation],
    *, coordinator_key: bytes, observer_key: bytes,
    now_unix_s: int,
) -> SealedUpgradeReview:
    """Verify every envelope, then run Star's existing multi-domain quality gate.

    Fail closed: even one invalid, repeated, out-of-window, or unauthenticated
    receipt makes the ENTIRE experiment inconclusive. Missing signed pairs
    remain inconclusive under the underlying evaluator. No deployment occurs.
    """
    if type(plan) is not UpgradePlan or type(sealed) is not SignedPrecommit:
        raise TypeError("expected UpgradePlan and SignedPrecommit")
    if type(rows) not in (tuple, list) or len(rows) > 2 * MAX_CASES:
        raise ValueError("bounded signed-observation sequence required")
    now = _timestamp(now_unix_s, "now_unix_s")
    coordinator = _secret(coordinator_key)
    observer = _secret(observer_key)
    if hmac.compare_digest(coordinator, observer):
        raise ValueError("coordinator and outcome observer must have independent keys")

    def fail(reason: str, count: int = 0) -> SealedUpgradeReview:
        return SealedUpgradeReview("inconclusive", reason, count, None)

    precommit = sealed.precommit
    expected = _signature(_PRECOMMIT_DOMAIN, asdict(precommit), coordinator)
    if not hmac.compare_digest(expected, sealed.signature):
        return fail("precommit_authentication_failed")
    reason = _schedule_reason(plan, precommit)
    if reason is not None:
        return fail(reason)
    if now < precommit.issued_unix_s or now > precommit.expires_unix_s + 86400:
        return fail("precommit_expired_or_not_yet_valid")

    schedule = dict(precommit.case_orders)
    seen_pairs: set[tuple[str, str]] = set()
    seen_evidence: set[str] = set()
    authenticated: list[UpgradeObservation] = []
    for record in rows:
        if type(record) is not SignedObservation:
            return fail("unsigned_or_malformed_observation", len(authenticated))
        row = record.observation
        if record.precommit_sha256 != precommit.digest:
            return fail("observation_cross_experiment_replay", len(authenticated))
        if (record.observed_unix_s <= precommit.issued_unix_s
                or record.observed_unix_s > precommit.expires_unix_s
                or record.observed_unix_s > now):
            return fail("observation_outside_frozen_run_window", len(authenticated))
        if schedule.get(row.case_id) != row.order:
            return fail("unregistered_case_or_changed_order", len(authenticated))
        pair = (row.case_id, row.variant)
        if pair in seen_pairs or record.evidence_sha256 in seen_evidence:
            return fail("duplicate_trial_or_evidence_reuse", len(authenticated))
        expected = _signature(_TRIAL_DOMAIN, record.signed_payload(), observer)
        if not hmac.compare_digest(expected, record.signature):
            return fail("observation_authentication_failed", len(authenticated))
        seen_pairs.add(pair)
        seen_evidence.add(record.evidence_sha256)
        authenticated.append(row)

    try:
        report = compare_upgrade(plan, authenticated)
    except (TypeError, ValueError):
        return fail("invalid_signed_measurements", len(authenticated))
    return SealedUpgradeReview(
        report.verdict, report.reason, len(authenticated), report,
    )


__all__ = [
    "Precommit", "SignedPrecommit", "SignedObservation", "SealedUpgradeReview",
    "plan_digest", "sign_precommit", "sign_observation", "review_sealed_upgrade",
]
