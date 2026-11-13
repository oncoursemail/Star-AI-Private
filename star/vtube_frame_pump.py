"""Latest-wins, interruption-safe VTube Studio frame scheduler.

The pump isolates synchronous WebSocket writes from audio, render, and game
threads. It holds at most one pending frame, drops superseded/stale frames,
and provides a flush barrier that waits for any in-flight send to finish.
It does not capture audio, generate motion, authenticate VTube Studio, start
playback, or decide whether a StagePlan is authorized.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from threading import Condition, Thread, current_thread
import time
from typing import Callable, Protocol, cast

from .stream_motion import MotionFrame
from .stream_stage import StagePlan

_EPOCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MAX_AUDIO_S = 15.0
_MAX_USED_EPOCHS = 4096


class FrameHost(Protocol):
    @property
    def ready(self) -> bool: ...

    def send_frame(
        self,
        plan: StagePlan,
        *,
        playback_epoch: str,
        frame: MotionFrame,
        audible_cursor_s: float,
        sampled_ms: float,
    ) -> bool: ...


@dataclass(frozen=True)
class _FrameRequest:
    plan: StagePlan
    epoch: str
    frame: MotionFrame
    audible_cursor_s: float
    sampled_ms: float


def _finite(value: object, label: str, low: float, high: float) -> float:
    if type(value) is int:
        number = float(cast(int, value))
    elif type(value) is float:
        number = cast(float, value)
    else:
        raise ValueError(f"{label} must be a finite number")
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{label} is outside its supported range")
    return number


class VTubeFramePump:
    """Single-worker, one-slot latest-wins scheduler for Live2D parameter frames.

    The trusted host must bind the same plan/epoch in VTubeLive2DBridge before
    arming this pump. Call submit() from a host animation-scheduler thread; it
    never performs socket I/O. Call flush_epoch() only after the stage has been
    revoked and physical playback for that epoch has stopped. A successful
    flush is a barrier: no send for that epoch remains in flight when it
    returns, so the host may then send the neutral avatar reset.
    """

    def __init__(
        self,
        host: FrameHost,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        max_frame_age_ms: float = 100.0,
        flush_timeout_ms: float = 250.0,
    ) -> None:
        if not callable(getattr(host, "send_frame", None)):
            raise TypeError("host must provide send_frame")
        if not callable(monotonic):
            raise TypeError("monotonic must be callable")
        _finite(max_frame_age_ms, "max_frame_age_ms", 1.0, 100.0)
        _finite(flush_timeout_ms, "flush_timeout_ms", 20.0, 1000.0)
        self._host = host
        self._clock = monotonic
        self._max_age = float(max_frame_age_ms)
        self._flush_timeout = float(flush_timeout_ms)
        self._condition = Condition()
        self._thread: Thread | None = None
        self._started = False
        self._closing = False
        self._fault = False
        self._active: tuple[StagePlan, str] | None = None
        self._pending: _FrameRequest | None = None
        self._in_flight_epoch: str | None = None
        self._last_submitted_s = -1.0
        self._used_epochs: set[str] = set()
        self._counts = {
            "submitted": 0,
            "sent": 0,
            "replaced": 0,
            "stale_dropped": 0,
            "rejected": 0,
            "send_failures": 0,
            "flush_timeouts": 0,
        }

    def _now_ms(self) -> float:
        value = self._clock()
        if type(value) not in (int, float):
            raise ValueError("trusted monotonic clock is invalid")
        number = float(value) * 1000.0
        if not math.isfinite(number) or number < 0:
            raise ValueError("trusted monotonic clock is invalid")
        return number

    def start(self) -> None:
        with self._condition:
            if self._started:
                return
            if self._closing or self._fault:
                raise RuntimeError("closed or faulted frame pump cannot start")
            self._thread = Thread(
                target=self._run,
                name="star-vtube-frame-pump",
                daemon=True,
            )
            self._started = True
            self._thread.start()

    def arm(self, plan: StagePlan, *, playback_epoch: str) -> bool:
        if type(plan) is not StagePlan:
            raise TypeError("plan must be a StagePlan")
        if type(playback_epoch) is not str or not _EPOCH.fullmatch(playback_epoch):
            raise ValueError("invalid playback epoch")
        with self._condition:
            if (
                not self._started
                or self._closing
                or self._fault
                or self._active is not None
                or self._pending is not None
                or self._in_flight_epoch is not None
            ):
                return False
            if playback_epoch in self._used_epochs:
                return False
            if len(self._used_epochs) >= _MAX_USED_EPOCHS:
                self._fault = True
                return False
            try:
                ready = self._host.ready is True
            except Exception:
                ready = False
            if not ready:
                return False
            self._used_epochs.add(playback_epoch)
            self._active = (plan, playback_epoch)
            self._last_submitted_s = -1.0
            return True

    def submit(
        self,
        plan: StagePlan,
        *,
        playback_epoch: str,
        frame: MotionFrame,
        audible_cursor_s: float,
        sampled_ms: float,
    ) -> bool:
        if type(plan) is not StagePlan or type(frame) is not MotionFrame:
            raise TypeError("submit requires a StagePlan and MotionFrame")
        if type(playback_epoch) is not str or not _EPOCH.fullmatch(playback_epoch):
            raise ValueError("invalid playback epoch")
        cursor = _finite(audible_cursor_s, "audible_cursor_s", 0.0, _MAX_AUDIO_S)
        stamp = _finite(sampled_ms, "sampled_ms", 0.0, 1e13)
        frame_at = _finite(frame.at_s, "frame.at_s", 0.0, _MAX_AUDIO_S)
        if frame_at > cursor or cursor - frame_at > 0.100:
            with self._condition:
                self._counts["rejected"] += 1
            return False
        try:
            age = self._now_ms() - stamp
        except ValueError:
            with self._condition:
                self._counts["rejected"] += 1
            return False
        if not 0.0 <= age <= self._max_age:
            with self._condition:
                self._counts["stale_dropped"] += 1
            return False

        request = _FrameRequest(plan, playback_epoch, frame, cursor, stamp)
        with self._condition:
            if (
                not self._started
                or self._closing
                or self._fault
                or self._active is None
                or self._active[0] is not plan
                or self._active[1] != playback_epoch
            ):
                self._counts["rejected"] += 1
                return False
            if frame_at <= self._last_submitted_s:
                self._counts["rejected"] += 1
                return False
            self._last_submitted_s = frame_at
            if self._pending is not None:
                if (
                    self._pending.epoch != playback_epoch
                    or self._pending.plan is not plan
                ):
                    self._counts["rejected"] += 1
                    return False
                self._pending = None
                self._counts["replaced"] += 1
                self._counts["stale_dropped"] += 1
            self._pending = request
            self._counts["submitted"] += 1
            self._condition.notify()
            return True

    def flush_epoch(
        self,
        playback_epoch: str,
        *,
        timeout_ms: float | None = None,
    ) -> bool:
        if type(playback_epoch) is not str or not _EPOCH.fullmatch(playback_epoch):
            raise ValueError("invalid playback epoch")
        timeout = (
            self._flush_timeout
            if timeout_ms is None
            else _finite(timeout_ms, "timeout_ms", 1.0, 5000.0)
        )
        deadline = time.monotonic() + timeout / 1000.0
        with self._condition:
            if self._active is not None and self._active[1] != playback_epoch:
                return False
            # Revoke submissions before waiting for a send already in progress.
            if self._active is not None:
                self._active = None
            if self._pending is not None and self._pending.epoch == playback_epoch:
                self._pending = None
                self._counts["stale_dropped"] += 1
            self._condition.notify_all()
            while self._in_flight_epoch == playback_epoch:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._counts["flush_timeouts"] += 1
                    self._fault = True
                    return False
                self._condition.wait(remaining)
            return not self._fault

    def _run(self) -> None:
        while True:
            with self._condition:
                while self._pending is None and not self._closing:
                    self._condition.wait()
                if self._closing and self._pending is None:
                    return
                request = self._pending
                self._pending = None
                if request is None:
                    continue
                if (
                    self._active is None
                    or self._active[0] is not request.plan
                    or self._active[1] != request.epoch
                    or self._fault
                ):
                    self._counts["stale_dropped"] += 1
                    continue
                self._in_flight_epoch = request.epoch
            try:
                age = self._now_ms() - request.sampled_ms
                if not 0.0 <= age <= self._max_age:
                    with self._condition:
                        self._counts["stale_dropped"] += 1
                else:
                    sent = self._host.send_frame(
                        request.plan,
                        playback_epoch=request.epoch,
                        frame=request.frame,
                        audible_cursor_s=request.audible_cursor_s,
                        sampled_ms=request.sampled_ms,
                    )
                    with self._condition:
                        if sent is True:
                            self._counts["sent"] += 1
                        else:
                            self._counts["stale_dropped"] += 1
            except Exception:
                with self._condition:
                    self._counts["send_failures"] += 1
                    self._fault = True
                    self._active = None
                    if self._pending is not None:
                        self._pending = None
                        self._counts["stale_dropped"] += 1
            finally:
                with self._condition:
                    self._in_flight_epoch = None
                    self._condition.notify_all()

    def metrics(self) -> dict[str, int | bool]:
        with self._condition:
            return {
                **self._counts,
                "running": self._started and not self._closing,
                "active": self._active is not None,
                "pending": self._pending is not None,
                "in_flight": self._in_flight_epoch is not None,
                "fault": self._fault,
            }

    def close(self, *, timeout_ms: float = 1000.0) -> bool:
        timeout = _finite(timeout_ms, "timeout_ms", 1.0, 5000.0)
        with self._condition:
            self._closing = True
            self._active = None
            if self._pending is not None:
                self._pending = None
                self._counts["stale_dropped"] += 1
            thread = self._thread
            self._condition.notify_all()
        if thread is not None and thread is not current_thread():
            thread.join(timeout / 1000.0)
            if thread.is_alive():
                with self._condition:
                    self._fault = True
                return False
        with self._condition:
            self._started = False
            return self._in_flight_epoch is None


__all__ = ["FrameHost", "VTubeFramePump"]
