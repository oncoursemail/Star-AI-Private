"""Bounded resource admission for STAR's interactive and background workloads.

This is a pure host-side policy component. It does not launch, cancel, or
prioritize operating-system processes; call models; control audio, games, OBS,
or VTube Studio; inspect hardware; or grant tool permissions.

A Windows host adapter supplies a calibrated resource budget and fresh health
signal. The controller protects a reserved resource slice for latency-sensitive
work and defers noncritical work when that health signal is stale or degraded.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
import secrets
from threading import RLock

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_MAX_RESOURCE = 1_000_000_000
_MAX_CLOCK_MS = 10**15

class WorkloadLane(str, Enum):
    """Work classes ordered by user-visible latency sensitivity."""

    AUDIO = "audio"
    GAME_CONTROL = "game_control"
    VOICE = "voice"
    AVATAR = "avatar"
    CHAT = "chat"
    INTERACTIVE = "interactive"
    RESEARCH = "research"
    LEARNING = "learning"
    ASSET_GENERATION = "asset_generation"


_LANE_PRIORITY = {
    WorkloadLane.AUDIO: 0,
    WorkloadLane.GAME_CONTROL: 0,
    WorkloadLane.VOICE: 1,
    WorkloadLane.AVATAR: 1,
    WorkloadLane.CHAT: 2,
    WorkloadLane.INTERACTIVE: 3,
    WorkloadLane.RESEARCH: 4,
    WorkloadLane.LEARNING: 4,
    WorkloadLane.ASSET_GENERATION: 4,
}
_PROTECTED_LANES = frozenset({
    WorkloadLane.AUDIO,
    WorkloadLane.GAME_CONTROL,
    WorkloadLane.VOICE,
    WorkloadLane.AVATAR,
    WorkloadLane.CHAT,
})
_REALTIME_RESERVE_LANES = frozenset({
    WorkloadLane.AUDIO,
    WorkloadLane.GAME_CONTROL,
    WorkloadLane.VOICE,
    WorkloadLane.AVATAR,
})
_STREAM_DEFERRED_LANES = frozenset({
    WorkloadLane.INTERACTIVE,
    WorkloadLane.RESEARCH,
    WorkloadLane.LEARNING,
    WorkloadLane.ASSET_GENERATION,
})


def _clock(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_CLOCK_MS:
        raise ValueError(f"{label} must be a bounded monotonic millisecond value")
    return value


def _resource(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_RESOURCE:
        raise ValueError(f"{label} must be a bounded nonnegative integer")
    return value


@dataclass(frozen=True)
class ResourceVector:
    """Abstract STAR allocation units; values are not OS measurements."""

    cpu_millicores: int = 0
    ram_mb: int = 0
    vram_mb: int = 0

    def __post_init__(self) -> None:
        _resource(self.cpu_millicores, "cpu_millicores")
        _resource(self.ram_mb, "ram_mb")
        _resource(self.vram_mb, "vram_mb")


@dataclass(frozen=True)
class ResourceBudget:
    """Static per-session STAR budget and hard real-time reserve.

    The hard reserve is available only to audio, game-control, voice, and
    avatar lanes. Chat remains eligible during a stream but uses unreserved
    capacity. Capacity is the maximum allocation the host is willing to assign
    after accounting for Windows, the game, OBS, drivers, and fixed work; it is
    not installed hardware capacity or instantaneous free memory.
    """

    capacity: ResourceVector
    realtime_reserve: ResourceVector = ResourceVector()

    def __post_init__(self) -> None:
        if not isinstance(self.capacity, ResourceVector):
            raise TypeError("capacity must be ResourceVector")
        if not isinstance(self.realtime_reserve, ResourceVector):
            raise TypeError("realtime_reserve must be ResourceVector")
        if not _fits(self.capacity, self.realtime_reserve):
            raise ValueError("real-time reserve cannot exceed STAR capacity")


@dataclass(frozen=True)
class HostHealth:
    """Fresh host-computed signal; raw telemetry never enters this policy."""

    observed_monotonic_ms: int
    realtime_degraded: bool
    streaming: bool = False
    gaming: bool = False

    def __post_init__(self) -> None:
        _clock(self.observed_monotonic_ms, "observed_monotonic_ms")
        if type(self.realtime_degraded) is not bool:
            raise ValueError("realtime_degraded must be an explicit boolean")
        if type(self.streaming) is not bool or type(self.gaming) is not bool:
            raise ValueError("streaming and gaming must be explicit booleans")


@dataclass(frozen=True)
class WorkloadRequest:
    """Content-free request for a bounded resource lease."""

    request_id: str
    lane: WorkloadLane
    resources: ResourceVector
    enqueued_monotonic_ms: int
    deadline_monotonic_ms: int | None = None

    def __post_init__(self) -> None:
        if type(self.request_id) is not str or _ID.fullmatch(self.request_id) is None:
            raise ValueError("request_id must be a bounded opaque identifier")
        if not isinstance(self.lane, WorkloadLane):
            raise ValueError("lane must be a WorkloadLane")
        if not isinstance(self.resources, ResourceVector):
            raise TypeError("resources must be ResourceVector")
        _clock(self.enqueued_monotonic_ms, "enqueued_monotonic_ms")
        if self.deadline_monotonic_ms is not None:
            deadline = _clock(self.deadline_monotonic_ms, "deadline_monotonic_ms")
            if deadline <= self.enqueued_monotonic_ms:
                raise ValueError("deadline must follow enqueue time")


@dataclass(frozen=True)
class WorkloadLease:
    """Host-local allocation lease; its ID is not an authorization credential."""

    lease_id: str
    request_id: str
    lane: WorkloadLane
    resources: ResourceVector
    granted_monotonic_ms: int
    expires_monotonic_ms: int


@dataclass(frozen=True)
class Submission:
    status: str
    request_id: str
    lease: WorkloadLease | None = None
    reason: str | None = None


@dataclass(frozen=True)
class AdmissionSnapshot:
    """Aggregate diagnostics only; deliberately contains no request/lease IDs."""

    queued: int
    active: int
    queued_by_lane: tuple[tuple[str, int], ...]
    active_by_lane: tuple[tuple[str, int], ...]
    used: ResourceVector
    available: ResourceVector
    realtime_reserve_remaining: ResourceVector
    health_fresh: bool
    realtime_degraded: bool
    streaming: bool | None
    gaming: bool | None
    deferred_for_health: int
    deferred_for_active_session: int
    expired_queued: int
    expired_active_leases: int


def _fits(available: ResourceVector, requested: ResourceVector) -> bool:
    return (
        requested.cpu_millicores <= available.cpu_millicores
        and requested.ram_mb <= available.ram_mb
        and requested.vram_mb <= available.vram_mb
    )


def _add(left: ResourceVector, right: ResourceVector) -> ResourceVector:
    return ResourceVector(
        left.cpu_millicores + right.cpu_millicores,
        left.ram_mb + right.ram_mb,
        left.vram_mb + right.vram_mb,
    )


def _subtract(left: ResourceVector, right: ResourceVector) -> ResourceVector:
    """Saturating subtraction for remaining capacity/reserve calculations."""
    return ResourceVector(
        max(0, left.cpu_millicores - right.cpu_millicores),
        max(0, left.ram_mb - right.ram_mb),
        max(0, left.vram_mb - right.vram_mb),
    )


def _sum_resources(leases: list[WorkloadLease]) -> ResourceVector:
    total = ResourceVector()
    for lease in leases:
        total = _add(total, lease.resources)
    return total


class WorkloadAdmissionController:
    """Deterministic, bounded admission; the host owns all actual execution.

    The controller never preempts an active lease. Only audio, game-control,
    voice, and avatar lanes can consume the hard real-time reserve. Chat remains
    eligible under degraded health but must fit outside that reserve. The host
    must size the reserve for its worst expected voice/game burst and retain a
    separate cancellation mechanism for long-running workers.
    """

    def __init__(
        self,
        budget: ResourceBudget,
        *,
        max_queue: int = 256,
        max_active: int = 32,
        lease_ttl_ms: int = 60_000,
        health_max_age_ms: int = 5_000,
        max_seen_requests: int = 100_000,
    ) -> None:
        if not isinstance(budget, ResourceBudget):
            raise TypeError("budget must be ResourceBudget")
        if type(max_queue) is not int or not 1 <= max_queue <= 4_096:
            raise ValueError("max_queue must be in 1..4096")
        if type(max_active) is not int or not 1 <= max_active <= 256:
            raise ValueError("max_active must be in 1..256")
        if type(lease_ttl_ms) is not int or not 100 <= lease_ttl_ms <= 3_600_000:
            raise ValueError("lease_ttl_ms must be in 100..3600000")
        if type(health_max_age_ms) is not int or not 100 <= health_max_age_ms <= 60_000:
            raise ValueError("health_max_age_ms must be in 100..60000")
        if type(max_seen_requests) is not int or not 1 <= max_seen_requests <= 100_000:
            raise ValueError("max_seen_requests must be in 1..100000")
        self._budget = budget
        self._max_queue = max_queue
        self._max_active = max_active
        self._lease_ttl_ms = lease_ttl_ms
        self._health_max_age_ms = health_max_age_ms
        self._max_seen_requests = max_seen_requests
        self._lock = RLock()
        self._queued: dict[str, tuple[int, WorkloadRequest]] = {}
        self._active: dict[str, WorkloadLease] = {}
        self._active_by_request: dict[str, str] = {}
        self._seen_request_ids: set[str] = set()
        self._sequence = 0
        self._last_clock_ms: int | None = None
        self._expired_queued = 0

    def _advance_clock(self, now_ms: int) -> int:
        now = _clock(now_ms, "now_ms")
        if self._last_clock_ms is not None and now < self._last_clock_ms:
            raise ValueError("monotonic clock moved backwards")
        self._last_clock_ms = now
        return now

    def _expire(self, now_ms: int) -> None:
        for request_id, (_, request) in list(self._queued.items()):
            deadline = request.deadline_monotonic_ms
            if deadline is not None and now_ms >= deadline:
                del self._queued[request_id]
                self._expired_queued += 1

    def submit(self, request: WorkloadRequest) -> Submission:
        """Queue one request. Duplicate IDs never create duplicate work."""
        if not isinstance(request, WorkloadRequest):
            raise TypeError("request must be WorkloadRequest")
        with self._lock:
            active_id = self._active_by_request.get(request.request_id)
            if active_id is not None:
                return Submission("active", request.request_id, self._active[active_id])
            if request.request_id in self._queued:
                return Submission("queued", request.request_id)
            if request.request_id in self._seen_request_ids:
                return Submission("duplicate", request.request_id, reason="request ID was already used")
            if len(self._queued) >= self._max_queue:
                return Submission("rejected", request.request_id, reason="queue is full")
            if len(self._seen_request_ids) >= self._max_seen_requests:
                raise RuntimeError("request replay ledger is full; start a new controller")
            self._seen_request_ids.add(request.request_id)
            self._sequence += 1
            self._queued[request.request_id] = (self._sequence, request)
            return Submission("queued", request.request_id)

    def cancel_queued(self, request_id: str) -> bool:
        """Remove a queued request. Active work is never silently preempted."""
        if type(request_id) is not str or _ID.fullmatch(request_id) is None:
            raise ValueError("request_id must be a bounded opaque identifier")
        with self._lock:
            return self._queued.pop(request_id, None) is not None

    def _health_state(
        self, now_ms: int, health: HostHealth | None
    ) -> tuple[bool, bool, bool | None, bool | None]:
        if health is not None and not isinstance(health, HostHealth):
            raise TypeError("health must be HostHealth or None")
        fresh = bool(
            health is not None
            and 0 <= now_ms - health.observed_monotonic_ms <= self._health_max_age_ms
        )
        degraded = not fresh or (health.realtime_degraded if health is not None else True)
        if not fresh or health is None:
            return False, True, None, None
        return True, degraded, health.streaming, health.gaming

    def schedule(
        self,
        now_monotonic_ms: int,
        *,
        health: HostHealth | None,
        max_admissions: int = 8,
    ) -> tuple[WorkloadLease, ...]:
        """Admit highest-priority fitting requests using a fresh host health signal.

        Missing, future-dated, stale, or degraded health blocks all non-protected
        lanes. A fresh healthy signal is required before background work resumes.
        """
        if type(max_admissions) is not int or not 1 <= max_admissions <= 256:
            raise ValueError("max_admissions must be in 1..256")
        with self._lock:
            now = self._advance_clock(now_monotonic_ms)
            self._expire(now)
            _, degraded, streaming, gaming = self._health_state(now, health)
            if len(self._active) >= self._max_active or not self._queued:
                return ()
            active_leases = list(self._active.values())
            used = _sum_resources(active_leases)
            available = _subtract(self._budget.capacity, used)
            reserve_used = _sum_resources(
                [lease for lease in active_leases if lease.lane in _REALTIME_RESERVE_LANES]
            )
            reserve_remaining = _subtract(self._budget.realtime_reserve, reserve_used)
            ordered = sorted(
                self._queued.items(),
                key=lambda item: (
                    _LANE_PRIORITY[item[1][1].lane],
                    item[1][1].enqueued_monotonic_ms,
                    item[1][0],
                ),
            )
            admitted: list[WorkloadLease] = []
            blocked_priority: int | None = None
            for request_id, (_, request) in ordered:
                if len(admitted) >= max_admissions or len(self._active) >= self._max_active:
                    break
                priority = _LANE_PRIORITY[request.lane]
                if blocked_priority is not None and priority > blocked_priority:
                    break
                if request.enqueued_monotonic_ms > now:
                    continue
                if degraded and request.lane not in _PROTECTED_LANES:
                    continue
                if (streaming or gaming) and request.lane in _STREAM_DEFERRED_LANES:
                    blocked_priority = priority
                    continue
                allocatable = (
                    available
                    if request.lane in _REALTIME_RESERVE_LANES
                    else _subtract(available, reserve_remaining)
                )
                if not _fits(allocatable, request.resources):
                    blocked_priority = priority
                    continue
                lease = WorkloadLease(
                    lease_id=secrets.token_hex(16),
                    request_id=request_id,
                    lane=request.lane,
                    resources=request.resources,
                    granted_monotonic_ms=now,
                    expires_monotonic_ms=now + self._lease_ttl_ms,
                )
                del self._queued[request_id]
                self._active[lease.lease_id] = lease
                self._active_by_request[request_id] = lease.lease_id
                available = _subtract(available, request.resources)
                if request.lane in _REALTIME_RESERVE_LANES:
                    reserve_used = _add(reserve_used, request.resources)
                    reserve_remaining = _subtract(self._budget.realtime_reserve, reserve_used)
                admitted.append(lease)
            return tuple(admitted)

    def release(
        self,
        lease_id: str,
        now_monotonic_ms: int,
        *,
        host_confirmed_stopped: bool,
    ) -> bool:
        """Release capacity only after the host confirms the worker has stopped.

        Lease expiry is diagnostic, not proof of process termination. An
        expired lease continues to reserve capacity until this host assertion.
        """
        if type(lease_id) is not str or re.fullmatch(r"[0-9a-f]{32}", lease_id) is None:
            raise ValueError("lease_id must be a host-issued opaque lease ID")
        if host_confirmed_stopped is not True:
            raise PermissionError("host must confirm the worker has stopped before releasing capacity")
        with self._lock:
            now = self._advance_clock(now_monotonic_ms)
            self._expire(now)
            lease = self._active.pop(lease_id, None)
            if lease is None:
                return False
            self._active_by_request.pop(lease.request_id, None)
            return True

    def snapshot(
        self,
        now_monotonic_ms: int,
        *,
        health: HostHealth | None,
    ) -> AdmissionSnapshot:
        """Return bounded aggregate state without exposing opaque identifiers."""
        with self._lock:
            now = self._advance_clock(now_monotonic_ms)
            self._expire(now)
            fresh, degraded, streaming, gaming = self._health_state(now, health)
            active = list(self._active.values())
            used = _sum_resources(active)
            available = _subtract(self._budget.capacity, used)
            reserve_used = _sum_resources(
                [lease for lease in active if lease.lane in _REALTIME_RESERVE_LANES]
            )
            reserve_remaining = _subtract(self._budget.realtime_reserve, reserve_used)
            queued_counts = tuple(
                (lane.value, sum(1 for _, request in self._queued.values() if request.lane == lane))
                for lane in WorkloadLane
            )
            active_counts = tuple(
                (lane.value, sum(1 for lease in active if lease.lane == lane))
                for lane in WorkloadLane
            )
            deferred = sum(
                1 for _, request in self._queued.values()
                if degraded and request.lane not in _PROTECTED_LANES
            )
            deferred_active = sum(
                1 for _, request in self._queued.values()
                if (streaming or gaming) and request.lane in _STREAM_DEFERRED_LANES
            )
            return AdmissionSnapshot(
                queued=len(self._queued),
                active=len(active),
                queued_by_lane=queued_counts,
                active_by_lane=active_counts,
                used=used,
                available=available,
                realtime_reserve_remaining=reserve_remaining,
                health_fresh=fresh,
                realtime_degraded=degraded,
                streaming=streaming,
                gaming=gaming,
                deferred_for_health=deferred,
                deferred_for_active_session=deferred_active,
                expired_queued=self._expired_queued,
                expired_active_leases=sum(1 for lease in active if now >= lease.expires_monotonic_ms),
            )
