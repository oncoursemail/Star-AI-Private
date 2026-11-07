"""Host-only OS witness bridge for optional VTuber GPU-work reservations.

Integrates RealtimeGPUWorkLeases with independently pinned OS process handles.
The bridge never launches, signals, or kills processes. Its stop intents must
be serviced by a separate trusted, nonblocking process supervisor. Only a
confirmed stopped *pinned process handle* frees a reservation. Process
observation failures fail closed and retain all outstanding reservations.

The owner-selected PID must come from the local host's own worker registry,
never from a model output, viewer chat, Discord message, or HTTP request.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from threading import RLock
from typing import Callable, Protocol, cast

from .stream_realtime_gpu_leases import RealtimeGPUWorkLeases, WorkLeaseTicket


class _ProcessHandle(Protocol):
    @property
    def pid(self) -> int: ...

    def create_time(self) -> float: ...

    def is_running(self) -> bool: ...


def _process(pid: int) -> _ProcessHandle:
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError("local psutil runtime unavailable") from exc
    return psutil.Process(pid)


def _birth(value: object) -> float:
    if type(value) not in (float, int):
        raise ValueError("invalid OS process creation time")
    try:
        out = float(cast(int | float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError("invalid OS process creation time") from exc
    if not math.isfinite(out) or not 0 < out < 1e12:
        raise ValueError("invalid OS process creation time")
    return out


@dataclass(frozen=True)
class GPUWorkerStopIntent:
    """Host-internal request, NOT authorization to signal or kill a process."""

    ticket: WorkLeaseTicket
    pid: int
    born_unix_s: float
    reason: str
    authorizes_termination: bool = False
    authorizes_broadcast: bool = False


@dataclass
class _Pinned:
    handle: _ProcessHandle
    ticket: WorkLeaseTicket
    pid: int
    born: float


class HostGPUWorkerLeaseBridge:
    """Monitor host-started optional workers without trusting caller booleans.

    bind_started() verifies the OS process PID+birth BEFORE acknowledging the
    lease's start. reconcile() returns intents for the trusted supervisor and
    frees claims ONLY on a positive pinned-handle non-running observation.

    The caller must keep the original process handle alive, service returned
    stop intents independently and reconcile again after stop completes.
    Merely sending a stop request is never release evidence.
    """

    def __init__(
        self,
        leases: RealtimeGPUWorkLeases,
        *,
        process_factory: Callable[[int], _ProcessHandle] = _process,
    ) -> None:
        if not isinstance(leases, RealtimeGPUWorkLeases):
            raise TypeError("host GPU reservation ledger required")
        if not callable(process_factory):
            raise TypeError("trusted local process factory required")
        self._leases = leases
        self._factory = process_factory
        self._lock = RLock()
        self._pinned: dict[int, _Pinned] = {}
        self._stats = {"bound": 0, "confirmed_stopped": 0, "uncertain": 0}

    @staticmethod
    def _read(handle: _ProcessHandle, pid: int, born: float) -> str:
        """Only a positive pinned-handle not-running result proves stop.

        Any I/O error, changed birth time, or inconsistent handle is UNKNOWN.
        In particular, a failed or timed-out process query cannot free VRAM.
        """
        try:
            if type(handle.pid) is not int or handle.pid != pid:
                return "unknown"
            running = handle.is_running()
            if type(running) is not bool:
                return "unknown"
            if running is False:
                return "stopped"
            if _birth(handle.create_time()) != born:
                return "unknown"
            if handle.is_running() is not True:
                return "unknown"
            return "running"
        except Exception:
            return "unknown"

    def bind_started(
        self, ticket: WorkLeaseTicket, *, pid: int, now_ms: float,
        owner_approved: bool = False,
    ) -> bool:
        """Only the local host may attach its just-started worker handle."""
        if owner_approved is not True:
            raise PermissionError("owner-approved local worker enrollment required")
        if type(ticket) is not WorkLeaseTicket:
            raise TypeError("original in-process lease ticket required")
        if type(pid) is not int or not 1 <= pid < 2**31:
            raise ValueError("valid host-selected process ID required")
        with self._lock:
            if ticket.serial in self._pinned:
                return False
            try:
                handle = self._factory(pid)
                if type(handle.pid) is not int or handle.pid != pid:
                    return False
                born = _birth(handle.create_time())
                if (self._read(handle, pid, born) != "running"
                        or self._read(handle, pid, born) != "running"):
                    return False
            except Exception:
                return False
            if not self._leases.mark_started(
                ticket, now_ms=now_ms, host_confirms_worker_started=True,
            ):
                return False
            self._pinned[ticket.serial] = _Pinned(handle, ticket, pid, born)
            self._stats["bound"] += 1
            return True

    def reconcile(self, *, now_ms: float) -> tuple[GPUWorkerStopIntent, ...]:
        """Read-only, bounded health tick. Return stop intents, never block on stop.

        If process identity cannot be established, disable optional admission,
        revoke all claims, and keep claims charged until independent proof of
        exit. No uncertain query is interpreted as process termination.
        """
        with self._lock:
            revoked = set(self._leases.poll(now_ms=now_ms))
            intents: list[GPUWorkerStopIntent] = []
            uncertain = False
            for serial, item in tuple(self._pinned.items()):
                state = self._read(item.handle, item.pid, item.born)
                if state == "stopped":
                    if self._leases.release(
                        item.ticket, host_confirms_worker_stopped=True,
                    ):
                        del self._pinned[serial]
                        self._stats["confirmed_stopped"] += 1
                    continue
                if state == "unknown":
                    uncertain = True
                    self._stats["uncertain"] += 1
                elif item.ticket not in revoked:
                    if not self._leases.heartbeat(
                        item.ticket, now_ms=now_ms,
                        host_confirms_worker_running=True,
                    ):
                        uncertain = True
                if state == "unknown" or item.ticket in revoked or uncertain:
                    intents.append(GPUWorkerStopIntent(
                        item.ticket, item.pid, item.born,
                        "process_identity_unverified" if state == "unknown"
                        else "realtime_lease_revoked",
                    ))
            if uncertain:
                self._leases.disable()
                # The host should stop EVERY optional worker when evidence is
                # uncertain; add any other still-running workers to requests.
                known = {x.ticket.serial for x in intents}
                for item in self._pinned.values():
                    if item.ticket.serial not in known:
                        intents.append(GPUWorkerStopIntent(
                            item.ticket, item.pid, item.born,
                            "optional_host_session_disabled",
                        ))
            return tuple(intents)

    def disable(self) -> None:
        """Stop new GPU admissions; caller must reconcile and service intents."""
        with self._lock:
            self._leases.disable()

    def metrics(self) -> dict[str, int]:
        """No raw PIDs, process creation times, paths, or viewer data."""
        with self._lock:
            return {
                **self._stats,
                "pinned": len(self._pinned),
            }


__all__ = ["HostGPUWorkerLeaseBridge", "GPUWorkerStopIntent"]
