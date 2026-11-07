"""Adaptive, host-measured screenshot budget for STAR's private Roblox playtests.

This schedules *read-only* StudioVisualObserver observations. It is not an
input permission, screenshot/video recorder, GPU benchmark, skill scorer, or
a background worker. The embedding host owns trusted telemetry, monotonic
clock, Studio authorization and an independent keyboard-release watchdog.

Measured game/voice pressure takes priority over vision. Duplicate scenes
and failing sensors back off to avoid wasting CPU/GPU or spamming Studio.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import math
import time
from typing import Callable

from .stream_budget import StreamTelemetry, advise_workload
from .studio_visual_evidence import (
    ObservationRejected, StudioVisualObserver, VisualEvidence,
)


def _clock_ms(clock: Callable[[], float]) -> float:
    value = clock()
    if (type(value) not in (int, float) or
            not math.isfinite(float(value)) or
            not 0 <= value <= 1e13):
        raise ValueError("invalid trusted monotonic clock")
    return float(value)


@dataclass(frozen=True)
class VisionSample:
    """An observation or a bounded non-sensitive skip reason, NEVER authority."""
    attempted: bool
    reason: str
    evidence: VisualEvidence | None = None


class StudioVisionQoS:
    """Fail-conservative visual inference rate governor.

    The trusted host supplies *measured* StreamTelemetry. Missing telemetry,
    an inactive game, or performance pressure must not initiate a screenshot.
    The observer separately checks owner opt-in, private focus and play mode.

    No sleep, polling worker, disk writes or arbitrary tool/model calls.
    Scheduling uses completion times so a slow assessment cannot burst-capture
    a backlog. Live observations are capped at 1 Hz; offline practice at 4 Hz.
    """

    def __init__(self, observer: StudioVisualObserver, *,
                 clock_ms: Callable[[], float] = lambda: time.monotonic() * 1000,
                 duplicate_backoff_cap_ms: int = 4000,
                 error_backoff_cap_ms: int = 8000) -> None:
        if not isinstance(observer, StudioVisualObserver):
            raise TypeError("observer must be a real StudioVisualObserver")
        if not callable(clock_ms):
            raise TypeError("clock_ms must be host-owned")
        if (type(duplicate_backoff_cap_ms) is not int
                or not 1000 <= duplicate_backoff_cap_ms <= 15000
                or type(error_backoff_cap_ms) is not int
                or not 1000 <= error_backoff_cap_ms <= 30000):
            raise ValueError("invalid backoff bounds")
        self._observer = observer
        self._clock = clock_ms
        self._duplicate_cap = duplicate_backoff_cap_ms
        self._error_cap = error_backoff_cap_ms
        self._lock = asyncio.Lock()
        self._next_ms = 0.0
        self._last_ms: float | None = None
        self._duplicates = 0
        self._failures = 0
        self._counts = {
            "captured": 0, "changed": 0, "duplicates": 0,
            "pressure_skips": 0, "cadence_skips": 0, "sensor_failures": 0,
        }

    async def sample(self, telemetry: StreamTelemetry | None) -> VisionSample:
        # This object is constructed only from the trusted host's own measured
        # telemetry. Game text, Twitch chat or the model must never set it.
        if telemetry is not None and not isinstance(telemetry, StreamTelemetry):
            raise TypeError("telemetry must be host-measured StreamTelemetry")
        async with self._lock:
            now = _clock_ms(self._clock)
            if self._last_ms is not None and now < self._last_ms:
                # Never re-use tickets/cadence after an invalid host clock.
                self._next_ms = float("inf")
                raise ValueError("host monotonic clock reversed")
            self._last_ms = now

            if telemetry is None or not telemetry.game_active:
                self._counts["pressure_skips"] += 1
                return VisionSample(False, "game_telemetry_unavailable_or_inactive")
            advice = advise_workload("vision", telemetry)
            if not advice.allowed:
                self._counts["pressure_skips"] += 1
                return VisionSample(False, "stream_vision_deferred")
            if telemetry.game_fps < 30 or telemetry.speech_backlog_ms > 350:
                self._counts["pressure_skips"] += 1
                return VisionSample(False, "realtime_game_or_voice_pressure")
            if now < self._next_ms:
                self._counts["cadence_skips"] += 1
                return VisionSample(False, "visual_sampling_cooldown")

            # Even when called faster by an outer loop, only the observer's
            # already-approved read-only MCP API may capture any image.
            try:
                evidence = await self._observer.observe()
            except (ObservationRejected, PermissionError):
                self._failures = min(self._failures + 1, 16)
                self._duplicates = 0
                finish = _clock_ms(self._clock)
                if finish < now:
                    self._next_ms = float("inf")
                    raise ValueError("host clock reversed during capture")
                delay = min(self._error_cap, 1000 * 2 ** (self._failures - 1))
                self._next_ms = finish + delay
                self._counts["sensor_failures"] += 1
                return VisionSample(True, "visual_observation_unavailable")

            finish = _clock_ms(self._clock)
            if finish < now:
                self._next_ms = float("inf")
                raise ValueError("host clock reversed during capture")
            self._failures = 0
            self._counts["captured"] += 1
            if evidence.changed:
                self._duplicates = 0
                self._counts["changed"] += 1
            else:
                self._duplicates = min(self._duplicates + 1, 16)
                self._counts["duplicates"] += 1
            # Additional backoff on repeated identical screenshots: an idle
            # stream does not require 1 MB/frame * 1 fps worth of inference.
            base_ms = 1000 if telemetry.live else 250
            if self._duplicates:
                delay = min(self._duplicate_cap,
                            base_ms * (2 ** self._duplicates))
            else:
                delay = base_ms
            self._next_ms = finish + delay
            return VisionSample(True, "new_visual_evidence" if evidence.changed
                                else "identical_scene_no_new_action_evidence",
                                evidence)

    def metrics(self) -> dict[str, int | bool]:
        """No scene names, game IDs, images, speech or player information."""
        return {**self._counts, "duplicates_in_row": self._duplicates,
                "sensor_failures_in_row": self._failures,
                "observer_armed": bool(self._observer.metrics()["armed"])}


__all__ = ["StudioVisionQoS", "VisionSample"]
