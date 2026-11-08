"""Fail-closed OBS v5 GetStreamStatus network-drop interval sampler.

Only a trusted host with an authenticated OBS websocket connection may call
this read-only adapter. It never opens a connection, starts a stream, exposes
stream keys, or treats absent/idle stream telemetry as zero packet loss.

GetStreamStatus outputSkippedFrames counts network-dropped frames and
outputTotalFrames counts delivered frames. The interval denominator is
delivered + dropped attempts; never use the lifetime aggregate to authorize
optional VTuber work.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Mapping

from .obs_stats_window import _valid_clock, _valid_counter


@dataclass(frozen=True)
class ObsStreamLossWindow:
    observed_ms: float
    window_ms: float
    network_dropped_pct: float
    delivered_frames: int
    dropped_frames: int


class ObsStreamLossSampler:
    """Session-local, monotonic, trusted OBS streaming drop-rate intervals."""

    def __init__(
        self,
        *,
        min_window_ms: int = 250,
        max_window_ms: int = 5000,
        min_attempted_frames: int = 10,
    ) -> None:
        if (
            type(min_window_ms) is not int
            or type(max_window_ms) is not int
            or not 100 <= min_window_ms < max_window_ms <= 30000
        ):
            raise ValueError("invalid OBS stream sampling interval")
        if type(min_attempted_frames) is not int or not 1 <= min_attempted_frames <= 10000:
            raise ValueError("min_attempted_frames must be 1..10000")
        self._min_ms = min_window_ms
        self._max_ms = max_window_ms
        self._min_frames = min_attempted_frames
        self._lock = RLock()
        self._before: tuple[float, int, int, int] | None = None
        self._last_seen_ms: float | None = None
        self._counts = {"samples": 0, "windows": 0, "rejected": 0, "resets": 0}

    def _reset(self) -> None:
        self._before = None
        self._last_seen_ms = None

    def reset(self) -> None:
        """Required on OBS reconnect, output restart, or observer identity change."""
        with self._lock:
            self._reset()
            self._counts["resets"] += 1

    def ingest(
        self,
        data: Mapping[str, object],
        *,
        host_ms: float,
        host_verified: bool = False,
    ) -> ObsStreamLossWindow | None:
        """Observe authenticated GetStreamStatus responseData, not a model summary.

        Any missing/invalid/disconnected/reconnecting reading destroys the old
        baseline. A new legitimate stream needs two valid ordered samples
        before it can produce nonzero OR zero network-loss evidence.
        """
        with self._lock:
            try:
                now = _valid_clock(host_ms)
                if host_verified is not True:
                    raise ValueError("authenticated local OBS stream status required")
                if not isinstance(data, Mapping):
                    raise TypeError("GetStreamStatus responseData must be a mapping")
                if self._last_seen_ms is not None and now <= self._last_seen_ms:
                    raise ValueError("replayed or reversed host stream observation")
                if type(data.get("outputActive")) is not bool:
                    raise ValueError("outputActive must be OBS boolean")
                if type(data.get("outputReconnecting")) is not bool:
                    raise ValueError("outputReconnecting must be OBS boolean")
                if not data["outputActive"] or data["outputReconnecting"]:
                    raise ValueError("stream inactive or reconnecting")
                duration = _valid_counter(data.get("outputDuration"))
                dropped = _valid_counter(data.get("outputSkippedFrames"))
                delivered = _valid_counter(data.get("outputTotalFrames"))
            except (TypeError, ValueError, OverflowError):
                self._counts["rejected"] += 1
                self._counts["resets"] += 1
                self._reset()
                return None

            self._counts["samples"] += 1
            self._last_seen_ms = now
            prev = self._before
            self._before = (now, duration, dropped, delivered)
            if prev is None:
                return None
            old_ms, old_duration, old_dropped, old_delivered = prev
            elapsed = now - old_ms
            if (
                elapsed > self._max_ms
                or duration <= old_duration
                or dropped < old_dropped
                or delivered < old_delivered
                or abs((duration - old_duration) - elapsed) > max(250.0, elapsed * 0.5)
            ):
                self._counts["resets"] += 1
                return None
            if elapsed < self._min_ms:
                self._before = prev
                return None
            delta_dropped = dropped - old_dropped
            delta_delivered = delivered - old_delivered
            attempted = delta_dropped + delta_delivered
            if attempted < self._min_frames:
                return None
            self._counts["windows"] += 1
            return ObsStreamLossWindow(
                observed_ms=now,
                window_ms=elapsed,
                network_dropped_pct=100 * delta_dropped / attempted,
                delivered_frames=delta_delivered,
                dropped_frames=delta_dropped,
            )

    def metrics(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)


__all__ = ["ObsStreamLossWindow", "ObsStreamLossSampler"]
