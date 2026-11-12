"""Thread-safe telemetry for the voice speaker's output callback.

A callback timestamp means the audio backend handed a non-empty PCM block to
PortAudio's output callback. It is not a measurement of DAC, Bluetooth, room,
or listener-perceived acoustic arrival.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import threading
import time
from typing import Callable


@dataclass(frozen=True)
class PlaybackSnapshot:
    """Per-reply playback evidence; None counters mean the backend cannot report them."""

    first_playback_at: float | None
    output_callbacks: int | None
    output_callbacks_with_audio: int | None
    output_underflows: int | None  # PortAudio underflows observed while non-empty audio was emitted


class PlaybackTelemetry:
    """Small lock-protected callback counter, safe to snapshot outside the audio thread."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._callbacks = 0
            self._callbacks_with_audio = 0
            self._output_underflows = 0
            self._first_playback_at: float | None = None

    def record_callback(
        self,
        *,
        frames: int,
        emitted_frames: int,
        output_underflow: bool = False,
        at: float | None = None,
    ) -> None:
        """Record one PortAudio callback and the number of queued frames copied to output."""
        if type(frames) is not int or frames < 0:
            raise ValueError("frames must be a nonnegative integer")
        if type(emitted_frames) is not int or not 0 <= emitted_frames <= frames:
            raise ValueError("emitted_frames must be between zero and frames")
        if type(output_underflow) is not bool:
            raise ValueError("output_underflow must be boolean")
        stamp = self._clock() if at is None else at
        if type(stamp) not in (int, float) or not math.isfinite(stamp):
            raise ValueError("callback timestamp must be finite")
        with self._lock:
            self._callbacks += 1
            if emitted_frames:
                self._callbacks_with_audio += 1
                if self._first_playback_at is None:
                    self._first_playback_at = float(stamp)
            if output_underflow and emitted_frames:
                self._output_underflows += 1

    def snapshot(self) -> PlaybackSnapshot:
        with self._lock:
            return PlaybackSnapshot(
                first_playback_at=self._first_playback_at,
                output_callbacks=self._callbacks,
                output_callbacks_with_audio=self._callbacks_with_audio,
                output_underflows=self._output_underflows,
            )


__all__ = ["PlaybackSnapshot", "PlaybackTelemetry"]
