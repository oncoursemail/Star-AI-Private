"""Compose STAR's stream-pressure governor with multi-resource admission.

This is a policy bridge only. It accepts trusted, already-collected host
samples, converts them to a freshness-bounded health signal, and delegates
resource accounting to WorkloadAdmissionController. It does not inspect
hardware, start or stop workers, run models, control games, or authorize tools.
"""
from __future__ import annotations

from threading import RLock

from .stream_load_governor import StreamLoadGovernor, StreamSample
from .stream_workload_admission import (
    AdmissionSnapshot,
    HostHealth,
    Submission,
    WorkloadAdmissionController,
    WorkloadLease,
    WorkloadRequest,
)


_MAX_MONOTONIC_MS = 10**12


def _now(value: object) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_MONOTONIC_MS:
        raise ValueError("now_monotonic_ms must be a bounded monotonic integer")
    return value


class StreamWorkloadRuntime:
    """Single policy entry point for stream pressure and CPU/RAM/VRAM leases.

    The governor contributes pressure hysteresis and live-session state. The
    admission controller contributes queue ordering, resource reservations,
    deadlines, and host-confirmed lease release. Neither component executes
    work. The caller remains responsible for owner consent, authorization,
    process supervision, and checking that a worker really stopped.
    """

    def __init__(
        self,
        admission: WorkloadAdmissionController,
        governor: StreamLoadGovernor | None = None,
    ) -> None:
        if not isinstance(admission, WorkloadAdmissionController):
            raise TypeError("admission must be WorkloadAdmissionController")
        if governor is not None and not isinstance(governor, StreamLoadGovernor):
            raise TypeError("governor must be StreamLoadGovernor or None")
        self._admission = admission
        self._governor = governor if governor is not None else StreamLoadGovernor()
        self._health: HostHealth | None = None
        self._lock = RLock()

    def observe(
        self,
        sample: StreamSample,
        *,
        now_monotonic_ms: int,
        trusted_host: bool = False,
    ) -> str:
        """Accept one fresh host sample and update the governor's hysteresis."""
        now = _now(now_monotonic_ms)
        if trusted_host is not True:
            raise PermissionError("authoritative host telemetry is required")
        if type(sample) is not StreamSample:
            raise TypeError("sample must be StreamSample")
        if sample.captured_ms > now:
            raise ValueError("host sample cannot be future-dated")
        if now - sample.captured_ms > self._governor.policy.stale_after_ms:
            raise ValueError("host sample is stale")

        with self._lock:
            state = self._governor.observe(sample, trusted_host=True)
            self._health = HostHealth(
                observed_monotonic_ms=sample.captured_ms,
                realtime_degraded=state != "normal",
                streaming=sample.streaming,
                gaming=sample.gaming,
            )
            return state

    def submit(self, request: WorkloadRequest) -> Submission:
        """Queue a content-free request; this does not authorize its execution."""
        return self._admission.submit(request)

    def cancel_queued(self, request_id: str) -> bool:
        """Cancel queued work only; active workers are never preempted here."""
        return self._admission.cancel_queued(request_id)

    def _health_for(self, now_ms: int) -> HostHealth | None:
        health = self._health
        if health is None:
            return None
        age = now_ms - health.observed_monotonic_ms
        if age < 0 or age > self._governor.policy.stale_after_ms:
            return HostHealth(
                observed_monotonic_ms=health.observed_monotonic_ms,
                realtime_degraded=True,
                streaming=health.streaming,
                gaming=health.gaming,
            )
        return health

    def schedule(
        self,
        now_monotonic_ms: int,
        *,
        max_admissions: int = 8,
    ) -> tuple[WorkloadLease, ...]:
        """Reserve resources using the strictest of both health freshness limits."""
        now = _now(now_monotonic_ms)
        with self._lock:
            return self._admission.schedule(
                now,
                health=self._health_for(now),
                max_admissions=max_admissions,
            )

    def release(
        self,
        lease_id: str,
        now_monotonic_ms: int,
        *,
        host_confirmed_stopped: bool,
    ) -> bool:
        """Release a reservation only after the host confirms worker termination."""
        return self._admission.release(
            lease_id,
            _now(now_monotonic_ms),
            host_confirmed_stopped=host_confirmed_stopped,
        )

    def snapshot(self, now_monotonic_ms: int) -> AdmissionSnapshot:
        """Return aggregate scheduler state without request or lease identifiers."""
        now = _now(now_monotonic_ms)
        with self._lock:
            return self._admission.snapshot(now, health=self._health_for(now))
