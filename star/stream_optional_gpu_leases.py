"""Host-only admission ledger for *optional* GPU work during gaming streams.

The load governor estimates instantaneous headroom but does not reserve it.
Two independent workers can each be approved for the *same* free VRAM. This
ledger atomically accounts for overlapping reservations and latches revocation
until an external native host attests physical worker termination.

This is an advisory controller, NOT a CUDA allocator, watchdog, scheduler,
permission broker, OBS client, game controller, or source of trusted telemetry.
The host must review every lease immediately before each worker GPU step and
maintain an independent kill/timeout path if Python or the worker stalls.
Nothing is enabled by default.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import secrets
from threading import RLock
from typing import cast

from .stream_load_governor import StreamLoadAdvice, StreamLoadGovernor

_KINDS = frozenset({"vision", "reasoning", "tts_experiment", "game_practice", "studio_build"})


def _seconds(value: object, name: str, *, maximum: float = 1e10) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(cast(int | float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} is invalid") from exc
    if not math.isfinite(result) or not 0 <= result <= maximum:
        raise ValueError(f"{name} outside bounds")
    return result


@dataclass(frozen=True)
class OptionalGpuLease:
    """Opaque coordination receipt, NOT a capability or a security token."""

    lease_id: str
    work_kind: str
    reserved_vram_mb: int
    issued_at_s: float
    deadline_at_s: float


@dataclass(frozen=True)
class OptionalGpuDecision:
    action: str  # admit | reject | run | stop | unknown
    reason: str
    lease: OptionalGpuLease | None = None
    authorizes_gpu_execution: bool = False
    authorizes_game_input: bool = False
    authorizes_broadcast: bool = False


class OptionalGpuLeaseGate:
    """Bounded, thread-safe *advisory* VRAM reservation and revocation ledger.

    Only a separately authenticated host may request/review/acknowledge work.
    Reserve based on current governor headroom. Recheck before every optional
    GPU step; a stale, pressured or rolled-back clock revokes all outstanding
    work, and a reservation remains charged until native stop is witnessed.
    """

    def __init__(self, governor: StreamLoadGovernor, *,
                 max_workers: int = 3, max_lease_s: float = 15.0) -> None:
        if type(governor) is not StreamLoadGovernor:
            raise TypeError("expected the host's StreamLoadGovernor")
        if type(max_workers) is not int or not 1 <= max_workers <= 8:
            raise ValueError("max_workers must be 1..8")
        lease_limit = _seconds(max_lease_s, "max_lease_s", maximum=30)
        if lease_limit < 0.1:
            raise ValueError("max_lease_s must be at least 0.1")
        self._governor = governor
        self._max_workers = max_workers
        self._max_lease_s = lease_limit
        self._lock = RLock()
        self._enabled = False
        # Lease IDs must not collide with receipts from a prior Python host
        # process: delayed stop callbacks are otherwise able to free new work.
        # This random namespace is NOT an authentication token.
        self._instance_id = secrets.token_hex(16)
        self._epoch = 0
        self._serial = 0
        self._last_now: float | None = None
        self._outstanding: dict[str, OptionalGpuLease] = {}
        self._revoked: dict[str, str] = {}
        self._counts = {"admitted": 0, "rejected": 0,
                        "revoked": 0, "stopped": 0}

    def enable(
        self, *, owner_approved: bool = False, host_verified: bool = False,
        optional_workers_quiescent: bool = False,
    ) -> None:
        """Require native startup/rearm worker sweep before new reservations.

        A Python restart loses the in-memory ledger, not its former GPU
        workers. The independently authenticated native host must confirm
        there are no surviving *optional* workers from any previous instance.
        A caller-supplied bool is an assertion, not process verification.
        """
        if owner_approved is not True:
            raise PermissionError("owner approval required")
        if type(host_verified) is not bool or type(optional_workers_quiescent) is not bool:
            raise ValueError("native host sweep flags must be bool")
        with self._lock:
            if self._outstanding:
                raise RuntimeError("physical workers must stop before rearming")
            if not self._enabled:
                if not host_verified or not optional_workers_quiescent:
                    raise PermissionError("verified native optional-worker sweep required")
                self._epoch += 1
                self._last_now = None
            self._enabled = True

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._revoke_all("owner_disabled")

    def _revoke_all(self, reason: str) -> None:
        for ident in self._outstanding:
            if ident not in self._revoked:
                self._revoked[ident] = reason
                self._counts["revoked"] += 1

    def _clock(self, now_s: object) -> tuple[float, bool]:
        now = _seconds(now_s, "now_s")
        if self._last_now is not None and now < self._last_now:
            self._revoke_all("host_clock_reversed")
            return now, False
        self._last_now = now
        return now, True

    def _refresh(self, now: float) -> tuple[StreamLoadAdvice | None, str]:
        # Never reclaim reservations merely because a timer has expired.
        for ident, receipt in self._outstanding.items():
            if now >= receipt.deadline_at_s and ident not in self._revoked:
                self._revoked[ident] = "lease_expired"
                self._counts["revoked"] += 1
        try:
            advice = self._governor.recommend(now_s=now)
        except ValueError:
            self._revoke_all("resource_clock_invalid")
            return None, "resource_clock_invalid"
        if advice.profile != "normal" or not advice.allow_extra_gpu_inference:
            self._revoke_all("resource_" + advice.profile)
            return advice, "resource_" + advice.profile
        # A measured increase in game/OBS VRAM use can shrink the ceiling
        # below our previous reservations. All optional workers must yield.
        if sum(item.reserved_vram_mb for item in self._outstanding.values()) > advice.max_extra_gpu_vram_mb:
            self._revoke_all("vram_budget_shrunk")
            return advice, "vram_budget_shrunk"
        return advice, "headroom_fresh"

    def request(self, *, work_kind: str, vram_mb: int,
                duration_s: float, now_s: float,
                host_verified: bool = False) -> OptionalGpuDecision:
        """Admit only with fresh governor headroom and no pending native stop."""
        if type(work_kind) is not str or work_kind not in _KINDS:
            raise ValueError("unknown optional GPU workload")
        if type(vram_mb) is not int or not 64 <= vram_mb <= 65536:
            raise ValueError("vram_mb must be an integer 64..65536")
        duration = _seconds(duration_s, "duration_s", maximum=self._max_lease_s)
        if duration < 0.1:
            raise ValueError("duration_s must be at least 0.1")
        if type(host_verified) is not bool:
            raise ValueError("host_verified must be bool")
        with self._lock:
            def reject(reason: str) -> OptionalGpuDecision:
                self._counts["rejected"] += 1
                return OptionalGpuDecision("reject", reason)
            # Untrusted traffic must not advance our host-clock watermark.
            if not self._enabled:
                return reject("owner_opt_in_required")
            if not host_verified:
                return reject("host_not_verified")
            now, ordered = self._clock(now_s)
            if not ordered:
                return reject("host_clock_reversed")
            advice, reason = self._refresh(now)
            if self._revoked:
                return reject("pending_physical_stop")
            if advice is None or reason != "headroom_fresh":
                return reject(reason)
            if len(self._outstanding) >= self._max_workers:
                return reject("worker_limit")
            reserved = sum(lease.reserved_vram_mb for lease in self._outstanding.values())
            if vram_mb + reserved > advice.max_extra_gpu_vram_mb:
                return reject("vram_reserve_exhausted")
            self._serial += 1
            receipt = OptionalGpuLease(
                f"star-gpu-{self._instance_id}-{self._epoch}-{self._serial}",
                work_kind, vram_mb,
                now, now + duration,
            )
            self._outstanding[receipt.lease_id] = receipt
            self._counts["admitted"] += 1
            return OptionalGpuDecision("admit", "reservation_recorded", receipt)

    def review(self, lease_id: str, *, now_s: float,
               host_verified: bool = False) -> OptionalGpuDecision:
        """Review immediately before each GPU step, never authorizing execution."""
        if type(lease_id) is not str or len(lease_id) > 80:
            raise ValueError("invalid lease identifier")
        if type(host_verified) is not bool:
            raise ValueError("host_verified must be bool")
        with self._lock:
            lease = self._outstanding.get(lease_id)
            if lease is None:
                return OptionalGpuDecision("unknown", "no_outstanding_lease")
            if not host_verified:
                self._revoke_all("host_not_verified")
                return OptionalGpuDecision("stop", "host_not_verified", lease)
            now, ordered = self._clock(now_s)
            if not ordered:
                return OptionalGpuDecision("stop", "host_clock_reversed", lease)
            _, reason = self._refresh(now)
            if not self._enabled:
                return OptionalGpuDecision("stop", "owner_disabled", lease)
            if lease_id in self._revoked:
                return OptionalGpuDecision("stop", self._revoked[lease_id], lease)
            if self._revoked:
                # Revoked workers have NOT yet released physical VRAM.
                self._revoke_all("peer_stop_unconfirmed")
                return OptionalGpuDecision("stop", "peer_stop_unconfirmed", lease)
            if reason != "headroom_fresh":
                self._revoke_all(reason)
                return OptionalGpuDecision("stop", reason, lease)
            return OptionalGpuDecision("run", "fresh_advisory_only", lease)

    def acknowledge_stopped(self, lease_id: str, *,
                            host_verified: bool = False,
                            physical_worker_stopped: bool = False) -> bool:
        """Release VRAM claim only after a trusted native stop/exit witness."""
        if type(lease_id) is not str or len(lease_id) > 80:
            raise ValueError("invalid lease identifier")
        if type(host_verified) is not bool or type(physical_worker_stopped) is not bool:
            raise ValueError("native witness flags must be bool")
        with self._lock:
            if not host_verified or not physical_worker_stopped or lease_id not in self._outstanding:
                return False
            del self._outstanding[lease_id]
            self._revoked.pop(lease_id, None)
            self._counts["stopped"] += 1
            return True

    def metrics(self) -> dict[str, int | bool]:
        """Aggregate counters only; never store prompts, screen or viewer data."""
        with self._lock:
            return {**self._counts, "outstanding": len(self._outstanding),
                    "stop_pending": len(self._revoked), "enabled": self._enabled}


__all__ = ["OptionalGpuLease", "OptionalGpuDecision", "OptionalGpuLeaseGate"]
