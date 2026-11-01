"""Strict local adapter for OBS WebSocket v5 GetStats *frame counters*.

The host calls an authenticated loopback GetStats and provides only the
responseData object. We never open a socket, store OBS credentials, read scenes
or expose media. Rolling counter deltas—not OBS lifetime cumulative rates—are
converted into admission policy's render/output-lag percentages.

OBS output-thread skipped frames are an *output/encoding pressure proxy*, not
proof of a hardware encoder's precise failure mode. Independent OBS logs and
actual recordings are required to attribute performance problems.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from threading import RLock
from typing import Mapping, cast

_MAX_COUNTER = 2**53 - 1  # integer precision in JSON/JavaScript transports
_MAX_CLOCK_MS = 1e13


def _valid_counter(value: object) -> int:
    if type(value) not in (int, float):
        raise ValueError("OBS counters must be nonnegative exact integers")
    try:
        v = float(cast(int | float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError("OBS counters must be nonnegative exact integers") from exc
    if not math.isfinite(v) or v < 0 or v > _MAX_COUNTER or not v.is_integer():
        raise ValueError("OBS counters must be nonnegative exact integers")
    return int(v)


def _valid_clock(value: object) -> float:
    if type(value) not in (float, int):
        raise ValueError("host time must be finite and nonnegative")
    try:
        x = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError("host time must be finite and nonnegative") from exc
    if not math.isfinite(x) or not 0 <= x <= _MAX_CLOCK_MS:
        raise ValueError("host time must be finite and nonnegative")
    return x


@dataclass(frozen=True)
class ObsLagWindow:
    observed_ms: float
    render_lag_pct: float
    output_lag_pct: float
    window_ms: float


class ObsStatsWindow:
    """Bounded window on one local OBS instance; no I/O or task control."""

    def __init__(self, *, min_window_ms: int = 250,
                 max_window_ms: int = 5000) -> None:
        if (type(min_window_ms) is not int or type(max_window_ms) is not int
                or not 100 <= min_window_ms < max_window_ms <= 30000):
            raise ValueError("invalid OBS sampling interval")
        self._min_ms = min_window_ms
        self._max_ms = max_window_ms
        self._lock = RLock()
        self._before: tuple[float, tuple[int, int, int, int]] | None = None
        self._last_seen_ms: float | None = None
        self._counts = {"samples": 0, "windows": 0, "rejected": 0, "resets": 0}

    def reset(self) -> None:
        """Call on OBS restart, reconnect, or recording/stream session change."""
        with self._lock:
            self._before = None
            self._last_seen_ms = None

    def ingest(self, data: Mapping[str, object], *, host_ms: float,
               host_verified: bool = False) -> ObsLagWindow | None:
        """Return a usable window only after two trusted, ordered samples.

        data is specifically OBS WebSocket v5 GetStats responseData. The
        host must authenticate and authorize the source before calling.
        """
        now = _valid_clock(host_ms)
        if type(host_verified) is not bool:
            raise ValueError("host_verified must be a strict boolean")
        if not isinstance(data, Mapping):
            raise TypeError("GetStats responseData must be a mapping")
        with self._lock:
            if not host_verified or (self._last_seen_ms is not None and
                                     now <= self._last_seen_ms):
                self._counts["rejected"] += 1
                return None
            # Extract only four expected fields, never persist arbitrary OBS
            # response data (e.g. third-party plugin fields or identifying text).
            # Explicit tuple fields keep static types precise and prevent
            # accidental schema broadening if OBS adds additional counters.
            values = (
                _valid_counter(data.get("renderSkippedFrames")),
                _valid_counter(data.get("renderTotalFrames")),
                _valid_counter(data.get("outputSkippedFrames")),
                _valid_counter(data.get("outputTotalFrames")),
            )
            self._last_seen_ms = now
            self._counts["samples"] += 1
            prev = self._before
            if prev is None:
                self._before = (now, values)
                return None
            old_ms, old = prev
            elapsed = now - old_ms
            if (elapsed > self._max_ms or
                    any(new < prior for new, prior in zip(values, old))):
                self._counts["resets"] += 1
                self._before = (now, values)
                return None
            if elapsed < self._min_ms:
                return None  # maintain earlier baseline to avoid tiny windows
            self._before = (now, values)
            drskip, drtotal, doskip, dototal = (
                new - prior for new, prior in zip(values, old)
            )
            # OBS counts skipped frames *within* its total frame count.
            # Its own status bar computes skipped / total, not
            # skipped / (skipped + total). The latter underreports GPU
            # pressure precisely when the stream is struggling.
            if drtotal == 0 or dototal == 0:
                return None  # no running OBS output, not zero-lag proof
            if drskip > drtotal or doskip > dototal:
                # Impossible within one OBS counter epoch: do not treat it
                # as a valid percentage or healthy streaming evidence.
                # Rebase on this attested sample and require another one.
                self._counts["resets"] += 1
                return None
            self._counts["windows"] += 1
            return ObsLagWindow(
                observed_ms=now,
                render_lag_pct=100.0 * drskip / drtotal,
                output_lag_pct=100.0 * doskip / dototal,
                window_ms=elapsed,
            )

    def metrics(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)


__all__ = ["ObsLagWindow", "ObsStatsWindow"]
