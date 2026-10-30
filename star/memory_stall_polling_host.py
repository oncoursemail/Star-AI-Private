"""Opt-in Linux memory-pressure polling worker for STAR's realtime brain.

MemoryStallGuard is a safe, in-memory admission latch; it needs an *actual*
worker to read /proc. This host supplies that missing production integration,
off the speech/game rendering path. No model or chat text may control its
reader, clock, approval, thread, or guard.

The worker observes aggregate kernel counters only. It neither reads user
data nor starts/stops inference, games, OBS, microphones, or OS processes.
Failure, shutdown, or a stale sample blocks new OPTIONAL work via the
existing guard; the existing urgent speech path remains available.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from threading import Event, RLock, Thread, current_thread
from typing import Callable

from .memory_stall_guard import (
    MemoryStallGuard, MemoryStallSample, read_linux_stall_sample,
)


@dataclass(frozen=True)
class PollingStatus:
    running: bool
    polls: int
    accepted: int
    failed: int
    last_sample_ms: float | None


class MemoryPressurePollingHost:
    """Read-only, one-session worker feeding an owner-enabled memory guard.

    start() is owner-gated, and shutdown() does not silently join an
    unresponsive OS reader indefinitely. A stopped or crashed poller
    immediately invalidates optional-work admission (not active worker
    leases). A new session must construct a new poller instance.

    The trusted embedding host owns lifecycle and must explicitly pass
    the SAME guard to StreamBrainGovernor(memory_guard=guard).
    """

    def __init__(
        self, *,
        guard: MemoryStallGuard,
        interval_s: float = 1.0,
        reader: Callable[[], MemoryStallSample | None] = read_linux_stall_sample,
    ) -> None:
        if not isinstance(guard, MemoryStallGuard):
            raise TypeError("expected existing MemoryStallGuard")
        if (type(interval_s) not in (float, int) or
                not math.isfinite(float(interval_s)) or
                not 0.25 <= float(interval_s) <= 2.0):
            raise ValueError("poll interval must be 0.25..2 seconds")
        if not callable(reader):
            raise TypeError("trusted host-side /proc reader required")
        self._guard = guard
        self._reader = reader
        self._interval_s = float(interval_s)
        self._lock = RLock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._started = False
        self._running = False
        self._polls = 0
        self._accepted = 0
        self._failed = 0
        self._last_sample_ms: float | None = None

    def start(self, *, owner_approved: bool = False) -> None:
        """Launch a periodic reader; never called automatically by imports."""
        if owner_approved is not True:
            raise PermissionError("trusted owner must opt into Linux PSI polling")
        with self._lock:
            if self._started:
                raise RuntimeError("polling host is single-use")
            if self._guard.status()["enabled"] is not True:
                raise RuntimeError("enable the trusted MemoryStallGuard first")
            self._started = True
            # An old observation from before worker activation cannot confer
            # health to a new polling epoch.
            self._guard.observe(None)
            self._running = True
            self._thread = Thread(
                target=self._run,
                name="star-memory-stall-poll",
                daemon=True,
            )
            try:
                self._thread.start()
            except Exception:
                self._running = False
                self._guard.observe(None)
                raise

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    sample = self._reader()
                except Exception:
                    sample = None
                # Serialize with shutdown. A late completed read must never
                # re-enable optional work after the host has shut down.
                with self._lock:
                    if self._stop.is_set():
                        break
                    self._polls += 1
                    try:
                        accepted = self._guard.observe(sample)
                    except Exception:
                        accepted = False
                        self._guard.observe(None)
                    if accepted and isinstance(sample, MemoryStallSample):
                        self._accepted += 1
                        self._last_sample_ms = sample.sampled_ms
                    else:
                        self._failed += 1
                self._stop.wait(self._interval_s)
        finally:
            with self._lock:
                self._running = False
                self._guard.observe(None)

    def shutdown(self, *, timeout_s: float = 2.0) -> bool:
        """Revoke admission immediately; return False if reader won't exit.

        This never kills unrelated work. Keep the host object and stop event
        alive if a custom reader is blocked so its late sample is discarded.
        """
        if (type(timeout_s) not in (int, float)
                or not math.isfinite(float(timeout_s))
                or not 0 <= float(timeout_s) <= 10):
            raise ValueError("invalid join timeout")
        with self._lock:
            self._stop.set()
            self._guard.observe(None)
            thread = self._thread
        if thread is None:
            return True
        if thread is current_thread():
            return False
        thread.join(float(timeout_s))
        return not thread.is_alive()

    def status(self) -> PollingStatus:
        """Expose counters, never process IDs, usernames or model prompts."""
        with self._lock:
            return PollingStatus(
                self._running, self._polls, self._accepted,
                self._failed, self._last_sample_ms,
            )


__all__ = ["MemoryPressurePollingHost", "PollingStatus"]
