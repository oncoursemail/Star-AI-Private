"""Owner-opted, one-host Windows game-input ROUNDTRIP timing.

Unlike HostMonotonicGameProbe.guarded_dispatch, WindowsGameInputPort.send_action
blocks until its separate watchdog/worker reports release. Treating that call
as a low-latency *submission timestamp* would be false. This adapter measures
the complete host call (including key hold, worker startup and release), with
a separate pre-action inference interval. It never claims a game-state change.

An approved Windows host must own the pinned game window and input port.
This class never launches games, broadcasts, trains, connects to services or
creates synthetic input on its own. It invokes only the preauthorized port.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from threading import Event, RLock
from time import monotonic_ns
from typing import Callable, NoReturn

from .windows_game_input_port import WindowsGameInputPort

_MAX_NS = (1 << 63) - 1
_ACTION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")


@dataclass(frozen=True, slots=True)
class NativeRoundtripReport:
    """Counts and aggregate timings only; no action IDs or OS identity."""

    status: str
    attempted: int
    completed: int
    inference_p95_ms: float | None
    native_call_p95_ms: float | None
    frame_to_release_p95_ms: float | None
    # A passing latency audit does not grant any real-world permission.
    game_effect_attested: bool = False
    input_release_guaranteed: bool = False
    authorizes_gameplay: bool = False
    authorizes_broadcast: bool = False


def _p95_ns(values: list[int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[math.ceil(len(ordered) * 0.95) - 1] / 1_000_000, 3)


class NativeGameRoundtripAudit:
    """Measure bounded owner-approved game input roundtrips without fake wins.

    Single-use and single-threaded per frame, but abort() latches an Event
    without waiting for a potentially blocked native subprocess call. The
    underlying WindowsGameInputPort and its watchdog own actual key-up.
    Synthetic/mock clocks are *test-only* and never proof of hardware speed.
    """

    def __init__(
        self, port: WindowsGameInputPort, *, owner_approved: bool = False,
        max_decision_age_ms: int = 350, max_host_call_ms: int = 2500,
        clock: Callable[[], int] = monotonic_ns,
    ) -> None:
        if owner_approved is not True:
            raise PermissionError("owner-approved private game episode required")
        if not isinstance(port, WindowsGameInputPort):
            raise TypeError("existing approved WindowsGameInputPort required")
        for label, value, minimum, maximum in (
            ("max_decision_age_ms", max_decision_age_ms, 10, 5000),
            ("max_host_call_ms", max_host_call_ms, 100, 5000),
        ):
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{label} outside permitted range")
        if not callable(clock):
            raise TypeError("monotonic clock callable required")
        self._port = port
        self._clock = clock
        self._max_decision_ns = max_decision_age_ms * 1_000_000
        self._max_call_ns = max_host_call_ms * 1_000_000
        self._lock = RLock()
        self._aborted = Event()
        self._revoked = False
        self._finalized = False
        self._last_ns: int | None = None
        self._pending: tuple[int, int | None] | None = None
        self._attempted = 0
        self._durations: list[tuple[int, int, int]] = []
        self._final_report: NativeRoundtripReport | None = None

    def _fail(self, reason: str) -> NoReturn:
        self._revoked = True
        self._aborted.set()
        self._pending = None
        self._durations.clear()
        raise RuntimeError(reason)

    def _open(self) -> None:
        if self._aborted.is_set() or self._revoked:
            self._fail("private game roundtrip revoked")
        if self._finalized:
            raise RuntimeError("private game roundtrip finalized")

    def _sample(self) -> int:
        try:
            now = self._clock()
        except Exception:
            self._fail("host clock unavailable")
        if (type(now) is not int or not 0 <= now <= _MAX_NS
                or (self._last_ns is not None and now < self._last_ns)):
            self._fail("invalid or regressed host monotonic clock")
        self._last_ns = now
        return now

    def capture(self) -> None:
        """Host reports frame availability BEFORE invoking the AI decision."""
        with self._lock:
            self._open()
            if self._pending is not None or self._attempted >= 256:
                self._fail("unclaimed frame or excessive roundtrip window")
            self._pending = (self._sample(), None)

    def decision_ready(self) -> None:
        with self._lock:
            self._open()
            if self._pending is None or self._pending[1] is not None:
                self._fail("decision without exactly one pending frame")
            capture_ns, _ = self._pending
            now = self._sample()
            if now - capture_ns > self._max_decision_ns:
                self._fail("reasoning exceeded game decision deadline")
            self._pending = (capture_ns, now)

    def execute(self, action_id: str, hold_ms: int) -> None:
        """Invoke ONE native host call, then measure its actual return.

        The native call returns after key-release supervision, not at key-down.
        No submission timestamps from this method may be inserted into a
        HostMonotonicGameProbe replay as if they were pre-actuation events.
        """
        with self._lock:
            self._open()
            if self._pending is None or self._pending[1] is None:
                self._fail("native action requires ready decision")
            capture_ns, ready_ns = self._pending
            now = self._sample()
            if now - capture_ns > self._max_decision_ns:
                self._fail("action deadline expired before native host call")
            if (type(action_id) is not str or _ACTION.fullmatch(action_id) is None
                    or type(hold_ms) is not int or not 1 <= hold_ms <= 180):
                self._fail("unapproved native action request")
            self._attempted += 1
            try:
                # Only this already-approved port is able to generate input.
                success = self._port.send_action(action_id, hold_ms, self._aborted)
                finished_ns = self._sample()
                # Native return True is a limited OS/worker receipt, not a win.
                if (success is not True or self._aborted.is_set()
                        or self._port.focus_ok() is not True
                        or self._port.all_keys_up() is not True):
                    self._fail("native game input roundtrip not confirmed")
                if finished_ns - now > self._max_call_ns:
                    self._fail("native game input roundtrip deadline exceeded")
                self._durations.append((
                    ready_ns - capture_ns,
                    finished_ns - now,
                    finished_ns - capture_ns,
                ))
                self._pending = None
            except Exception:
                self._fail("native game input roundtrip failed")

    def abort(self) -> None:
        """Nonblocking cancellation signal; native port/watchdog own key-up."""
        self._aborted.set()
        if self._lock.acquire(blocking=False):
            try:
                self._revoked = True
                self._durations.clear()
                self._pending = None
            finally:
                self._lock.release()

    def report(self) -> NativeRoundtripReport:
        """Do not report partial successes while a frame or abort is pending."""
        with self._lock:
            if self._aborted.is_set() or self._revoked:
                return NativeRoundtripReport("revoked", self._attempted, 0, None, None, None)
            if self._final_report is not None:
                return self._final_report
            if self._pending is not None or not self._durations:
                return NativeRoundtripReport(
                    "incomplete", self._attempted, 0, None, None, None,
                )
            inference, call, total = zip(*self._durations, strict=True)
            return NativeRoundtripReport(
                "host_roundtrip_only", self._attempted, len(self._durations),
                _p95_ns(list(inference)), _p95_ns(list(call)), _p95_ns(list(total)),
            )

    def finalize(self) -> NativeRoundtripReport:
        with self._lock:
            self._open()
            result = self.report()
            if result.status != "host_roundtrip_only":
                self._fail("incomplete native game roundtrip cannot finalize")
            self._finalized = True
            self._final_report = result
            self._durations.clear()
            return result


__all__ = ["NativeRoundtripReport", "NativeGameRoundtripAudit"]
