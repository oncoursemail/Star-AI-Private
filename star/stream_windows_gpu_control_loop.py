"""Fail-closed host loop joining live GPU telemetry to optional worker control.

Only a trusted, private Windows supervisor may call this. The caller supplies
independently measured game/OBS/voice health; viewer/model messages are NEVER
health evidence. The loop must run outside gameplay, audio and OBS callbacks.
No automatic model launch or broadcast is performed by this module.

Star's optional work is OFF by default. The owner must separately enable the
GPU ledger and its fixed-command launch supervisor. Failed or stale probes
revoke optional workers but do not release their VRAM claims until the host
observes that their original process exited.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
import time
from typing import Callable

from .stream_admission import StreamHealthSample
from .stream_optional_gpu_launch_supervisor import (
    HostOptionalGPUWorkerLaunchSupervisor,
    HostOptionalWorkerPlan,
    OptionalWorkerLaunchResult,
)
from .stream_realtime_gpu_leases import RealtimeGPUWorkLeases, _now
from .stream_windows_gpu_probe import WindowsGPUHealthObserver


@dataclass(frozen=True)
class HostGPUControlTick:
    """Anonymous local status, never a model instruction or execution grant."""

    healthy: bool
    reason: str
    stop_requests_sent: int
    exits_confirmed: int
    outstanding_reservations: int
    authorizes_execution: bool = False
    authorizes_gameplay: bool = False
    authorizes_broadcast: bool = False


class WindowsGPUWorkerControlLoop:
    """Bind a real GPU sample, host health, lease revocation and process ticks.

    The caller owns all ingredients, and must never pass arbitrary input as
    host health. On loss of timely observations, permanently fault this loop;
    recreate it only after independent host reconciliation. The lock prevents
    interleaved sampling, launch and cleanup on different host threads.
    """

    def __init__(
        self,
        observer: WindowsGPUHealthObserver,
        supervisor: HostOptionalGPUWorkerLaunchSupervisor,
        leases: RealtimeGPUWorkLeases,
        *,
        clock_ms: Callable[[], float] = lambda: time.monotonic() * 1000.0,
        maximum_fresh_ms: int = 500,
        maximum_probe_ms: int = 2500,
    ) -> None:
        if not isinstance(observer, WindowsGPUHealthObserver):
            raise TypeError("host-pinned Windows GPU observer required")
        if not isinstance(supervisor, HostOptionalGPUWorkerLaunchSupervisor):
            raise TypeError("trusted Windows launch supervisor required")
        if not isinstance(leases, RealtimeGPUWorkLeases):
            raise TypeError("trusted GPU reservation ledger required")
        if observer._leases is not leases or supervisor._leases is not leases:
            raise ValueError("all host components must share one reservation ledger")
        if not callable(clock_ms):
            raise TypeError("local monotonic clock required")
        if type(maximum_fresh_ms) is not int or not 100 <= maximum_fresh_ms <= 1500:
            raise ValueError("bounded freshness policy required")
        if type(maximum_probe_ms) is not int or not 500 <= maximum_probe_ms <= 3000:
            raise ValueError("bounded GPU probe deadline required")
        self._observer = observer
        self._supervisor = supervisor
        self._leases = leases
        self._clock = clock_ms
        self._max_age = maximum_fresh_ms
        self._max_probe = maximum_probe_ms
        self._lock = Lock()
        self._healthy = False
        self._faulted = False
        self._last_read_ms: float | None = None

    def _fail_closed(self) -> None:
        self._healthy = False
        self._faulted = True
        self._leases.disable()
        self._supervisor.disable()

    def tick(self, local: StreamHealthSample) -> HostGPUControlTick:
        """Poll real GPU off hot paths; always service owned-worker exits/stops."""
        if not self._lock.acquire(blocking=False):
            # A concurrent poll invalidates the host's exclusive sampling
            # contract. Latch the *native* launch path off as well.
            self._fail_closed()
            return HostGPUControlTick(
                False,
                "host_supervisor_poll_overlap",
                0,
                0,
                self._leases.metrics()["outstanding_claims"],
            )
        try:
            accepted = False
            reason = "gpu_control_loop_faulted"
            try:
                start = _now(self._clock())
                if not self._faulted:
                    if type(local) is not StreamHealthSample:
                        reason = "host_health_missing"
                        self._fail_closed()
                    elif local.host_verified is not True or abs(start - _now(local.observed_ms)) > self._max_age:
                        reason = "host_health_not_fresh_or_verified"
                        self._fail_closed()
                    else:
                        result = self._observer.observe(local)
                        end = _now(self._clock())
                        if end < start or end - start > self._max_probe:
                            reason = "gpu_probe_too_slow_or_clock_invalid"
                            self._fail_closed()
                        elif not result.accepted:
                            reason = result.reason
                            self._fail_closed()
                        elif self._faulted:
                            # A second host thread already invalidated this
                            # observation while the probe was running.
                            reason = "host_control_faulted_during_probe"
                            accepted = False
                            self._healthy = False
                        else:
                            self._last_read_ms = end
                            self._healthy = True
                            accepted = True
                            reason = "live_gpu_host_control_healthy"
            except Exception:
                reason = "gpu_or_host_control_unavailable"
                self._fail_closed()
            # Always service previously started processes, even after a
            # telemetry fault or deliberate disable. No new launch occurs.
            try:
                owned = self._supervisor.tick(now_ms=_now(self._clock()))
                sent, exited = owned.stop_requests_sent, owned.exits_confirmed
                if owned.uncertain_workers:
                    accepted = False
                    reason = "host_process_exit_uncertain"
                    self._fail_closed()
            except Exception:
                sent, exited = 0, 0
                accepted = False
                reason = "host_worker_reconciliation_failed"
                self._fail_closed()
            return HostGPUControlTick(
                accepted and not self._faulted,
                reason,
                sent,
                exited,
                self._leases.metrics()["outstanding_claims"],
            )
        finally:
            self._lock.release()

    def launch(
        self,
        plan: HostOptionalWorkerPlan,
        *,
        owner_approved: bool = False,
    ) -> OptionalWorkerLaunchResult:
        """Start a fixed, owner-approved plan only after very recent live poll."""
        if owner_approved is not True:
            raise PermissionError("owner-approved host optional launch required")
        with self._lock:
            if self._faulted or not self._healthy or self._last_read_ms is None:
                return self._deferred("trusted_gpu_control_not_healthy")
            try:
                now = _now(self._clock())
            except (ValueError, TypeError):
                self._fail_closed()
                return self._deferred("trusted_gpu_control_clock_failed")
            if now < self._last_read_ms or now - self._last_read_ms > self._max_age:
                self._fail_closed()
                return self._deferred("trusted_gpu_control_observation_stale")
            if not self._leases.metrics()["enabled"]:
                self._fail_closed()
                return self._deferred("trusted_gpu_reservation_ledger_disabled")
            try:
                result = self._supervisor.launch(
                    plan,
                    now_ms=now,
                    owner_approved=True,
                )
            except Exception:
                # Native process creation can be ambiguous; the existing
                # owned-worker ledger must retain claims until exit is proven.
                self._fail_closed()
                return self._deferred("trusted_optional_launch_failed")
            if self._faulted:
                self._fail_closed()
                return OptionalWorkerLaunchResult(
                    "quarantined",
                    "trusted_control_revoked_during_launch",
                    self._leases.metrics()["outstanding_claims"],
                )
            if result.outcome in ("fault", "quarantined"):
                self._fail_closed()
            return result

    def _deferred(self, reason: str) -> OptionalWorkerLaunchResult:
        return OptionalWorkerLaunchResult(
            "deferred",
            reason,
            self._leases.metrics()["outstanding_claims"],
        )

    def disable(self) -> None:
        """Revoke optional work; follow with tick until exits are verified."""
        with self._lock:
            self._fail_closed()


__all__ = ["HostGPUControlTick", "WindowsGPUWorkerControlLoop"]
