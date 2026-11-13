"""Conservative admission policy for STAR's optional background workloads.

This module is deliberately pure: the desktop host supplies a fresh resource
snapshot and calibrated workload estimates. It does not probe hardware, launch
workers, reserve memory, or control real-time processes.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math


class WorkloadKind(str, Enum):
    """Trusted host-assigned workload classes."""

    BACKGROUND_REASONING = "background_reasoning"
    RESEARCH = "research"
    ASSET_GENERATION = "asset_generation"
    VIDEO_GENERATION = "video_generation"
    MODEL_TRAINING = "model_training"
    INDEX_BUILD = "index_build"
    MAINTENANCE = "maintenance"
    FOREGROUND_INFERENCE = "foreground_inference"
    REALTIME_AUDIO = "realtime_audio"
    TTS_PLAYBACK = "tts_playback"
    GAME_INPUT = "game_input"
    OBS_CAPTURE = "obs_capture"


class AdmissionAction(str, Enum):
    """A decision for the caller; PROTECTED is a separate scheduling lane."""

    ALLOW = "allow"
    DEFER = "defer"
    PROTECTED = "protected"


def _number(value: object, name: str, *, minimum: float, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    try:
        valid = math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid or value < minimum or (maximum is not None and value > maximum):
        if maximum is None:
            raise ValueError(f"{name} must be finite and at least {minimum}")
        raise ValueError(f"{name} must be finite and between {minimum} and {maximum}")
    return float(value)


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer at least {minimum}")
    return value


@dataclass(frozen=True)
class ResourceSnapshot:
    """One host-collected sample; timestamps use the same monotonic clock as evaluate()."""

    observed_at: float
    cpu_percent: float
    available_ram_mb: int
    available_vram_mb: int | None = None
    gpu_percent: float | None = None
    game_active: bool = False
    game_fps: float | None = None
    audio_underruns: int = 0
    obs_dropped_frames: int = 0
    obs_total_frames: int = 0
    window_seconds: float = 5.0

    def __post_init__(self) -> None:
        _number(self.observed_at, "observed_at", minimum=0)
        _number(self.cpu_percent, "cpu_percent", minimum=0, maximum=100)
        _integer(self.available_ram_mb, "available_ram_mb")
        if self.available_vram_mb is not None:
            _integer(self.available_vram_mb, "available_vram_mb")
        if self.gpu_percent is not None:
            _number(self.gpu_percent, "gpu_percent", minimum=0, maximum=100)
        if type(self.game_active) is not bool:
            raise TypeError("game_active must be a boolean")
        if self.game_fps is not None:
            _number(self.game_fps, "game_fps", minimum=0, maximum=1000)
        _integer(self.audio_underruns, "audio_underruns")
        _integer(self.obs_dropped_frames, "obs_dropped_frames")
        _integer(self.obs_total_frames, "obs_total_frames")
        if self.obs_dropped_frames > self.obs_total_frames:
            raise ValueError("OBS dropped frames cannot exceed total frames")
        _number(self.window_seconds, "window_seconds", minimum=0.001)


@dataclass(frozen=True)
class WorkloadRequest:
    """Resource estimate supplied by a trusted scheduler, never by user/viewer text."""

    request_id: str
    kind: WorkloadKind
    estimated_cpu_percent: float
    estimated_ram_mb: int
    estimated_vram_mb: int = 0
    estimated_gpu_percent: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str):
            raise TypeError("request_id must be a string")
        request_id = self.request_id.strip()
        if not request_id or len(request_id) > 128 or "\x00" in request_id:
            raise ValueError("request_id must be non-empty and at most 128 characters")
        if not isinstance(self.kind, WorkloadKind):
            raise TypeError("kind must be a WorkloadKind assigned by the host")
        _number(self.estimated_cpu_percent, "estimated_cpu_percent", minimum=0, maximum=100)
        _integer(self.estimated_ram_mb, "estimated_ram_mb")
        _integer(self.estimated_vram_mb, "estimated_vram_mb")
        _number(self.estimated_gpu_percent, "estimated_gpu_percent", minimum=0, maximum=100)


@dataclass(frozen=True)
class AdmissionDecision:
    action: AdmissionAction
    reason: str
    retry_after_seconds: float | None = None


@dataclass(frozen=True)
class AdmissionPolicy:
    """Conservative thresholds; tune from measured hardware, not model marketing."""

    max_snapshot_age_seconds: float = 3.0
    future_clock_skew_seconds: float = 0.25
    max_cpu_percent_after_admission: float = 82.0
    min_available_ram_mb: int = 2048
    min_available_vram_mb: int = 1536
    max_gpu_percent_after_admission: float = 82.0
    min_game_fps: float = 55.0
    max_obs_drop_rate: float = 0.01
    min_obs_frames_for_drop_rate: int = 120
    retry_after_seconds: float = 2.0

    def __post_init__(self) -> None:
        _number(self.max_snapshot_age_seconds, "max_snapshot_age_seconds", minimum=0.001)
        _number(self.future_clock_skew_seconds, "future_clock_skew_seconds", minimum=0)
        _number(self.max_cpu_percent_after_admission, "max_cpu_percent_after_admission",
                minimum=0, maximum=100)
        _integer(self.min_available_ram_mb, "min_available_ram_mb")
        _integer(self.min_available_vram_mb, "min_available_vram_mb")
        _number(self.max_gpu_percent_after_admission, "max_gpu_percent_after_admission",
                minimum=0, maximum=100)
        _number(self.min_game_fps, "min_game_fps", minimum=0, maximum=1000)
        _number(self.max_obs_drop_rate, "max_obs_drop_rate", minimum=0, maximum=1)
        _integer(self.min_obs_frames_for_drop_rate, "min_obs_frames_for_drop_rate", minimum=1)
        _number(self.retry_after_seconds, "retry_after_seconds", minimum=0.001)

    def evaluate(
        self,
        request: WorkloadRequest,
        snapshot: ResourceSnapshot,
        *,
        now_monotonic: float,
    ) -> AdmissionDecision:
        """Evaluate one optional workload; never sleeps, samples, or starts a process."""
        if not isinstance(request, WorkloadRequest):
            raise TypeError("request must be a WorkloadRequest")
        if not isinstance(snapshot, ResourceSnapshot):
            raise TypeError("snapshot must be a ResourceSnapshot")
        now = _number(now_monotonic, "now_monotonic", minimum=0)

        protected = {
            WorkloadKind.FOREGROUND_INFERENCE,
            WorkloadKind.REALTIME_AUDIO,
            WorkloadKind.TTS_PLAYBACK,
            WorkloadKind.GAME_INPUT,
            WorkloadKind.OBS_CAPTURE,
        }
        if request.kind in protected:
            return AdmissionDecision(AdmissionAction.PROTECTED, "route_to_protected_lane")

        age = now - snapshot.observed_at
        if age < -self.future_clock_skew_seconds:
            return self._defer("snapshot_from_future")
        if age > self.max_snapshot_age_seconds:
            return self._defer("stale_snapshot")
        if snapshot.audio_underruns:
            return self._defer("audio_underrun_observed")

        if snapshot.obs_dropped_frames:
            if snapshot.obs_total_frames < self.min_obs_frames_for_drop_rate:
                return self._defer("obs_window_too_small")
            drop_rate = snapshot.obs_dropped_frames / snapshot.obs_total_frames
            if drop_rate > self.max_obs_drop_rate:
                return self._defer("obs_drop_rate_high")

        if snapshot.game_active:
            if snapshot.game_fps is None:
                return self._defer("game_fps_unavailable")
            if snapshot.game_fps < self.min_game_fps:
                return self._defer("game_fps_below_floor")

        if snapshot.cpu_percent + request.estimated_cpu_percent > self.max_cpu_percent_after_admission:
            return self._defer("cpu_budget_exceeded")
        if snapshot.available_ram_mb - request.estimated_ram_mb < self.min_available_ram_mb:
            return self._defer("ram_reserve_would_be_breached")

        needs_gpu = request.estimated_vram_mb > 0 or request.estimated_gpu_percent > 0
        if needs_gpu:
            if snapshot.available_vram_mb is None or snapshot.gpu_percent is None:
                return self._defer("gpu_telemetry_unavailable")
            if snapshot.available_vram_mb - request.estimated_vram_mb < self.min_available_vram_mb:
                return self._defer("vram_reserve_would_be_breached")
            if snapshot.gpu_percent + request.estimated_gpu_percent > self.max_gpu_percent_after_admission:
                return self._defer("gpu_budget_exceeded")

        return AdmissionDecision(AdmissionAction.ALLOW, "within_budget")

    def _defer(self, reason: str) -> AdmissionDecision:
        return AdmissionDecision(AdmissionAction.DEFER, reason, self.retry_after_seconds)
