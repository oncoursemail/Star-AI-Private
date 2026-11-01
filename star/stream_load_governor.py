"""Opt-in, observation-only resource governor for Star's gaming VTuber host.

A game, OBS, TTS and local AI compete for limited frame time and VRAM. The
trusted host supplies fresh *interval* rates from OBS, not lifetime averages.
The governor emits conservative resource advice; it neither reads OBS nor
starts/stops processes, changes GPU settings, sends chat or controls games.

The host must authenticate the telemetry producer and apply recommendations
only through separately authorized executors. No personal data is retained.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import math
import re
from threading import RLock
from typing import cast

_SAMPLE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_MAX_SECONDS = 1e10
_REPLAY_LIMIT = 1024
_RANK = {"normal": 0, "constrained": 1, "critical": 2}


def _number(value: object, label: str, *, minimum: float = 0.0,
            maximum: float = 1e10) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite number")
    number = float(cast(int | float, value))
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{label} is outside its permitted range")
    return number


@dataclass(frozen=True)
class StreamLoadSample:
    """Host-attested snapshot; percentages are recent *interval* percentages.

    OBS renderer, encoder and network losses are distinct signals, each
    calculated from monotonic counter DELTAS from one uninterrupted OBS session.
    A host must reset its baseline after an OBS reconnect or counter reset.
    """
    sample_id: str
    measured_at_s: float  # Host monotonic clock, not wall/UTC time.
    game_p95_frame_ms: float
    game_target_fps: float
    obs_render_missed_pct: float
    obs_encode_skipped_pct: float
    obs_network_dropped_pct: float
    gpu_vram_used_mb: float
    gpu_vram_total_mb: float
    tts_first_audio_p95_ms: float
    obs_connected: bool = True

    def __post_init__(self) -> None:
        if type(self.sample_id) is not str or _SAMPLE_ID.fullmatch(self.sample_id) is None:
            raise ValueError("sample_id must be a bounded stable identifier")
        _number(self.measured_at_s, "measured_at_s", maximum=_MAX_SECONDS)
        _number(self.game_p95_frame_ms, "game_p95_frame_ms", minimum=0.001, maximum=10000)
        _number(self.game_target_fps, "game_target_fps", minimum=1, maximum=500)
        for field in ("obs_render_missed_pct", "obs_encode_skipped_pct",
                      "obs_network_dropped_pct"):
            _number(getattr(self, field), field, maximum=100)
        total = _number(self.gpu_vram_total_mb, "gpu_vram_total_mb",
                        minimum=1, maximum=1_000_000)
        _number(self.gpu_vram_used_mb, "gpu_vram_used_mb", maximum=total)
        _number(self.tts_first_audio_p95_ms, "tts_first_audio_p95_ms", maximum=60000)
        if type(self.obs_connected) is not bool:
            raise ValueError("obs_connected must be a bool")


@dataclass(frozen=True)
class StreamLoadAdvice:
    """Non-binding profile. Host must separately approve any concrete action."""
    profile: str
    reason: str
    pause_background_workers: bool
    allow_optional_commentary: bool
    allow_extra_gpu_inference: bool
    max_extra_gpu_vram_mb: int
    prefer_cpu_voice_experiment: bool


class StreamLoadGovernor:
    """Fail-quiet during telemetry loss; recover gradually after clean samples.

    Escalation is immediate. A return from critical -> constrained -> normal
    requires three consecutive lower-pressure samples per step, avoiding
    oscillation around one noisy threshold. Disabled until owner-approved.
    """

    def __init__(self, *, max_sample_age_s: float = 3.0,
                 recovery_samples: int = 3) -> None:
        self.max_sample_age_s = _number(
            max_sample_age_s, "max_sample_age_s", minimum=0.1, maximum=30
        )
        if type(recovery_samples) is not int or not 2 <= recovery_samples <= 20:
            raise ValueError("recovery_samples must be 2..20")
        self.recovery_samples = recovery_samples
        self._lock = RLock()
        self._enabled = False
        self._profile = "warming"
        self._reason = "waiting_for_fresh_telemetry"
        self._last_now: float | None = None
        self._last_sample: StreamLoadSample | None = None
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._recovery_streak = 0
        self._counts = {"accepted": 0, "rejected": 0, "transitions": 0}

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner must approve stream telemetry monitoring")
        with self._lock:
            if self._enabled:
                return
            self._enabled = True
            self._reset()

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._reset()

    def _reset(self) -> None:
        self._profile = "warming"
        self._reason = "waiting_for_fresh_telemetry"
        self._last_now = None
        self._last_sample = None
        self._seen.clear()
        self._recovery_streak = 0

    def _clock(self, now_s: float, *, commit: bool = True) -> float:
        now = _number(now_s, "now_s", maximum=_MAX_SECONDS)
        if self._last_now is not None and now < self._last_now:
            raise ValueError("host monotonic clock moved backwards; reset session")
        # Rejected but host-verified telemetry (e.g. replayed counter samples)
        # must not advance the clock and lock out a subsequent valid sample.
        if commit:
            self._last_now = now
        return now

    @staticmethod
    def _classify(sample: StreamLoadSample) -> tuple[str, str]:
        budget_ms = 1000.0 / sample.game_target_fps
        vram_fraction = sample.gpu_vram_used_mb / sample.gpu_vram_total_mb
        if not sample.obs_connected:
            return "critical", "obs_disconnected"
        if sample.obs_render_missed_pct >= 3.0:
            return "critical", "obs_render_lag"
        if sample.obs_encode_skipped_pct >= 2.0:
            return "critical", "obs_encoder_lag"
        if sample.obs_network_dropped_pct >= 4.0:
            return "critical", "network_loss"
        if sample.game_p95_frame_ms >= 1.8 * budget_ms:
            return "critical", "game_frame_deadline"
        if vram_fraction >= 0.96:
            return "critical", "vram_near_capacity"
        if sample.obs_render_missed_pct >= 0.5:
            return "constrained", "obs_render_lag"
        if sample.obs_encode_skipped_pct >= 0.5:
            return "constrained", "obs_encoder_lag"
        if sample.obs_network_dropped_pct >= 1.0:
            return "constrained", "network_loss"
        if sample.game_p95_frame_ms >= 1.25 * budget_ms:
            return "constrained", "game_frame_pressure"
        if vram_fraction >= 0.86:
            return "constrained", "vram_pressure"
        if sample.tts_first_audio_p95_ms >= 900.0:
            return "constrained", "speech_latency"
        return "normal", "headroom_observed"

    def ingest(self, sample: StreamLoadSample, *, now_s: float,
               host_verified: bool = False) -> bool:
        """Store one independently verified, fresh, ordered measurement.

        False means rejected; an invalid sample never creates a healthy profile.
        Source authentication and OBS counter-delta calculations belong to host.
        """
        with self._lock:
            # Reject unauthenticated/malformed submissions BEFORE touching the
            # host-clock watermark. Otherwise a bogus future timestamp on a
            # rejected packet can lock out every subsequent valid measurement
            # until the session is restarted (clock-poisoning denial of service).
            if (not self._enabled or host_verified is not True
                    or not isinstance(sample, StreamLoadSample)):
                self._counts["rejected"] += 1
                return False
            now = self._clock(now_s, commit=False)
            if (sample.sample_id in self._seen
                    or sample.measured_at_s > now
                    or now - sample.measured_at_s > self.max_sample_age_s
                    or (self._last_sample is not None
                        and sample.measured_at_s <= self._last_sample.measured_at_s)):
                self._counts["rejected"] += 1
                return False
            # Trust and freshness gates passed: only now commit the host-clock
            # watermark. A rejected delivery cannot poison future observations.
            self._last_now = now
            # A long gap must not preserve a previously healthy profile.
            # Demand fresh consecutive evidence before optional work resumes.
            if (self._last_sample is not None and
                    sample.measured_at_s - self._last_sample.measured_at_s
                    > self.max_sample_age_s):
                self._profile = "warming"
                self._reason = "telemetry_gap_rewarming"
                self._recovery_streak = 0
            self._seen[sample.sample_id] = None
            if len(self._seen) > _REPLAY_LIMIT:
                self._seen.popitem(last=False)
            self._last_sample = sample
            new_profile, reason = self._classify(sample)
            if self._profile == "warming":
                if new_profile != "normal":
                    self._recovery_streak = 0
                    self._profile = new_profile
                    self._reason = reason
                    self._counts["transitions"] += 1
                else:
                    self._recovery_streak += 1
                    if self._recovery_streak >= self.recovery_samples:
                        self._profile = "normal"
                        self._reason = reason
                        self._counts["transitions"] += 1
            elif _RANK[new_profile] > _RANK[self._profile]:
                self._profile = new_profile
                self._reason = reason
                self._recovery_streak = 0
                self._counts["transitions"] += 1
            elif _RANK[new_profile] < _RANK[self._profile]:
                self._recovery_streak += 1
                self._reason = "waiting_for_stable_recovery"
                if self._recovery_streak >= self.recovery_samples:
                    level = _RANK[self._profile] - 1
                    self._profile = ("normal", "constrained", "critical")[level]
                    self._reason = reason
                    self._recovery_streak = 0
                    self._counts["transitions"] += 1
            else:
                self._recovery_streak = 0
                self._reason = reason
            self._counts["accepted"] += 1
            return True

    def recommend(self, *, now_s: float) -> StreamLoadAdvice:
        """Read-only snapshot of recommendations, never a new clock attestation.

        The last trusted clock watermark advances only upon accepted host
        telemetry. A wrong-epoch or future *read* must not lock out the next
        valid OBS/game sample from recovering the streamer.
        """
        with self._lock:
            now = self._clock(now_s, commit=False)
            if not self._enabled:
                return StreamLoadAdvice("disabled", "owner_opt_in_required",
                                        False, False, False, 0, False)
            sample = self._last_sample
            if sample is None or now - sample.measured_at_s > self.max_sample_age_s:
                return StreamLoadAdvice("telemetry_stale", "fresh_observation_required",
                                        True, False, False, 0, False)
            if self._profile == "warming":
                return StreamLoadAdvice("warming", self._reason,
                                        True, False, False, 0, False)
            if self._profile != "normal":
                # A CPU TTS experiment may be considered for memory pressure,
                # but the host must also benchmark CPU load before switching.
                cpu_voice = (self._profile == "constrained"
                             and sample.gpu_vram_used_mb / sample.gpu_vram_total_mb >= 0.86)
                return StreamLoadAdvice(self._profile, self._reason,
                                        True, False, False, 0, cpu_voice)
            # Advisory upper bound, NOT guaranteed allocatable VRAM. Keep at
            # least 20% (or 768 MB) in reserve for the game and OBS.
            spare = sample.gpu_vram_total_mb - sample.gpu_vram_used_mb
            reserve = max(768.0, 0.20 * sample.gpu_vram_total_mb)
            budget = max(0, int(spare - reserve))
            return StreamLoadAdvice("normal", self._reason, True, True,
                                    budget >= 1024, budget, False)

    def metrics(self) -> dict[str, int]:
        """Only anonymous counters; no prompts, device IDs or viewer data."""
        with self._lock:
            return {**self._counts, "recent_ids": len(self._seen)}


__all__ = ["StreamLoadSample", "StreamLoadAdvice", "StreamLoadGovernor"]
