"""Passive, host-owned bridge from real game trials and OBS windows to load drift.

Captures *measurement provenance boundaries*, not game actions. A real Windows
host must supply independently observed game frames, timestamps, current OBS
counter deltas, and GPU headroom. This module has no OS input, network, OBS
control, inference, voice, or broadcast side effects.

Accepted flags are host assertions, not authentication. In particular, an
OS input acknowledgment does NOT prove the game executed the requested action.
The result cannot approve gameplay, learned skills, or live streaming.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import islice
import math
from typing import Iterable, cast

from .game_capture_to_action_benchmark import CaptureToActionTrial
from .game_load_shift_guard import (
    GameLoadDriftReport,
    GameLoadSample,
    assess_game_load_shift,
)
from .obs_stats_window import ObsLagWindow

_MAX_SAMPLES = 200


def _finite_number(value: object, name: str, maximum: float) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name}: host numeric evidence required")
    try:
        result = float(cast(int | float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name}: invalid numeric evidence") from exc
    if not math.isfinite(result) or not 0 <= result <= maximum:
        raise ValueError(f"{name}: out of bounds")
    return result


@dataclass(frozen=True)
class GameHostLoadTick:
    """One actual host-measured game action covered by one OBS stats interval.

    OBS windows must come from two consecutive GetStats counter readings via
    ObsStatsWindow. No OBS scene titles, raw frames, game chat, account IDs,
    microphone audio, keys, credentials, or viewers may enter this schema.

    host_verified and obs_continuity_verified are claims made by the host
    adapter. A signed host recorder with distinct, trusted inputs is needed
    before this becomes high-assurance evidence. No runtime is trusted merely
    because it instantiated this dataclass.
    """

    trial: CaptureToActionTrial
    obs: ObsLagWindow
    host_session_id: str
    profile: str
    gpu_free_mib: int
    host_verified: bool
    obs_continuity_verified: bool

    def to_sample(self) -> GameLoadSample:
        if type(self.trial) is not CaptureToActionTrial:
            raise ValueError("actual capture-to-action trial required")
        if type(self.obs) is not ObsLagWindow:
            raise ValueError("OBS interval derived from GetStats required")
        if (self.host_verified is not True or
                self.obs_continuity_verified is not True or
                self.trial.independently_measured is not True):
            raise ValueError("host, OBS continuity and game evidence required")
        if type(self.gpu_free_mib) is not int:
            raise ValueError("GPU memory must be a measured integer MiB")

        end = self.trial.input_ack_ms
        if end is None:
            end = self.trial.inference_end_ms
        elif not self.trial.world_kept_running:
            raise ValueError("game world did not demonstrably keep running")

        observed = _finite_number(self.obs.observed_ms, "OBS time", 1e13)
        span = _finite_number(self.obs.window_ms, "OBS interval", 30000)
        if span < 100:
            raise ValueError("OBS interval too short")
        render = _finite_number(self.obs.render_lag_pct, "OBS render lag", 100)
        output = _finite_number(self.obs.output_lag_pct, "OBS output lag", 100)
        if not (observed - span <= self.trial.capture_start_ms <= end <= observed):
            raise ValueError("game trial is not enclosed by measured OBS interval")

        return GameLoadSample(
            episode_id=self.trial.episode_id,
            host_session_id=self.host_session_id,
            # Include game version; new deployments cannot inherit old baselines.
            game_scope=f"{self.trial.game_id}:{self.trial.game_version}",
            profile=self.profile,
            observed_at_ms=observed,
            capture_to_ack_ms=(
                self.trial.input_ack_ms - self.trial.capture_start_ms
                if self.trial.input_ack_ms is not None else None
            ),
            inference_ms=(
                self.trial.inference_end_ms - self.trial.preprocess_end_ms
            ),
            dispatch_ms=(
                self.trial.input_ack_ms - self.trial.inference_end_ms
                if self.trial.input_ack_ms is not None else None
            ),
            game_p99_frame_ms=self.trial.game_p99_frame_ms,
            # Protect rendering AND encoding; use worst interval.
            obs_skipped_pct=max(render, output),
            gpu_free_mib=self.gpu_free_mib,
            independently_measured=True,
        )


def assess_host_game_load(
    baseline: Iterable[GameHostLoadTick],
    current: Iterable[GameHostLoadTick], *,
    now_ms: float,
    minimum_per_window: int = 20,
) -> GameLoadDriftReport:
    """Translate two successive real-host windows and run the passive drift audit.

    Unlike paired A/B benchmarking, this comparison requires *one unchanged*
    baseline/candidate variant, engine/version, host and workload profile.
    Each OBS counter interval may cover just one game trial. Reusing one
    counter interval for dozens of trials falsely inflates sample count and
    is rejected even when episode IDs are unique.
    """
    before = tuple(islice(baseline, _MAX_SAMPLES + 1))
    after = tuple(islice(current, _MAX_SAMPLES + 1))
    if len(before) > _MAX_SAMPLES or len(after) > _MAX_SAMPLES:
        raise ValueError("too many host observations")
    ticks = before + after
    variants = set()
    previous_obs_end = -1.0
    previous_game_start = -1.0
    for tick in ticks:
        if type(tick) is not GameHostLoadTick:
            raise TypeError("only typed host observations are allowed")
        # Convert before touching the order fields: this checks finiteness.
        tick.to_sample()
        variants.add(tick.trial.variant)
        obs_start = tick.obs.observed_ms - tick.obs.window_ms
        if obs_start < previous_obs_end:
            raise ValueError("reused or overlapping OBS measurement interval")
        if tick.trial.capture_start_ms <= previous_game_start:
            raise ValueError("game capture order reversed or replayed")
        previous_obs_end = tick.obs.observed_ms
        previous_game_start = tick.trial.capture_start_ms
    if len(variants) > 1:
        raise ValueError("cannot compare distinct model variants as load drift")
    return assess_game_load_shift(
        (tick.to_sample() for tick in before),
        (tick.to_sample() for tick in after),
        now_ms=now_ms, minimum_per_window=minimum_per_window,
    )


__all__ = ["GameHostLoadTick", "assess_host_game_load"]
