"""Host-attested inspection coverage before modifying a Roblox Studio scene.

This is an OFF-by-default, read-only evaluation aid. The trusted Windows Studio
host independently enumerates the objects an edit will affect, signs complete
observations at a fixed scene revision, and asks whether ALL requested objects
were actually inspected. A language model cannot use a self-described read to
satisfy this gate. No Studio writes, tools, network calls, permissions, or
gameplay actions are provided by this module.

HMAC authenticates the host that made an observation; it cannot establish
that the host enumerated every dependency or that the observation was truthful.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import re
import secrets
from threading import RLock

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_SEGMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_ .-]{0,63}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ROOTS = frozenset({
    "Workspace", "ReplicatedStorage", "ServerStorage", "StarterGui",
    "StarterPlayer", "ServerScriptService", "Lighting", "SoundService",
})
_CLASSES = frozenset({
    "Script", "LocalScript", "ModuleScript", "Model", "Folder",
    "Part", "MeshPart", "UnionOperation", "SpawnLocation", "Attachment",
    "ScreenGui", "Frame", "TextLabel", "ImageLabel", "TextButton",
    "ImageButton", "Sound", "ParticleEmitter", "Beam",
})
MAX_CLOCK_MS = 10**13


def _time(value: object) -> int:
    if type(value) is not int or not 0 <= value <= MAX_CLOCK_MS:
        raise ValueError("expected bounded, nonnegative monotonic milliseconds")
    return value


def _path(value: object) -> tuple[str, ...]:
    if (type(value) is not tuple or not 2 <= len(value) <= 9
            or value[0] not in _ROOTS
            or any(type(seg) is not str or not _SEGMENT.fullmatch(seg)
                   for seg in value[1:])):
        raise ValueError("invalid bounded Roblox instance path")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or not _HEX.fullmatch(value):
        raise ValueError(f"{name} must be lowercase SHA-256")
    return value


@dataclass(frozen=True)
class EditFootprint:
    """Host-reviewed exact edit, targets and read dependencies; no raw source."""

    project_id: str
    studio_session: str
    scene_revision: int
    change_sha256: str
    targets: tuple[tuple[str, ...], ...]
    dependencies: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        for name in ("project_id", "studio_session"):
            value = getattr(self, name)
            if type(value) is not str or not _ID.fullmatch(value):
                raise ValueError(f"invalid {name}")
        if type(self.scene_revision) is not int or not 0 <= self.scene_revision <= 2**63 - 1:
            raise ValueError("invalid scene revision")
        _digest(self.change_sha256, "change_sha256")
        if type(self.targets) is not tuple or type(self.dependencies) is not tuple:
            raise ValueError("footprint paths must be exact tuples")
        if not 1 <= len(self.targets) <= 32 or len(self.dependencies) > 32:
            raise ValueError("footprint needs 1..32 targets and at most 32 dependencies")
        paths = self.targets + self.dependencies
        for path in paths:
            _path(path)
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate or overlapping footprint paths")


@dataclass(frozen=True)
class StudioReadReceipt:
    """Host-signature-bound receipt for ONE unambiguous, complete object read."""

    plan_nonce: str
    project_id: str
    studio_session: str
    scene_revision: int
    path: tuple[str, ...]
    class_name: str
    observation_sha256: str
    captured_ms: int
    complete: bool
    unique_path: bool
    mac: str

    def __post_init__(self) -> None:
        if type(self.plan_nonce) is not str or not re.fullmatch(r"[0-9a-f]{32}", self.plan_nonce):
            raise ValueError("invalid plan nonce")
        for name in ("project_id", "studio_session"):
            value = getattr(self, name)
            if type(value) is not str or not _ID.fullmatch(value):
                raise ValueError(f"invalid {name}")
        if type(self.scene_revision) is not int or not 0 <= self.scene_revision <= 2**63 - 1:
            raise ValueError("invalid scene revision")
        _path(self.path)
        if type(self.class_name) is not str or self.class_name not in _CLASSES:
            raise ValueError("unsupported inspected class")
        _digest(self.observation_sha256, "observation_sha256")
        _time(self.captured_ms)
        if type(self.complete) is not bool or type(self.unique_path) is not bool:
            raise ValueError("observation completeness flags must be booleans")
        _digest(self.mac, "receipt mac")

    def signed_bytes(self) -> bytes:
        """Canonical versioned payload. mac is excluded deliberately."""
        return json.dumps([
            "star.studio.inspection.v1", self.plan_nonce,
            self.project_id, self.studio_session, self.scene_revision,
            list(self.path), self.class_name, self.observation_sha256,
            self.captured_ms, self.complete, self.unique_path,
        ], ensure_ascii=True, separators=(",", ":")).encode("ascii")


@dataclass(frozen=True)
class InspectionReview:
    status: str  # disabled | unplanned | incomplete | stale | invalid | ready_for_review
    inspected: int
    required: int
    missing_paths: tuple[tuple[str, ...], ...]
    change_sha256: str | None
    authorized_to_mutate: bool = False


class StudioInspectionCoverageGate:
    """Require exact host-signed reads of every node in a bounded edit footprint.

    The trusted host supplies a secret never shared with a model, chat, or
    Studio place. It is responsible for reporting a revision change before
    another plan is considered. This gate is not itself an enforcement point;
    a mutating Studio host must separately require a fresh ready review.
    """

    def __init__(self, *, host_key: bytes, freshness_ms: int = 30_000) -> None:
        if type(host_key) is not bytes or len(host_key) < 32:
            raise ValueError("host-only HMAC key must be 32+ bytes")
        if type(freshness_ms) is not int or not 1000 <= freshness_ms <= 120_000:
            raise ValueError("freshness must be 1..120 seconds")
        self._key = host_key
        self._freshness = freshness_ms
        self._lock = RLock()
        self._enabled = False
        self._plan: EditFootprint | None = None
        self._nonce: str | None = None
        self._registered_ms: int | None = None
        self._last_clock: int | None = None
        self._reads: dict[tuple[str, ...], StudioReadReceipt] = {}
        self._invalid = False
        self._counts = {"accepted": 0, "rejected": 0, "revisions": 0}

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner approval required")
        with self._lock:
            self._clear()
            self._enabled = True

    def _clear(self) -> None:
        self._plan = None
        self._nonce = None
        self._registered_ms = None
        self._last_clock = None
        self._reads.clear()
        self._invalid = False

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._clear()

    def _advance(self, now_ms: int) -> int:
        now = _time(now_ms)
        if self._last_clock is not None and now < self._last_clock:
            self._invalid = True
            raise ValueError("inspection host clock reversed")
        self._last_clock = now
        return now

    def register(self, footprint: EditFootprint, *, now_ms: int,
                 host_approved: bool = False) -> str:
        """Register a host-derived edit footprint. Returns a nonsecret plan ID."""
        if not isinstance(footprint, EditFootprint):
            raise TypeError("expected validated edit footprint")
        with self._lock:
            if not self._enabled or host_approved is not True:
                raise PermissionError("host registration requires enabled owner approval")
            self._advance(now_ms)
            self._plan = footprint
            self._nonce = secrets.token_hex(16)
            self._registered_ms = now_ms
            self._reads.clear()
            self._invalid = False
            return self._nonce

    def invalidate_revision(self, *, now_ms: int) -> None:
        """Host must invoke after ANY Studio mutation, reload or reconnect."""
        with self._lock:
            self._advance(now_ms)
            self._plan = None
            self._nonce = None
            self._registered_ms = None
            self._reads.clear()
            self._invalid = False
            self._counts["revisions"] += 1

    def accept(self, receipt: StudioReadReceipt, *, now_ms: int) -> bool:
        """Accept only one first-use matching host-HMAC receipt per path."""
        if not isinstance(receipt, StudioReadReceipt):
            raise TypeError("expected validated host receipt")
        with self._lock:
            now = self._advance(now_ms)
            plan = self._plan
            if (not self._enabled or self._invalid or plan is None
                    or self._registered_ms is None or self._nonce is None):
                self._counts["rejected"] += 1
                return False
            requested = set(plan.targets + plan.dependencies)
            valid = (
                receipt.plan_nonce == self._nonce
                and receipt.project_id == plan.project_id
                and receipt.studio_session == plan.studio_session
                and receipt.scene_revision == plan.scene_revision
                and receipt.path in requested
                and receipt.complete and receipt.unique_path
                and self._registered_ms <= receipt.captured_ms <= now
                and now - receipt.captured_ms <= self._freshness
                and receipt.path not in self._reads
                and hmac.compare_digest(
                    receipt.mac,
                    hmac.new(self._key, receipt.signed_bytes(), hashlib.sha256).hexdigest(),
                )
            )
            if not valid:
                self._counts["rejected"] += 1
                return False
            self._reads[receipt.path] = receipt
            self._counts["accepted"] += 1
            return True

    def review(self, *, now_ms: int) -> InspectionReview:
        with self._lock:
            now = self._advance(now_ms)
            plan = self._plan
            if not self._enabled:
                return InspectionReview("disabled", 0, 0, (), None)
            if plan is None:
                return InspectionReview("unplanned", 0, 0, (), None)
            requested = plan.targets + plan.dependencies
            if self._invalid:
                return InspectionReview("invalid", 0, len(requested), requested,
                                        plan.change_sha256)
            fresh = {
                path for path, receipt in self._reads.items()
                if receipt.captured_ms <= now
                and now - receipt.captured_ms <= self._freshness
            }
            missing = tuple(path for path in requested if path not in fresh)
            status = ("ready_for_review" if not missing else
                      "stale" if len(self._reads) == len(requested) else "incomplete")
            return InspectionReview(status, len(fresh), len(requested),
                                    missing, plan.change_sha256)

    def counters(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)
