"""Thread-safe telemetry for the voice speaker's output callback.

When PortAudio supplies valid callback time info, the first playback timestamp
is its estimated DAC time mapped onto Python's monotonic clock. Otherwise it
falls back to callback invocation time. Neither proves acoustic arrival.
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
    output_callbacks_with_audio: int | None
    output_underflows: int | None  # PortAudio underflows observed while non-empty audio was emitted


def estimate_output_time(
    callback_monotonic: float,
    *,
    current_time: float | None,
    output_buffer_dac_time: float | None,
    max_future_s: float = 1.0,
) -> float:
    """Map PortAudio outputBufferDacTime to monotonic time; fall back safely."""
    if type(callback_monotonic) not in (int, float) or not math.isfinite(callback_monotonic):
        raise ValueError("callback_monotonic must be finite")
    if (
        type(current_time) in (int, float)
        and type(output_buffer_dac_time) in (int, float)
        and math.isfinite(current_time)
        and math.isfinite(output_buffer_dac_time)
        and type(max_future_s) in (int, float)
        and math.isfinite(max_future_s)
        and 0.0 < max_future_s <= 5.0
    ):
        delta = float(output_buffer_dac_time) - float(current_time)
        if 0.0 <= delta <= max_future_s:
            return float(callback_monotonic) + delta
    return float(callback_monotonic)


class PlaybackTelemetry:
    """Small lock-protected callback counter, safe to snapshot outside the audio thread."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
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
        """Record one output callback and the number of queued frames copied to output."""
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
                output_callbacks_with_audio=self._callbacks_with_audio,
                output_underflows=self._output_underflows,
            )


__all__ = ["PlaybackSnapshot", "PlaybackTelemetry", "estimate_output_time"]
