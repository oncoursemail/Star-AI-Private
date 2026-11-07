"""Read-only, fail-conservative resource recommendations for live game streaming.

No model starts, process controls, voice actions, device operations, permissions,
network requests or OBS calls. Real hardware admission remains host-owned.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

_WORKLOADS = frozenset({
    "speech", "gameplay", "vision", "research", "training", "render"
})


def _quantity(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite nonnegative number")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return value


@dataclass(frozen=True)
class StreamTelemetry:
    live: bool
    game_active: bool
    free_vram_mib: float
    total_vram_mib: float
    game_fps: float
    speech_backlog_ms: float

    def __post_init__(self) -> None:
        if type(self.live) is not bool or type(self.game_active) is not bool:
            raise ValueError("live and game_active must be explicit booleans")
        free = _quantity(self.free_vram_mib, "free_vram_mib")
        total = _quantity(self.total_vram_mib, "total_vram_mib")
        _quantity(self.game_fps, "game_fps")
        _quantity(self.speech_backlog_ms, "speech_backlog_ms")
        if total == 0 or free > total:
            raise ValueError("total_vram_mib must be positive and >= free_vram_mib")


@dataclass(frozen=True)
class WorkloadAdvice:
    allowed: bool
    profile: str  # latency, economical, offline, or deferred
    sample_fps: float
    reason: str


def advise_workload(kind: str, telemetry: StreamTelemetry | None) -> WorkloadAdvice:
    """Conservative scheduling hint. 'allowed' is NOT security authorization."""
    if kind not in _WORKLOADS:
        raise ValueError("unsupported workload")
    if telemetry is None:
        if kind in {"speech", "gameplay"}:
            return WorkloadAdvice(True, "latency", 0.0, "critical request; capacity unmeasured")
        return WorkloadAdvice(False, "deferred", 0.0, "capacity not measured")
    if not isinstance(telemetry, StreamTelemetry):
        raise TypeError("telemetry must be StreamTelemetry or None")
    if kind in {"speech", "gameplay"}:
        return WorkloadAdvice(True, "latency", 0.0, "realtime priority; upstream permissions still apply")
    if telemetry.live and kind in {"training", "render", "research"}:
        return WorkloadAdvice(False, "deferred", 0.0, "stream is live; protect gameplay and voice")
    constrained = (
        telemetry.free_vram_mib < 1536.0
        or (telemetry.game_active and telemetry.game_fps < 45.0)
        or telemetry.speech_backlog_ms > 350.0
    )
    if kind == "vision" and telemetry.live:
        if constrained:
            return WorkloadAdvice(False, "deferred", 0.0, "insufficient realtime GPU/latency headroom")
        # Deliberately sample at most 1 Hz; this is a policy cap, not a proven safe operating point.
        return WorkloadAdvice(True, "economical", 1.0, "bounded stream-time observation")
    if kind == "vision":
        return WorkloadAdvice(True, "offline", 4.0, "not broadcasting; offline sampling policy")
    if constrained:
        return WorkloadAdvice(False, "deferred", 0.0, "not enough measured headroom")
    return WorkloadAdvice(True, "offline", 0.0, "not broadcasting and adequate measured headroom")
