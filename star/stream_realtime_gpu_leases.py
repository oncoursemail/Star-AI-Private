"""Host-only optional GPU-work lease accounting for STAR's gaming VTuber.

Integrates the existing StreamAdmissionGate with bounded reservations. The
gate alone advises whether a background job is tolerable; it does not account
for several simultaneous model launches consuming the *same* free VRAM.

This controller does NOT start/stop processes or authorize inference, OBS,
game input, streaming, speech or self-training. The trusted local host must
enforce every revocation and explicitly confirm that a worker has stopped
before its claim is released. A telemetry sample is not hardware attestation.

Conservative accounting deliberately subtracts ALL outstanding claims from
fresh reported free VRAM, even if some workers have already allocated it.
This can underutilize VRAM, but cannot optimistically double-spend headroom.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from threading import RLock
from typing import cast

from .stream_admission import StreamAdmissionGate, StreamHealthSample

_OPTIONAL = frozenset({"vision", "research", "training", "render"})
_MAX_CLOCK_MS = 1e13


def _now(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("host clock must be a finite monotonic millisecond number")
    out = float(cast(int | float, value))
    if not math.isfinite(out) or not 0 <= out <= _MAX_CLOCK_MS:
        raise ValueError("invalid host monotonic time")
    return out


@dataclass(frozen=True, eq=False)
class WorkLeaseTicket:
    """Opaque in-process identity, not an OS credential or permission."""

    serial: int
    epoch: int


@dataclass(frozen=True)
class WorkLeaseAdvice:
    ticket: WorkLeaseTicket | None
    reason: str
    available_mib_after_claim: float | None = None
    authorizes_execution: bool = False
    authorizes_gameplay: bool = False
    authorizes_broadcast: bool = False


@dataclass
class _Claim:
    ticket: WorkLeaseTicket
    kind: str
    vram_mib: int
    last_heartbeat_ms: float
    started: bool = False
    revoke_requested: bool = False


class RealtimeGPUWorkLeases:
    """Thread-safe, fail-conservative reservation ledger for optional tasks.

    Lifecycle: enable -> observe trusted host telemetry -> reserve ->
    mark_started (after independent host launch) -> heartbeat -> release
    (only AFTER trusted host confirms termination).

    poll() returns tickets requiring an OS-level stop. Timeout, stream
    pressure, stale telemetry and clock rollback revoke but NEVER free memory.
    No untrusted model, viewer, or chat message can create host evidence.
    """

    def __init__(
        self, *, minimum_unclaimed_mib: int = 1536,
        max_optional_jobs: int = 2, lease_timeout_ms: int = 3000,
        max_sample_age_ms: int = 1500,
    ) -> None:
        if type(minimum_unclaimed_mib) is not int or not 512 <= minimum_unclaimed_mib <= 32768:
            raise ValueError("minimum_unclaimed_mib must be 512..32768")
        if type(max_optional_jobs) is not int or not 1 <= max_optional_jobs <= 4:
            raise ValueError("max_optional_jobs must be 1..4")
        if type(lease_timeout_ms) is not int or not 250 <= lease_timeout_ms <= 10000:
            raise ValueError("lease_timeout_ms must be 250..10000")
        if type(max_sample_age_ms) is not int or not 251 <= max_sample_age_ms <= 5000:
            raise ValueError("max_sample_age_ms must be 251..5000")
        self._reserve_mib = minimum_unclaimed_mib
        self._max_jobs = max_optional_jobs
        self._timeout_ms = lease_timeout_ms
        self._max_age_ms = max_sample_age_ms
        self._gate = StreamAdmissionGate(max_sample_age_ms=max_sample_age_ms)
        self._lock = RLock()
        self._enabled = False
        self._epoch = 0
        self._serial = 0
        self._sample: StreamHealthSample | None = None
        self._last_now: float | None = None
        self._claims: dict[int, _Claim] = {}
        self._counts = {
            "reserved": 0, "denied": 0, "started": 0,
            "revoked": 0, "released": 0, "clock_rollbacks": 0,
        }

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("trusted local host opt-in required")
        with self._lock:
            if self._enabled:
                raise RuntimeError("disable before restarting")
            if self._claims:
                raise RuntimeError("old workers must be confirmed stopped before reuse")
            self._gate.enable(owner_approved=True)
            self._epoch += 1
            self._enabled = True
            self._sample = None
            self._last_now = None

    def _revoke(self, item: _Claim) -> None:
        if not item.revoke_requested:
            item.revoke_requested = True
            self._counts["revoked"] += 1

    def _revoke_all(self) -> None:
        for item in self._claims.values():
            self._revoke(item)

    def disable(self) -> None:
        """Invalidate every ticket; do NOT assume a worker has stopped."""
        with self._lock:
            self._enabled = False
            self._epoch += 1
            self._gate.disable()
            self._revoke_all()
            self._sample = None

    def observe(self, sample: StreamHealthSample) -> bool:
        """Ingest ONLY trusted, ordered local telemetry, not agent-generated data."""
        if type(sample) is not StreamHealthSample:
            raise TypeError("expected typed local telemetry")
        with self._lock:
            if not self._enabled:
                return False
            accepted = self._gate.observe(sample)
            if not accepted:
                return False
            self._sample = sample
            # Immediately demand stop on overload; never await the next worker
            # reservation or heartbeat. Existing claims remain charged.
            t = sample.telemetry
            if (t.free_vram_mib < max(1536, self._reserve_mib)
                    or (t.game_active and t.game_fps < 45)
                    or t.speech_backlog_ms > 350
                    or ((t.live or t.private_stream_rehearsal)
                        and (sample.obs_render_lag_pct > 1
                             or sample.obs_encode_lag_pct > 1))):
                self._revoke_all()
            else:
                # A game/stream transition may make research/training/render
                # ineligible while leaving bounded vision permissible.
                for item in self._claims.values():
                    if (t.live or t.private_stream_rehearsal) and item.kind != "vision":
                        self._revoke(item)
            return True

    def _poll_locked(self, now: float) -> tuple[WorkLeaseTicket, ...]:
        if self._last_now is not None and now < self._last_now:
            self._counts["clock_rollbacks"] += 1
            self._revoke_all()
            # Preserve high-water mark: a reversed clock cannot extend leases.
            return tuple(x.ticket for x in self._claims.values() if x.revoke_requested)
        self._last_now = now
        current = self._sample
        stale = (not self._enabled or current is None
                 or current.observed_ms > now
                 or now - current.observed_ms > self._max_age_ms)
        for item in self._claims.values():
            if stale or now - item.last_heartbeat_ms > self._timeout_ms:
                self._revoke(item)
            elif not self._gate.advise(item.kind, now_ms=now).allowed:
                self._revoke(item)
        return tuple(x.ticket for x in self._claims.values() if x.revoke_requested)

    def poll(self, *, now_ms: float) -> tuple[WorkLeaseTicket, ...]:
        """Return revocations for the trusted host to enforce out-of-process."""
        now = _now(now_ms)
        with self._lock:
            return self._poll_locked(now)

    def reserve(
        self, *, kind: str, vram_mib: int, now_ms: float,
        host_verified: bool = False,
    ) -> WorkLeaseAdvice:
        """Account for concurrent GPU claims, never launch a model."""
        if type(kind) is not str or kind not in _OPTIONAL:
            raise ValueError("only optional workloads can request GPU leases")
        if type(vram_mib) is not int or not 1 <= vram_mib <= 32768:
            raise ValueError("vram_mib must be a bounded positive integer")
        now = _now(now_ms)
        with self._lock:
            self._poll_locked(now)
            if not self._enabled or host_verified is not True:
                reason = "trusted_local_host_required"
            elif self._last_now != now:
                reason = "host_clock_reversed"
            elif self._sample is None:
                reason = "telemetry_missing"
            elif self._sample.observed_ms > now or now - self._sample.observed_ms > self._max_age_ms:
                reason = "telemetry_stale"
            elif not self._gate.advise(kind, now_ms=now).allowed:
                reason = "realtime_resource_pressure"
            elif any(x.revoke_requested for x in self._claims.values()):
                # A revocation is NOT an acknowledgement that the actual
                # worker relinquished the GPU. Wait for host-confirmed stop.
                reason = "previous_worker_stop_unconfirmed"
            elif len(self._claims) >= self._max_jobs:
                reason = "optional_concurrency_limit"
            else:
                total_claimed = sum(item.vram_mib for item in self._claims.values())
                available_after = self._sample.telemetry.free_vram_mib - total_claimed - vram_mib
                if available_after < self._reserve_mib:
                    reason = "critical_gpu_reserve_protected"
                else:
                    self._serial += 1
                    ticket = WorkLeaseTicket(self._serial, self._epoch)
                    self._claims[ticket.serial] = _Claim(ticket, kind, vram_mib, now)
                    self._counts["reserved"] += 1
                    return WorkLeaseAdvice(ticket, "optional_reservation_only",
                                           round(available_after, 2))
            self._counts["denied"] += 1
            return WorkLeaseAdvice(None, reason)

    def _lookup(self, ticket: WorkLeaseTicket) -> _Claim | None:
        if type(ticket) is not WorkLeaseTicket:
            raise TypeError("expected original in-process ticket")
        item = self._claims.get(ticket.serial)
        return item if item is not None and item.ticket is ticket else None

    def mark_started(
        self, ticket: WorkLeaseTicket, *, now_ms: float,
        host_confirms_worker_started: bool = False,
    ) -> bool:
        """Mark independent start acknowledgement; recheck pressure and TTL."""
        now = _now(now_ms)
        with self._lock:
            self._poll_locked(now)
            item = self._lookup(ticket)
            if (not self._enabled or host_confirms_worker_started is not True
                    or item is None or item.ticket.epoch != self._epoch
                    or item.started or item.revoke_requested
                    or self._last_now != now):
                return False
            item.started = True
            item.last_heartbeat_ms = now
            self._counts["started"] += 1
            return True

    def heartbeat(
        self, ticket: WorkLeaseTicket, *, now_ms: float,
        host_confirms_worker_running: bool = False,
    ) -> bool:
        """A heartbeat cannot resurrect a revoked or old-session lease."""
        now = _now(now_ms)
        with self._lock:
            self._poll_locked(now)
            item = self._lookup(ticket)
            if (not self._enabled or host_confirms_worker_running is not True
                    or item is None or not item.started or item.revoke_requested
                    or item.ticket.epoch != self._epoch or self._last_now != now):
                return False
            item.last_heartbeat_ms = now
            return True

    def release(
        self, ticket: WorkLeaseTicket, *,
        host_confirms_worker_stopped: bool = False,
    ) -> bool:
        """Only an acknowledged stop frees a GPU claim, even after disable()."""
        with self._lock:
            item = self._lookup(ticket)
            if item is None or host_confirms_worker_stopped is not True:
                return False
            self._claims.pop(ticket.serial)
            self._counts["released"] += 1
            return True

    def metrics(self) -> dict[str, int | bool]:
        """Bounded anonymous counters; never expose host PIDs or content."""
        with self._lock:
            return {
                **self._counts,
                "enabled": self._enabled,
                "outstanding_claims": len(self._claims),
                "pending_revocations": sum(x.revoke_requested for x in self._claims.values()),
            }


__all__ = ["RealtimeGPUWorkLeases", "WorkLeaseTicket", "WorkLeaseAdvice"]
