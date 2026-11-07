"""Host-owned Windows optional GPU worker stop service (opt-in, never a launcher).

The trusted local supervisor supplies the exact subprocess.Popen object it
created, not a PID or a command supplied by an LLM, viewer, HTTP or Discord.
This adapter converts the GPU lease bridge's advisory stop intent into a
single bounded termination request against that *owned process handle*.

On Windows, Popen.terminate() targets the retained Windows process handle,
rather than looking up a potentially reused PID. On other operating systems
this adapter does not signal automatically. Only a subsequent independent
positive OS exit observation can reclaim a GPU lease. No game, OBS, voice,
avatar, recording or public broadcast control is exposed.
"""
from __future__ import annotations

from dataclasses import dataclass
import platform
from subprocess import Popen
from threading import RLock
from typing import Callable

from .stream_gpu_lease_host_bridge import HostGPUWorkerLeaseBridge
from .stream_realtime_gpu_leases import (
    RealtimeGPUWorkLeases, WorkLeaseTicket, _now,
)


@dataclass(frozen=True)
class OwnedWorkerTick:
    """Sanitized host health result, deliberately without PIDs/arguments."""

    owned_workers: int
    stop_requests_sent: int
    exits_confirmed: int
    uncertain_workers: int
    authorizes_execution: bool = False
    authorizes_gameplay: bool = False
    authorizes_broadcast: bool = False


@dataclass
class _Owned:
    ticket: WorkLeaseTicket
    process: Popen[bytes]
    pid: int
    bridge_bound: bool
    stop_sent: bool = False


class HostOwnedOptionalGPUWorkers:
    """Reconcile optional AI workers started by the trusted Windows host.

    Register after the host has independently reserved VRAM and launched a
    process with its own fixed, owner-configured command. Do not expose this
    object or its Popen handles to untrusted model/tool input.

    Registration failure quarantines the actual returned process until exit.
    A failed launch that never yielded a process is NOT handled by this API.
    Such ambiguous launch failures need the caller's own supervisor recovery.
    """

    def __init__(
        self,
        leases: RealtimeGPUWorkLeases,
        bridge: HostGPUWorkerLeaseBridge,
        *,
        system_name: Callable[[], str] = platform.system,
    ) -> None:
        if not isinstance(leases, RealtimeGPUWorkLeases):
            raise TypeError("trusted GPU lease ledger required")
        if not isinstance(bridge, HostGPUWorkerLeaseBridge) or bridge._leases is not leases:
            raise TypeError("bridge and ledger must refer to same local session")
        if not callable(system_name):
            raise TypeError("host OS selector required")
        self._leases = leases
        self._bridge = bridge
        self._system_name = system_name
        self._lock = RLock()
        self._enabled = False
        self._owned: dict[int, _Owned] = {}

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner-approved Windows host enrollment required")
        with self._lock:
            if self._owned:
                raise RuntimeError("previous workers must exit before restart")
            if self._system_name() != "Windows":
                raise RuntimeError("automated optional-worker stops require Windows")
            self._enabled = True

    def enroll_spawned(
        self,
        ticket: WorkLeaseTicket,
        process: Popen[bytes],
        *,
        now_ms: float,
        owner_approved: bool = False,
    ) -> bool:
        """Pin an original *locally spawned* Popen, never an externally chosen PID.

        The caller retains custody of the Popen and has already admitted the
        optional task in the same ledger. If OS binding fails, retain its claim
        and arrange a stop on the next host tick. Do not pretend it never ran.
        """
        _now(now_ms)
        if owner_approved is not True:
            raise PermissionError("owner-approved local worker required")
        if type(ticket) is not WorkLeaseTicket:
            raise TypeError("original lease ticket required")
        if not isinstance(process, Popen):
            raise TypeError("original host-spawned subprocess handle required")
        pid = process.pid
        if type(pid) is not int or not 1 <= pid < 2**31:
            raise ValueError("invalid host-spawned process")
        with self._lock:
            if not self._enabled:
                raise PermissionError("host worker stops disabled")
            if ticket.serial in self._owned or any(
                item.process is process or item.pid == pid
                for item in self._owned.values()
            ):
                raise ValueError("process or lease is already enrolled")
            if self._leases._lookup(ticket) is None:
                raise ValueError("lease does not belong to this host session")
            try:
                code = process.poll()
            except Exception:
                code = None
            if code is not None:
                # Original retained Popen positively reports completed process.
                # We have not marked this lease started or admitted anything.
                return self._leases.release(
                    ticket, host_confirms_worker_stopped=True,
                )
            item = _Owned(ticket, process, pid, False)
            self._owned[ticket.serial] = item
            try:
                item.bridge_bound = self._bridge.bind_started(
                    ticket, pid=pid, now_ms=now_ms, owner_approved=True,
                )
            except Exception:
                # The process may still exist, so quarantine it for stop.
                item.bridge_bound = False
            return item.bridge_bound

    def tick(self, *, now_ms: float) -> OwnedWorkerTick:
        """One host-supervisor tick, never run on a game/audio real-time thread.

        Stop intent is not stop completion. A Windows TerminateProcess request
        may fail; a reservation remains charged until the original Popen and
        pinned bridge have independently observed the process exit. If any
        observation fails, deny further optional admissions.
        """
        _now(now_ms)
        with self._lock:
            try:
                intents = self._bridge.reconcile(now_ms=now_ms)
            except Exception:
                self._bridge.disable()
                intents = ()
            revoked = {intent.ticket for intent in intents}
            sent, confirmed, uncertain = 0, 0, 0
            for serial, item in tuple(self._owned.items()):
                try:
                    if type(item.process.pid) is not int or item.process.pid != item.pid:
                        raise ValueError("original process identity changed")
                    exit_code = item.process.poll()
                    if exit_code is not None and type(exit_code) is not int:
                        raise ValueError("process exit result unavailable")
                except Exception:
                    uncertain += 1
                    self._bridge.disable()
                    continue

                if exit_code is not None:
                    if item.bridge_bound:
                        # The bridge's separately pinned psutil handle, not
                        # Popen.poll alone, must be the release witness.
                        try:
                            self._bridge.reconcile(now_ms=now_ms)
                        except Exception:
                            self._bridge.disable()
                        released = not self._bridge.is_pinned(item.ticket)
                    else:
                        # No OS witness enrolled, but the retained host-started
                        # Windows handle itself positively observed exit.
                        released = self._leases.release(
                            item.ticket, host_confirms_worker_stopped=True,
                        )
                    if released:
                        del self._owned[serial]
                        confirmed += 1
                    else:
                        uncertain += 1
                        self._bridge.disable()
                    continue

                # Failed pinning is never allowed to run indefinitely. A
                # revoked lease likewise asks to stop, without any new PID
                # lookup or user-controlled terminate command.
                should_stop = not item.bridge_bound or item.ticket in revoked
                if not should_stop or item.stop_sent:
                    continue
                if self._system_name() != "Windows":
                    uncertain += 1
                    self._bridge.disable()
                    continue
                try:
                    item.process.terminate()
                    item.stop_sent = True
                    sent += 1
                except Exception:
                    uncertain += 1
                    item.stop_sent = True  # no unbounded signal retry storm
                    self._bridge.disable()
            return OwnedWorkerTick(len(self._owned), sent, confirmed, uncertain)

    def disable(self) -> None:
        """Revoke all workers; the next tick requests owned Windows stops."""
        with self._lock:
            self._enabled = False
            self._bridge.disable()

    def metrics(self) -> dict[str, int | bool]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "owned_workers": len(self._owned),
                "pending_stop_confirmations": sum(
                    int(x.stop_sent) for x in self._owned.values()
                ),
                "quarantined_unbound": sum(
                    int(not x.bridge_bound) for x in self._owned.values()
                ),
            }


__all__ = ["HostOwnedOptionalGPUWorkers", "OwnedWorkerTick"]
