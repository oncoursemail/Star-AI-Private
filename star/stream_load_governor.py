"""Offline, opt-in QoS advice for STAR's realtime voice/game/stream workloads.

A host adapter must independently measure hardware/OBS/voice statistics and
implement scheduling. This module does not sample devices, run jobs, authorize
OS/game/OBS actions, touch data, or prove an actual speedup.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class StreamSample:
    """One atomic telemetry window from a trusted owner-controlled adapter.

    FPS and latencies describe the preceding sampling window, not predictions.
    `streaming` means a real broadcast/recording is active, `gaming` denotes
    an interactive game; neither is inferred from a user prompt.
    """

    seq: int
    captured_ms: int
    streaming: bool
    gaming: bool
    game_fps_p10: float
    voice_p95_ms: float
    obs_dropped_pct: float
    vram_free_mb: int
    audio_underruns: int = 0

    def __post_init__(self) -> None:
        if type(self.seq) is not int or not 1 <= self.seq <= 1_000_000_000:
            raise ValueError("seq must be a positive bounded integer")
        if type(self.captured_ms) is not int or not 0 <= self.captured_ms <= 10**12:
            raise ValueError("captured_ms must be a bounded monotonic timestamp")
        if type(self.streaming) is not bool or type(self.gaming) is not bool:
            raise ValueError("streaming and gaming must be booleans")
        for name, upper in (("game_fps_p10", 500.0), ("voice_p95_ms", 60_000.0),
                            ("obs_dropped_pct", 100.0)):
            value = getattr(self, name)
            if type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= upper:
                raise ValueError(f"{name} must be a finite bounded number")
        for name, maximum in (("vram_free_mb", 1_000_000), ("audio_underruns", 1_000_000)):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError(f"{name} must be a bounded nonnegative integer")


@dataclass(frozen=True)
class GovernorPolicy:
    """Conservative latency-first thresholds; no measured hardware defaults."""

    min_game_fps: float = 45.0
    max_voice_p95_ms: float = 700.0
    max_obs_drop_pct: float = 1.0
    min_free_vram_mb: int = 768
    stale_after_ms: int = 3_000
    recover_windows: int = 3
    vram_reserve_mb: int = 512

    def __post_init__(self) -> None:
        for name, lo, hi in (("min_game_fps", 1.0, 240.0),
                             ("max_voice_p95_ms", 10.0, 10_000.0),
                             ("max_obs_drop_pct", 0.0, 20.0)):
            value = getattr(self, name)
            if type(value) not in (int, float) or not isfinite(value) or not lo <= value <= hi:
                raise ValueError(f"Invalid {name}")
        for name, lo, hi in (("min_free_vram_mb", 0, 100_000),
                             ("stale_after_ms", 100, 60_000),
                             ("recover_windows", 1, 20),
                             ("vram_reserve_mb", 0, 100_000)):
            value = getattr(self, name)
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError(f"Invalid {name}")


@dataclass(frozen=True)
class WorkRequest:
    """Declared resource hint, not an executable task or host permission."""

    kind: str
    requested_vram_mb: int = 0

    def __post_init__(self) -> None:
        if self.kind not in ("voice", "game_control", "game_vision", "chat",
                             "research", "night_school", "asset_render"):
            raise ValueError("Unrecognized workload; default-deny")
        if type(self.requested_vram_mb) is not int or not 0 <= self.requested_vram_mb <= 65_536:
            raise ValueError("requested_vram_mb must be a bounded integer")


@dataclass(frozen=True)
class Admission:
    allowed: bool
    reason: str
    tier: str
    vision_stride: int
    chat_token_ceiling: int


class StreamLoadGovernor:
    """Telemetry-driven *advice* with immediate degradation and hysteresis.

    Active game/stream tasks outrank background training and asset work.
    Repeated healthy observations are required to recover from pressure,
    avoiding a 1-frame oscillation between expensive and lightweight plans.
    """

    def __init__(self, policy: GovernorPolicy | None = None) -> None:
        self.policy = policy if policy is not None else GovernorPolicy()
        if type(self.policy) is not GovernorPolicy:
            raise TypeError("Expected GovernorPolicy")
        self._sample: StreamSample | None = None
        self._pressure = True  # cold starts fail closed
        self._healthy_run = 0
        self._clock = -1
        self._rejected = 0
        self._admitted = 0

    def _check_clock(self, now_ms: int) -> None:
        if type(now_ms) is not int or not 0 <= now_ms <= 10**12:
            raise ValueError("Expected bounded monotonic milliseconds")
        if now_ms < self._clock:
            raise ValueError("Clock regression")
        self._clock = now_ms

    def observe(self, sample: StreamSample, *, trusted_host: bool = False) -> str:
        """Observe an ordered, host-supplied window; never call host APIs."""
        if trusted_host is not True:
            raise PermissionError("Authoritative host telemetry required")
        if type(sample) is not StreamSample:
            raise TypeError("Expected StreamSample")
        if self._sample is not None and sample.seq <= self._sample.seq:
            raise ValueError("Replay or out-of-order telemetry")
        if self._sample is not None and sample.captured_ms <= self._sample.captured_ms:
            raise ValueError("Non-increasing sample timestamp")
        self._check_clock(sample.captured_ms)
        self._sample = sample
        p = self.policy
        pressure = (sample.vram_free_mb < p.min_free_vram_mb
                    or (sample.gaming and sample.game_fps_p10 < p.min_game_fps)
                    or (sample.streaming and (sample.voice_p95_ms > p.max_voice_p95_ms
                                             or sample.obs_dropped_pct > p.max_obs_drop_pct
                                             or sample.audio_underruns > 0)))
        if pressure:
            self._pressure = True
            self._healthy_run = 0
        else:
            self._healthy_run += 1
            if self._healthy_run >= p.recover_windows:
                self._pressure = False
        return "pressure" if self._pressure else "normal"

    def admit(self, request: WorkRequest, *, now_ms: int,
              owner_approved: bool = False) -> Admission:
        """Return a bounded routing hint. Caller must also enforce permissions.

        This method has *no* side effects beyond counters; allowed never means
        approved to access files, games, cameras, remote PCs or the internet.
        """
        if type(request) is not WorkRequest:
            raise TypeError("Expected WorkRequest")
        self._check_clock(now_ms)
        s = self._sample
        stale = s is None or now_ms - s.captured_ms > self.policy.stale_after_ms
        tier = "unknown" if stale else "pressure" if self._pressure else "normal"
        foreground = request.kind in ("voice", "game_control", "game_vision", "chat")
        vision_stride = 4 if tier != "normal" else 1
        chat_cap = 64 if tier != "normal" else 256
        if owner_approved is not True:
            allowed, reason = False, "owner_approval_required"
        elif s is None or stale:
            # Even emergency voice/control need live admission by the actual host;
            # a stale heartbeat never authorizes independent execution.
            allowed, reason = False, "telemetry_unavailable"
        elif request.requested_vram_mb + self.policy.vram_reserve_mb > s.vram_free_mb:
            allowed, reason = False, "insufficient_vram_headroom"
        elif (s.streaming or s.gaming) and not foreground:
            allowed, reason = False, "interactive_workload_priority"
        elif self._pressure and not foreground:
            allowed, reason = False, "resource_pressure"
        else:
            allowed, reason = True, "foreground_advisory" if foreground else "idle_advisory"
        if allowed:
            self._admitted += 1
        else:
            self._rejected += 1
        return Admission(allowed, reason, tier, vision_stride, chat_cap)

    def summary(self) -> dict[str, int | str]:
        """Counters only; no chat, gameplay frames, or private process data."""
        return {"sample_seq": 0 if self._sample is None else self._sample.seq,
                "tier": "unknown" if self._sample is None else
                        "pressure" if self._pressure else "normal",
                "healthy_windows": self._healthy_run,
                "admitted_requests": self._admitted,
                "rejected_requests": self._rejected}
