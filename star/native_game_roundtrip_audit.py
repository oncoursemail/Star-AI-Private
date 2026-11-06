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
from threading import Event, Lock, RLock
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
    # Optional explicit native-host frame accounting. A host-supplied total is
    # not proof that the host actually observed every real game frame.
    observed_frames: int = 0
    no_action_frames: int = 0
    host_frame_coverage_declared: bool = False
    all_frame_decision_p95_ms: float | None = None
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
        require_frame_coverage: bool = False,
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
        if type(require_frame_coverage) is not bool:
            raise ValueError("require_frame_coverage must be boolean")
        if not callable(clock):
            raise TypeError("monotonic clock callable required")
        self._port = port
        self._clock = clock
        self._max_decision_ns = max_decision_age_ms * 1_000_000
        self._max_call_ns = max_host_call_ms * 1_000_000
        self._require_frame_coverage = require_frame_coverage
        self._last_frame_sequence = 0
        self._no_action_frames = 0
        self._coverage_sealed = False
        self._lock = RLock()
        # A separate, briefly held lock lets health polling inspect an active
        # native call without waiting for the OS input worker. This uses a real
        # host monotonic clock, never a model-supplied frame timestamp.
        self._health_lock = Lock()
        self._active_call_started_ns: int | None = None
        self._aborted = Event()
        self._revoked = False
        self._finalized = False
        self._last_ns: int | None = None
        self._pending: tuple[int, int | None] | None = None
        self._attempted = 0
        self._durations: list[tuple[int, int, int]] = []
        self._decision_durations: list[int] = []
        self._final_report: NativeRoundtripReport | None = None

    def _fail(self, reason: str) -> NoReturn:
        self._revoked = True
        self._aborted.set()
        self._pending = None
        self._durations.clear()
        self._decision_durations.clear()
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

    def capture(self, *, frame_sequence: int | None = None) -> None:
        """Declare each observed input frame BEFORE AI reasoning.

        In opt-in frame-coverage mode, the private host reports consecutive
        1-based frame sequence numbers, including frames intentionally not
        acted on. A hole, replay or late frame invalidates ALL measurements.
        This detects omissions *reported* to this adapter, not unseen frames
        concealed by a broken or dishonest source.
        """
        with self._lock:
            self._open()
            if self._coverage_sealed:
                self._fail("native frame coverage already sealed")
            if self._require_frame_coverage:
                if (type(frame_sequence) is not int
                        or frame_sequence != self._last_frame_sequence + 1
                        or frame_sequence > 256):
                    self._fail("missing, replayed or invalid native game frame")
                self._last_frame_sequence = frame_sequence
            elif frame_sequence is not None:
                self._fail("frame sequence requires explicit coverage opt-in")
            if self._pending is not None or self._attempted + self._no_action_frames >= 256:
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

    def no_action(self) -> None:
        """Account for an observed frame whose completed decision is to wait.

        This is NOT an input acknowledgment, gaming success or timing sample.
        It prevents an authorized agent's explicit no-op from being mistaken
        for a lost frame or being cherry-picked as a fast completed action.
        """
        with self._lock:
            self._open()
            if (not self._require_frame_coverage
                    or self._pending is None or self._pending[1] is None):
                self._fail("no-action frame requires an observed ready decision")
            capture_ns, ready_ns = self._pending
            if self._sample() - capture_ns > self._max_decision_ns:
                self._fail("no-action frame exceeded decision deadline")
            self._decision_durations.append(ready_ns - capture_ns)
            self._no_action_frames += 1
            self._pending = None

    def seal_frames(self, *, expected_frames: int, host_verified: bool = False) -> None:
        """Close a verified host-declared frame window before finalization.

        The frame count must come from an independently trusted frame source,
        never from the model or this class's observed_frames. host_verified is
        an assertion made by the embedding host, NOT a cryptographic receipt.
        A host that omits frames from both paths cannot be detected here.
        """
        with self._lock:
            self._open()
            if (not self._require_frame_coverage or self._coverage_sealed
                    or host_verified is not True or type(expected_frames) is not int
                    or not 1 <= expected_frames <= 256 or self._pending is not None
                    or expected_frames != self._last_frame_sequence
                    or expected_frames != self._attempted + self._no_action_frames
                    or not self._durations):
                self._fail("native game frame coverage not independently complete")
            self._coverage_sealed = True

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
            real_call_start_ns = monotonic_ns()
            with self._health_lock:
                self._active_call_started_ns = real_call_start_ns
            try:
                try:
                    # Only this already-approved port is able to generate input.
                    success = self._port.send_action(action_id, hold_ms, self._aborted)
                    finished_ns = self._sample()
                    # Native return True is a limited OS/worker receipt, not a win.
                    if (success is not True or self._aborted.is_set()
                            or self._port.focus_ok() is not True
                            or self._port.all_keys_up() is not True):
                        self._fail("native game input roundtrip not confirmed")
                    if (finished_ns - now > self._max_call_ns
                            or monotonic_ns() - real_call_start_ns > self._max_call_ns):
                        # A host-injected audit clock cannot hide a genuinely
                        # over-budget native call from the monitoring lane.
                        self._fail("native game input roundtrip deadline exceeded")
                    self._decision_durations.append(ready_ns - capture_ns)
                    self._durations.append((
                        ready_ns - capture_ns,
                        finished_ns - now,
                        finished_ns - capture_ns,
                    ))
                    self._pending = None
                except Exception:
                    self._fail("native game input roundtrip failed")
            finally:
                # Drop the live lease even if the port raises or the audit
                # revokes. Host-side cancellation/physical key-up remain the
                # responsibility of the independent Windows input watchdog.
                with self._health_lock:
                    self._active_call_started_ns = None

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
        """Snapshot without blocking a health monitor behind a hung input worker.

        A worker may be waiting for its OS watchdog. Never make a monitoring
        thread wait for the same lock as that worker: with the lock busy, only
        a conservative in-flight status is available. No timing or successes
        are exposed until the callback has finished and released its keys.
        """
        if not self._lock.acquire(blocking=False):
            # Never wait for the native callback or expose unverified counters.
            if self._aborted.is_set():
                return NativeRoundtripReport("revoked", 0, 0, None, None, None)
            overdue = False
            if self._health_lock.acquire(blocking=False):
                try:
                    started = self._active_call_started_ns
                    if started is not None:
                        overdue = monotonic_ns() - started > self._max_call_ns
                finally:
                    self._health_lock.release()
            # This is a monitoring warning, NOT forced input release. The
            # separate OS watchdog must stop/release a hung input worker.
            if self._aborted.is_set():
                return NativeRoundtripReport("revoked", 0, 0, None, None, None)
            return NativeRoundtripReport(
                "host_call_overdue" if overdue else "in_flight",
                0, 0, None, None, None,
            )
        try:
            if self._aborted.is_set() or self._revoked:
                return NativeRoundtripReport(
                    "revoked", self._attempted, 0, None, None, None,
                )
            if self._final_report is not None:
                return self._final_report
            if (self._pending is not None or not self._durations
                    or (self._require_frame_coverage and not self._coverage_sealed)):
                return NativeRoundtripReport(
                    "incomplete", self._attempted, 0, None, None, None,
                )
            inference, call, total = zip(*self._durations, strict=True)
            return NativeRoundtripReport(
                "host_roundtrip_only", self._attempted, len(self._durations),
                _p95_ns(list(inference)), _p95_ns(list(call)), _p95_ns(list(total)),
                observed_frames=self._last_frame_sequence,
                no_action_frames=self._no_action_frames,
                host_frame_coverage_declared=self._coverage_sealed,
                all_frame_decision_p95_ms=(
                    _p95_ns(self._decision_durations)
                    if self._require_frame_coverage else None
                ),
            )
        finally:
            self._lock.release()

    def finalize(self) -> NativeRoundtripReport:
        """Seal only an idle host; never block the monitor on a native call."""
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("native game roundtrip still in flight")
        try:
            self._open()
            if self._require_frame_coverage and not self._coverage_sealed:
                self._fail("native frame coverage must be sealed before finalization")
            result = self.report()
            if result.status != "host_roundtrip_only":
                self._fail("incomplete native game roundtrip cannot finalize")
            self._finalized = True
            self._final_report = result
            self._durations.clear()
            self._decision_durations.clear()
            return result
        finally:
            self._lock.release()

__all__ = ["NativeRoundtripReport", "NativeGameRoundtripAudit"]
