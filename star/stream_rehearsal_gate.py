"""Cross-lane acceptance gate for STAR's private mixed-workload rehearsals.

Aggregates signed, content-free receipts from existing lane evaluators. It does
not run models, capture media, control OBS, send game input, publish, or change
routing. Only a trusted local host should hold the HMAC key and construct the
preregistered manifest.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import secrets
import hashlib
import hmac
import json
import math
import re
from types import MappingProxyType
from typing import Mapping

_LANES = frozenset({
    "inference", "speech", "turn_taking", "gameplay",
    "obs", "avatar", "memory", "creator",
})
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{7,64}$")
_NONCE = re.compile(r"^[0-9a-f]{64}$")

# Aggregate-only schemas. Raw prompts, transcripts, screenshots, audio,
# viewer IDs, chat text and file contents are intentionally not accepted.
_METRICS: dict[str, dict[str, tuple[float, float, bool]]] = {
    "inference": {
        "ttft_p50_ms": (0, 120_000, False),
        "ttft_p95_ms": (0, 120_000, False),
        "tpot_p50_ms": (0, 120_000, False),
        "completion_p95_ms": (0, 600_000, False),
        "quality_pass_rate": (0, 1, False),
    },
    "speech": {
        "first_audible_p50_ms": (0, 120_000, False),
        "first_audible_p95_ms": (0, 120_000, False),
        "audio_underruns": (0, 1_000_000, True),
        "false_interruption_rate": (0, 1, False),
        "grounding_pass_rate": (0, 1, False),
    },
    "turn_taking": {
        "addressee_accuracy": (0, 1, False),
        "silence_precision": (0, 1, False),
        "false_interruption_rate": (0, 1, False),
        "missed_turn_rate": (0, 1, False),
        "multiparty_comprehension": (0, 1, False),
    },
    "gameplay": {
        "fps_p10": (0, 500, False),
        "action_ack_p95_ms": (0, 120_000, False),
        "objective_success_rate": (0, 1, False),
        "scenario_diversity": (0, 100, False),
        "stale_action_rate": (0, 1, False),
    },
    "obs": {
        "dropped_frames_pct": (0, 100, False),
        "render_lag_p95_ms": (0, 120_000, False),
        "encode_lag_p95_ms": (0, 120_000, False),
        "reconnects": (0, 1_000_000, True),
    },
    "avatar": {
        "lip_sync_error_p95_ms": (0, 120_000, False),
        "avatar_frame_drop_pct": (0, 100, False),
        "tracking_lost_pct": (0, 100, False),
    },
    "memory": {
        "transfer_gain": (-1, 1, False),
        "interference_rate": (0, 1, False),
        "retention_rate": (0, 1, False),
        "retrieval_p95_ms": (0, 120_000, False),
    },
    "creator": {
        "build_pass_rate": (0, 1, False),
        "playtest_pass_rate": (0, 1, False),
        "regression_count": (0, 1_000_000, True),
        "visual_check_pass_rate": (0, 1, False),
    },
}


def _key_bytes(key: bytes) -> bytes:
    if type(key) is not bytes or not 32 <= len(key) <= 128:
        raise ValueError("trusted host signing key must be 32..128 bytes")
    return key


def _canonical(payload: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            dict(payload), sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("receipt payload is not canonical JSON") from exc


def _signature(payload: Mapping[str, object], key: bytes) -> str:
    return hmac.new(_key_bytes(key), _canonical(payload), hashlib.sha256).hexdigest()


def _check_id(value: object, name: str) -> None:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{name} must be a bounded opaque identifier")


def _check_digest(value: object, name: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _check_revision(value: object) -> None:
    if type(value) is not str or _REVISION.fullmatch(value) is None:
        raise ValueError("source_revision must be a lowercase Git-style revision")


@dataclass(frozen=True)
class RehearsalManifest:
    """Host-created preregistered policy; never accept it from model output."""

    campaign_id: str
    environment_sha256: str
    source_revision: str
    campaign_nonce: str = field(default_factory=lambda: secrets.token_hex(32))
    required_lanes: tuple[str, ...] = tuple(sorted(_LANES))
    min_duration_ms: int = 30 * 60 * 1000
    max_duration_ms: int = 90 * 60 * 1000
    min_samples_per_lane: int = 8
    edge_coverage_tolerance_ms: int = 5 * 60 * 1000

    def __post_init__(self) -> None:
        _check_id(self.campaign_id, "campaign_id")
        _check_digest(self.environment_sha256, "environment_sha256")
        _check_revision(self.source_revision)
        if type(self.campaign_nonce) is not str or _NONCE.fullmatch(self.campaign_nonce) is None:
            raise ValueError("campaign_nonce must be 32 bytes of lowercase hex")
        if type(self.required_lanes) is not tuple or not self.required_lanes:
            raise ValueError("required_lanes must be a nonempty tuple")
        if any(type(lane) is not str or lane not in _LANES for lane in self.required_lanes):
            raise ValueError("required_lanes contains an unknown lane")
        if len(self.required_lanes) > len(_LANES) or len(set(self.required_lanes)) != len(self.required_lanes):
            raise ValueError("required_lanes must be unique and bounded")
        for name, value, lo, hi in (
            ("min_duration_ms", self.min_duration_ms, 60_000, 4 * 60 * 60 * 1000),
            ("max_duration_ms", self.max_duration_ms, 60_000, 8 * 60 * 60 * 1000),
            ("min_samples_per_lane", self.min_samples_per_lane, 1, 1_000_000),
            ("edge_coverage_tolerance_ms", self.edge_coverage_tolerance_ms, 0, 30 * 60 * 1000),
        ):
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError(f"{name} is outside its safe range")
        if self.min_duration_ms > self.max_duration_ms:
            raise ValueError("minimum duration cannot exceed maximum duration")

    def payload(self) -> dict[str, object]:
        """Return the complete preregistered policy, including its one-use nonce."""
        return {
            "schema_version": 1,
            "campaign_id": self.campaign_id,
            "campaign_nonce": self.campaign_nonce,
            "environment_sha256": self.environment_sha256,
            "source_revision": self.source_revision,
            "required_lanes": list(self.required_lanes),
            "min_duration_ms": self.min_duration_ms,
            "max_duration_ms": self.max_duration_ms,
            "min_samples_per_lane": self.min_samples_per_lane,
            "edge_coverage_tolerance_ms": self.edge_coverage_tolerance_ms,
        }

    @property
    def sha256(self) -> str:
        """Digest that receipts must bind to, preventing policy substitution."""
        return hashlib.sha256(_canonical(self.payload())).hexdigest()


@dataclass(frozen=True)
class SessionReceipt:
    campaign_id: str
    session_id: str
    environment_sha256: str
    source_revision: str
    manifest_sha256: str
    started_ms: int
    ended_ms: int
    signature: str = ""

    def __post_init__(self) -> None:
        _check_id(self.campaign_id, "campaign_id")
        _check_id(self.session_id, "session_id")
        _check_digest(self.environment_sha256, "environment_sha256")
        _check_revision(self.source_revision)
        _check_digest(self.manifest_sha256, "manifest_sha256")
        if type(self.started_ms) is not int or type(self.ended_ms) is not int:
            raise ValueError("session clocks must be integer monotonic milliseconds")
        if not 0 <= self.started_ms < self.ended_ms <= 10**13:
            raise ValueError("invalid session time range")
        if type(self.signature) is not str or (self.signature and _SHA256.fullmatch(self.signature) is None):
            raise ValueError("invalid session signature")

    def payload(self) -> dict[str, object]:
        return {
            "campaign_id": self.campaign_id,
            "session_id": self.session_id,
            "environment_sha256": self.environment_sha256,
            "source_revision": self.source_revision,
            "manifest_sha256": self.manifest_sha256,
            "started_ms": self.started_ms,
            "ended_ms": self.ended_ms,
        }


@dataclass(frozen=True)
class LaneReceipt:
    campaign_id: str
    session_id: str
    environment_sha256: str
    source_revision: str
    manifest_sha256: str
    lane: str
    status: str
    sample_count: int
    window_start_ms: int
    window_end_ms: int
    evidence_sha256: str
    metrics: Mapping[str, int | float]
    signature: str = ""

    def __post_init__(self) -> None:
        _check_id(self.campaign_id, "campaign_id")
        _check_id(self.session_id, "session_id")
        _check_digest(self.environment_sha256, "environment_sha256")
        _check_revision(self.source_revision)
        _check_digest(self.manifest_sha256, "manifest_sha256")
        if type(self.lane) is not str or self.lane not in _LANES:
            raise ValueError("unknown evidence lane")
        if type(self.status) is not str or self.status not in {"pass", "fail", "inconclusive"}:
            raise ValueError("invalid lane status")
        if type(self.sample_count) is not int or not 1 <= self.sample_count <= 1_000_000:
            raise ValueError("sample_count is outside its safe range")
        if (type(self.window_start_ms) is not int or type(self.window_end_ms) is not int
                or not 0 <= self.window_start_ms < self.window_end_ms <= 10**13):
            raise ValueError("invalid lane window")
        _check_digest(self.evidence_sha256, "evidence_sha256")
        if not isinstance(self.metrics, Mapping):
            raise ValueError("metrics must be a mapping")
        schema = _METRICS[self.lane]
        if set(self.metrics) != set(schema):
            raise ValueError("lane metrics do not match the exact aggregate schema")
        clean: dict[str, int | float] = {}
        for name, (lo, hi, integer_only) in schema.items():
            value = self.metrics[name]
            if type(value) not in (int, float):
                raise ValueError(f"invalid aggregate metric: {name}")
            try:
                numeric = float(value)
            except (OverflowError, ValueError) as exc:
                raise ValueError(f"invalid aggregate metric: {name}") from exc
            if not math.isfinite(numeric) or not lo <= numeric <= hi:
                raise ValueError(f"invalid aggregate metric: {name}")
            if integer_only and type(value) is not int:
                raise ValueError(f"{name} must be an integer count")
            clean[name] = value
        object.__setattr__(self, "metrics", MappingProxyType(clean))
        if type(self.signature) is not str or (self.signature and _SHA256.fullmatch(self.signature) is None):
            raise ValueError("invalid lane signature")

    def payload(self) -> dict[str, object]:
        return {
            "campaign_id": self.campaign_id,
            "session_id": self.session_id,
            "environment_sha256": self.environment_sha256,
            "source_revision": self.source_revision,
            "manifest_sha256": self.manifest_sha256,
            "lane": self.lane,
            "status": self.status,
            "sample_count": self.sample_count,
            "window_start_ms": self.window_start_ms,
            "window_end_ms": self.window_end_ms,
            "evidence_sha256": self.evidence_sha256,
            "metrics": dict(self.metrics),
        }


def seal_session_receipt(receipt: SessionReceipt, key: bytes) -> SessionReceipt:
    """Sign a session receipt with a key held only by the trusted host."""
    return replace(receipt, signature=_signature(receipt.payload(), key))


def seal_lane_receipt(receipt: LaneReceipt, key: bytes) -> LaneReceipt:
    """Sign a lane receipt with a key held only by the trusted host."""
    return replace(receipt, signature=_signature(receipt.payload(), key))


@dataclass(frozen=True)
class RehearsalResult:
    status: str
    reasons: tuple[str, ...]
    lane_status: tuple[tuple[str, str], ...]
    duration_ms: int | None

    @property
    def eligible_for_owner_review(self) -> bool:
        return self.status == "eligible_for_owner_review"


def evaluate_rehearsal(
    manifest: RehearsalManifest,
    session: SessionReceipt,
    lane_receipts: tuple[LaneReceipt, ...] | list[LaneReceipt],
    *,
    signing_key: bytes,
) -> RehearsalResult:
    """Aggregate lane evidence; never promotes a model, memory policy or stream."""
    key = _key_bytes(signing_key)
    if type(manifest) is not RehearsalManifest or type(session) is not SessionReceipt:
        raise TypeError("trusted manifest and session receipt are required")
    if type(lane_receipts) not in (tuple, list) or len(lane_receipts) > len(_LANES):
        raise ValueError("lane_receipts must be a bounded list or tuple")

    reasons: list[str] = []
    statuses: dict[str, str] = {}
    duration = session.ended_ms - session.started_ms

    if not session.signature or not hmac.compare_digest(
        session.signature, _signature(session.payload(), key)
    ):
        reasons.append("session_receipt_signature_invalid")
    if (session.campaign_id != manifest.campaign_id
            or session.environment_sha256 != manifest.environment_sha256
            or session.source_revision != manifest.source_revision):
        reasons.append("session_manifest_binding_mismatch")
    if session.manifest_sha256 != manifest.sha256:
        reasons.append("session_manifest_digest_mismatch")
    if not manifest.min_duration_ms <= duration <= manifest.max_duration_ms:
        reasons.append("session_duration_outside_preregistered_range")

    seen: set[str] = set()
    for receipt in lane_receipts:
        if type(receipt) is not LaneReceipt:
            reasons.append("invalid_lane_receipt_type")
            continue
        lane = receipt.lane
        if lane in seen:
            reasons.append(f"duplicate_lane:{lane}")
            continue
        seen.add(lane)
        if lane not in manifest.required_lanes:
            reasons.append(f"unexpected_lane:{lane}")
            continue
        if not receipt.signature or not hmac.compare_digest(
            receipt.signature, _signature(receipt.payload(), key)
        ):
            reasons.append(f"invalid_signature:{lane}")
            statuses[lane] = "invalid"
            continue
        if (receipt.campaign_id != session.campaign_id
                or receipt.session_id != session.session_id
                or receipt.environment_sha256 != session.environment_sha256
                or receipt.source_revision != session.source_revision
                or receipt.manifest_sha256 != session.manifest_sha256):
            reasons.append(f"binding_mismatch:{lane}")
            statuses[lane] = "invalid"
            continue
        if receipt.status == "fail":
            statuses[lane] = "fail"
            reasons.append(f"lane_failed:{lane}")
            continue
        if receipt.status == "inconclusive":
            statuses[lane] = "inconclusive"
            reasons.append(f"lane_inconclusive:{lane}")
            continue
        if (receipt.window_start_ms < session.started_ms
                or receipt.window_end_ms > session.ended_ms
                or receipt.window_start_ms > session.started_ms + manifest.edge_coverage_tolerance_ms
                or receipt.window_end_ms < session.ended_ms - manifest.edge_coverage_tolerance_ms):
            reasons.append(f"lane_window_incomplete:{lane}")
            statuses[lane] = "inconclusive"
            continue
        if receipt.sample_count < manifest.min_samples_per_lane:
            reasons.append(f"insufficient_samples:{lane}")
            statuses[lane] = "inconclusive"
            continue
        statuses[lane] = "pass"

    missing = [lane for lane in manifest.required_lanes if lane not in seen]
    if missing:
        reasons.append("missing_lanes:" + ",".join(sorted(missing)))

    blocked_prefixes = (
        "session_receipt_signature_invalid", "session_manifest_binding_mismatch",
        "session_manifest_digest_mismatch",
        "invalid_signature:", "binding_mismatch:", "duplicate_lane:",
        "unexpected_lane:", "lane_failed:",
    )
    if any(reason.startswith(blocked_prefixes) for reason in reasons):
        status = "blocked"
    elif reasons:
        status = "inconclusive"
    else:
        status = "eligible_for_owner_review"

    return RehearsalResult(
        status=status,
        reasons=tuple(reasons),
        lane_status=tuple(sorted(statuses.items())),
        duration_ms=duration,
    )
