"""A bounded, memory-only desktop capture worker. Capture rate is not model perception rate."""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Callable

from ..play.capture import Frame, FrameSource


class LatestFrameCapture:
    """Own a source on one thread and overwrite one latest-frame slot.

    A blocked native grab cannot be forcibly killed. close() invalidates immediately,
    returns False on a bounded join timeout, and the worker closes its source when it returns.
    """

    def __init__(self, source_factory: Callable[[], FrameSource], *, hz: float = 30,
                 max_age_s: float = .5, stopped: Callable[[], bool] | None = None) -> None:
        if not math.isfinite(hz) or not 0 < hz <= 60:
            raise ValueError('capture hz must be finite and between 0 and 60')
        if not math.isfinite(max_age_s) or not 0 < max_age_s <= 10:
            raise ValueError('max_age_s must be finite and between 0 and 10')
        self._factory, self.hz, self.max_age_s = source_factory, hz, max_age_s
        self._stopped = stopped or (lambda: False)
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame: Frame | None = None
        self._started: float | None = None
        self._ended: float | None = None
        self._last_read = -1
        self._polls = self._frames = self._overwritten = self._no_update = 0
        self._durations: deque[float] = deque(maxlen=300)
        self._backend = ''
        self._timestamp_kind = ''
        self._error = ''
        self._closed = False
        self._cleanup_complete = False

    def _blocked(self) -> bool:
        try:
            return self._stop.is_set() or bool(self._stopped())
        except Exception:
            return True

    def start(self) -> None:
        blocked = self._blocked()
        with self._condition:
            if self._closed:
                raise RuntimeError('capture is closed')
            if self._thread is not None:
                return
            if blocked or self._stop.is_set():
                return
            self._started = time.perf_counter()
            thread = self._thread = threading.Thread(target=self._run, name='desktop-capture', daemon=True)
        try:
            thread.start()
        except BaseException as exc:
            self._stop.set()
            with self._condition:
                # KeyboardInterrupt can arrive after the OS thread launched.
                # Keep uncertain/started workers pending until their own finally.
                if thread.ident is None and isinstance(exc, Exception):
                    self._thread = None
                    self._cleanup_complete = True
                    self._ended = time.perf_counter()
                self._closed = True
                self._error = type(exc).__name__
                self._condition.notify_all()
            raise

    def _run(self) -> None:
        source = None
        try:
            if self._blocked():
                return
            import numpy as np
            if self._blocked():
                return
            source = self._factory()
            with self._condition:
                self._backend = source.name
                self._timestamp_kind = getattr(source, 'timestamp_kind', 'sample_started')
            period = 1 / self.hz
            while not self._blocked():
                began = time.perf_counter()
                frame = source.grab()
                finished = time.perf_counter()
                if self._blocked():
                    break
                image = None
                if frame is not None:
                    if not math.isfinite(frame.t) or frame.t > finished:
                        raise ValueError('invalid frame clock')
                    # Copy without the mailbox lock: native conversion may stall.
                    image = np.frombuffer(frame.image.tobytes(), dtype=frame.image.dtype).reshape(frame.image.shape)
                blocked = self._blocked()
                with self._condition:
                    self._polls += 1
                    self._durations.append((finished - began) * 1000)
                    if blocked or self._stop.is_set() or self._closed:
                        break
                    if frame is None or image is None:
                        self._no_update += 1
                    else:
                        if self._frame is not None and self._frame.index != self._last_read:
                            self._overwritten += 1
                        self._frames += 1
                        self._frame = Frame(self._frames, frame.t, image)
                        self._condition.notify_all()
                deadline = began + period
                while not self._blocked():
                    remaining = deadline - time.perf_counter()
                    if remaining <= 0:
                        break
                    # Event.wait has coarse timer pacing on Windows; short sleeps
                    # use Python's process-local timer and keep cancellation polled.
                    time.sleep(min(remaining, .005))
        except Exception as exc:
            with self._condition:
                self._error = type(exc).__name__
        finally:
            released = True
            if source is not None:
                try:
                    source.close()
                except Exception as exc:
                    released = False
                    with self._condition:
                        self._error = type(exc).__name__
            with self._condition:
                self._frame = None
                self._ended = time.perf_counter()
                self._cleanup_complete = released
                self._closed = True
                self._condition.notify_all()

    def grab(self, *, timeout: float = 0) -> Frame | None:
        if not math.isfinite(timeout) or not 0 <= timeout <= 5:
            raise ValueError('timeout must be finite and between 0 and 5')
        deadline = time.perf_counter() + timeout
        while True:
            blocked = self._blocked()
            with self._condition:
                if self._closed or blocked or self._stop.is_set():
                    self._frame = None
                    return None
                frame = self._frame
                if frame is not None and 0 <= time.perf_counter() - frame.t <= self.max_age_s:
                    self._last_read = frame.index
                    return frame
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    return None
                self._condition.wait(min(remaining, .05))

    def close(self, timeout: float = 1) -> bool:
        if not math.isfinite(timeout) or not 0 <= timeout <= 5:
            raise ValueError('timeout must be finite and between 0 and 5')
        self._stop.set()
        with self._condition:
            self._closed = True
            self._frame = None
            self._condition.notify_all()
            thread = self._thread
            if thread is None:
                self._cleanup_complete = True
        if thread is not None and thread is not threading.current_thread() and thread.ident is not None:
            thread.join(timeout)
        with self._condition:
            return self._cleanup_complete

    def status(self) -> dict:
        blocked = self._blocked()
        with self._condition:
            now = time.perf_counter()
            elapsed = max(.000001, (self._ended or now) - self._started) if self._started is not None else 0
            age = max(0, now - self._frame.t) if self._frame is not None else None
            available = not self._closed and not blocked and age is not None and age <= self.max_age_s
            samples = sorted(self._durations)
            return {'backend': self._backend, 'target_hz': self.hz, 'polls': self._polls,
                    'timestamp_kind': self._timestamp_kind, 'pixel_change_rate_measured': False,
                    'new_frames': self._frames, 'no_update': self._no_update,
                    'overwritten_unread': self._overwritten, 'buffered_frames': int(available),
                    'capture_poll_hz': self._polls / elapsed if elapsed else 0,
                    'capture_new_frame_hz': self._frames / elapsed if elapsed else 0,
                    'frame_age_ms': age * 1000 if age is not None else None,
                    'capture_p95_ms': samples[min(len(samples) - 1, int(len(samples) * .95))] if samples else None,
                    'available': available, 'closed': self._closed,
                    'cleanup_complete': self._cleanup_complete, 'error_type': self._error,
                    'perception_connected': False}
