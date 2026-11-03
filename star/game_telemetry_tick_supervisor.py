"""Opt-in local receiver watchdog that ticks game-telemetry liveness without packets.

The signed game-engine telemetry receiver has a fail-closed liveness guard, but
its check() previously needed the host to keep calling it during transport
silence. This host-owned periodic thread closes that *integration* gap.

This module never observes games, sends keys, runs AI, generates speech, opens
a listener, starts OBS or broadcasts. Its trusted callback is only a stop
notification: the operating-system host must independently mute/stop physical
actuators. A Python thread is NOT an OS watchdog and cannot survive a process
crash, a wedged GIL, or a dead machine.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from threading import Event, RLock, Thread, current_thread
from typing import Callable

from .game_telemetry_liveness_guard import (
    GameTelemetryLivenessGuard, GameTelemetryLivenessLost,
)
from .game_state_transition_witness import AttestedGameMoment


@dataclass(frozen=True)
class TickSupervisorMetrics:
    active: bool
    checks: int
    accepted_frames: int
    revoked: bool
    stop_callback_failed: bool


class GameTelemetryTickSupervisor:
    """Own one daemon tick loop and gate *all* receiver ingestion.

    An authenticated, isolated owner host arms the original guard BEFORE
    start(). Only then does this thread call check() while no packets arrive.
    The callback is a trusted host's best-effort stop notification, not a
    guarantee of Windows key release or audio silencing.

    stop() permanently closes the wrapper and revokes its bridge/journal.
    Create a fresh guard and wrapper for a new session.
    """

    def __init__(
        self,
        guard: GameTelemetryLivenessGuard,
        *,
        interval_s: float = 0.1,
        on_lost: Callable[[], None] | None = None,
    ) -> None:
        if not isinstance(guard, GameTelemetryLivenessGuard):
            raise TypeError("a signed-telemetry liveness guard is required")
        if (type(interval_s) not in (int, float)
                or not math.isfinite(interval_s)
                or not 0.01 <= interval_s <= 1.0
                or interval_s * 3 > guard.silence_limit_s):
            raise ValueError("tick interval must be <= one third of the silence limit")
        if on_lost is not None and not callable(on_lost):
            raise TypeError("on_lost must be a trusted local host callback")
        self._guard = guard
        self._interval = float(interval_s)
        self._on_lost = on_lost
        self._lock = RLock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._started = False
        self._closed = False
        self._failed = False
        self._callback_failed = False
        self._checks = 0
        self._frames = 0

    def start(self, *, owner_approved: bool = False) -> None:
        """Owner arms an already-authorized signed receiver, not a stream."""
        if owner_approved is not True:
            raise PermissionError("trusted host must approve the watchdog")
        with self._lock:
            if self._started or self._closed:
                raise RuntimeError("watchdog cannot be restarted")
            if not self._guard.metrics().active:
                raise GameTelemetryLivenessLost("arm the signed receiver first")
            self._started = True
            worker = Thread(
                target=self._run, name="star-telemetry-receiver-tick", daemon=True,
            )
            self._thread = worker
            try:
                worker.start()
            except Exception:
                self._trip()
                raise RuntimeError("telemetry supervisor could not start") from None

    def _trip(self) -> None:
        """Single terminal transition; run stop callback at most once."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._failed = True
            self._stop.set()
        try:
            self._guard.disable()
        except Exception:
            pass
        if self._on_lost is not None:
            try:
                self._on_lost()
            except Exception:
                with self._lock:
                    self._callback_failed = True

    def _run(self) -> None:
        try:
            while not self._stop.wait(self._interval):
                with self._lock:
                    if self._closed:
                        return
                self._guard.check()
                with self._lock:
                    self._checks += 1
        except Exception:
            # No clock, packet, signing key or callback exception is surfaced.
            self._trip()

    def _require_running(self) -> None:
        with self._lock:
            if not self._started or self._closed:
                raise GameTelemetryLivenessLost("telemetry receiver is not running")
            worker = self._thread
            if worker is not None and worker.is_alive():
                return
        self._trip()
        raise GameTelemetryLivenessLost("telemetry watchdog is unavailable")

    def accept(self, packet: bytes) -> AttestedGameMoment | None:
        """Ingest through the guarded receiver ONLY, fail shut on any fault."""
        self._require_running()
        try:
            result = self._guard.accept(packet)
        except Exception:
            self._trip()
            raise GameTelemetryLivenessLost(
                "telemetry receiver rejected an untrusted frame"
            ) from None
        self._require_running()
        with self._lock:
            self._frames += 1
        return result

    def health(self) -> TickSupervisorMetrics:
        """Check the guard at call time, not only the last background tick."""
        self._require_running()
        try:
            self._guard.check()
        except Exception:
            self._trip()
            raise GameTelemetryLivenessLost("telemetry receiver liveness lost") from None
        self._require_running()
        return self.metrics()

    def stop(self) -> None:
        """Owner closes the receiver permanently; no automatic restart."""
        with self._lock:
            self._closed = True
            self._stop.set()
            worker = self._thread
        self._guard.disable()
        if worker is not None and worker is not current_thread():
            worker.join(timeout=min(1.0, self._interval * 3))

    def metrics(self) -> TickSupervisorMetrics:
        """No game frames, model text, credentials or detailed failure logs."""
        with self._lock:
            live = (self._started and not self._closed
                    and self._thread is not None and self._thread.is_alive())
            checks, frames = self._checks, self._frames
            failed, callback_failed = self._failed, self._callback_failed
        return TickSupervisorMetrics(
            active=live and self._guard.metrics().active,
            checks=checks, accepted_frames=frames,
            revoked=failed or self._guard.metrics().revoked,
            stop_callback_failed=callback_failed,
        )


__all__ = ["GameTelemetryTickSupervisor", "TickSupervisorMetrics"]
