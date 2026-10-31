"""Host-only real-time game inference routing advice for STAR.

A slow but correct action is useless after the scene has changed. This small
controller converts *measured*, session-scoped inference times and a trusted
observation age into a conservative decision: try the reactive model, or skip
this stale opportunity. A stronger teacher is eligible only between active
play attempts and only when the host opts into an offline study session.

It is disabled by default, never loads a model, never sends input, never
publishes, and cannot authorize gameplay. Timing samples are not evidence of
model correctness, successful play, or verified learning.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import re
from threading import RLock
from typing import cast

_SCOPE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
_MAX_TIME_MS = 1e7


def _milliseconds(value: object, label: str, *, minimum: float = 0.0) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(number) or not minimum <= number <= _MAX_TIME_MS:
        raise ValueError(f"{label} out of bounds")
    return number


def _p95(samples: list[float]) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    return round(ordered[math.ceil(0.95 * len(ordered)) - 1], 3)


def _clock_ms(value: object, label: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite host monotonic clock")
    try:
        clock = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a finite host monotonic clock") from exc
    if not math.isfinite(clock) or not 0 <= clock <= 1e13:
        raise ValueError(f"{label} out of clock bounds")
    return clock


@dataclass(frozen=True)
class DeadlineAdvice:
    """A hint to the host scheduler, NEVER authority to dispatch input."""

    route: str                     # reactive | teacher_offline | skip
    reason: str
    remaining_ms: float | None = None
    profiled_p95_ms: float | None = None
    authorized_to_play: bool = False
    authorizes_model_launch: bool = False


class GameDeadlineRouter:
    """Session-scoped two-timescale router for real-time game *planning*.

    The host alone must attest completed inference durations, observation ages,
    game/OBS state and worker termination. The fast model must be validated by
    an independent skill gate; this module knows nothing about output quality.
    An expensive teacher is never recommended while active gameplay continues.
    """

    def __init__(self, *, minimum_samples: int = 8,
                 history: int = 64, dispatch_reserve_ms: float = 40.0,
                 reactive_device: str = "cpu",
                 max_latency_sample_age_ms: float = 15_000.0) -> None:
        if type(minimum_samples) is not int or not 5 <= minimum_samples <= 64:
            raise ValueError("minimum_samples must be 5..64")
        if type(history) is not int or not minimum_samples <= history <= 256:
            raise ValueError("history must fit minimum_samples and be <=256")
        reserve = _milliseconds(dispatch_reserve_ms, "dispatch_reserve_ms", minimum=1)
        if reserve > 1000:
            raise ValueError("dispatch reserve must be <=1000ms")
        if reactive_device not in ("cpu", "gpu"):
            raise ValueError("reactive_device must be cpu or gpu")
        sample_age = _milliseconds(max_latency_sample_age_ms,
                                   "max_latency_sample_age_ms", minimum=250)
        if sample_age > 60_000:
            raise ValueError("latency sample age must be <=60 seconds")
        self._max_latency_age = sample_age
        self._minimum = minimum_samples
        self._reserve = reserve
        self._device = reactive_device
        self._lock = RLock()
        self._enabled = False
        self._scope = ""
        self._reactive: deque[tuple[float, float]] = deque(maxlen=history)
        self._last_sample_id = 0
        self._last_sample_ms: float | None = None
        self._last_advice_ms: float | None = None
        self._counts = {"measured": 0, "timeouts": 0, "replays": 0, "reactive": 0,
                        "skipped": 0, "offline_teacher": 0}

    def enable(self, *, owner_approved: bool = False, game_scope: str) -> None:
        if owner_approved is not True:
            raise PermissionError("host approval required")
        if type(game_scope) is not str or _SCOPE.fullmatch(game_scope) is None:
            raise ValueError("game_scope must be a bounded canonical identifier")
        with self._lock:
            if self._enabled:
                raise RuntimeError("disable before changing sessions")
            self._enabled = True
            self._scope = game_scope
            self._reactive.clear()
            self._last_sample_id = 0
            # The next host sample must not race a reset outside this lock.
            self._last_sample_ms = None
            self._last_advice_ms = None

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._scope = ""
            self._reactive.clear()
            self._last_sample_id = 0
            # The next host sample must not race a reset outside this lock.
            self._last_sample_ms = None
            self._last_advice_ms = None

    def record_reactive_latency(
        self, *, game_scope: str, sample_id: int, duration_ms: float,
        sample_host_ms: float,
        host_measured: bool = False, completed: bool = True,
    ) -> bool:
        """Only accept host-measured *completed* quick-path inference latency.

        Sample IDs and local monotonic host-clock stamps are strictly
        increasing in a session. Only recent measurements qualify live routing;
        yesterday's idle-system speed cannot justify decisions under today's
        sustained game/OBS load. Repeated measurements
        cannot make an unmeasured model appear warm. Host-reported timeouts
        enter the sliding latency window at 5000ms rather than disappearing
        and making a failing model appear deceptively fast.
        """
        if type(sample_id) is not int or not 1 <= sample_id < 2**63:
            raise ValueError("invalid timing sample ID")
        duration = _milliseconds(duration_ms, "duration_ms", minimum=0.001)
        at = _clock_ms(sample_host_ms, "sample_host_ms")
        if type(host_measured) is not bool or type(completed) is not bool:
            raise ValueError("host_measured and completed must be booleans")
        with self._lock:
            if not self._enabled or not host_measured or game_scope != self._scope:
                return False
            if (sample_id <= self._last_sample_id or
                    (self._last_sample_ms is not None and at <= self._last_sample_ms)):
                self._counts["replays"] += 1
                return False
            self._last_sample_id = sample_id
            self._last_sample_ms = at
            self._reactive.append((at, duration if completed else 5000.0))
            self._counts["measured"] += 1
            if not completed:
                self._counts["timeouts"] += 1
            return True

    def advise(
        self, *, game_scope: str, game_active: bool,
        observation_age_ms: float | None = None,
        now_host_ms: float | None = None,
        max_observation_age_ms: float = 350.0,
        host_verified: bool = False,
        cpu_pressure: bool = False, gpu_pressure: bool = False,
        offline_teacher_approved: bool = False,
    ) -> DeadlineAdvice:
        """Pre-inference advisory. The host rechecks fresh data at input time.

        For live play, success means the profiled p95 PLUS dispatch reserve is
        strictly within the remaining *scene* lifetime. These are anonymous
        timing statistics, not a guarantee or a game input permit.
        """
        if any(type(flag) is not bool for flag in (
            game_active, host_verified, cpu_pressure, gpu_pressure,
            offline_teacher_approved,
        )):
            raise ValueError("flags must be strict booleans")
        if type(game_scope) is not str or _SCOPE.fullmatch(game_scope) is None:
            raise ValueError("invalid game scope")
        with self._lock:
            def skip(reason: str, *, remaining: float | None = None,
                     profiled: float | None = None) -> DeadlineAdvice:
                self._counts["skipped"] += 1
                return DeadlineAdvice("skip", reason, remaining, profiled)

            if not self._enabled or game_scope != self._scope:
                return skip("disabled_or_wrong_game_session")
            if not host_verified:
                return skip("trusted_host_evidence_missing")
            # A paused game can use a slow teacher only between attempts, and
            # only after *separate* host approval. Never conflate teacher
            # research with permission to update a game agent.
            if not game_active:
                if not offline_teacher_approved:
                    return skip("offline_teacher_not_approved")
                if cpu_pressure or gpu_pressure:
                    return skip("hardware_pressure")
                self._counts["offline_teacher"] += 1
                return DeadlineAdvice("teacher_offline", "offline_study_only")

            if observation_age_ms is None:
                return skip("observation_age_missing")
            age = _milliseconds(observation_age_ms, "observation_age_ms")
            max_age = _milliseconds(max_observation_age_ms,
                                    "max_observation_age_ms", minimum=1)
            if max_age > 5000:
                raise ValueError("observation maximum cannot exceed 5000ms")
            remaining = max(0.0, max_age - age - self._reserve)
            if age > max_age or remaining <= 0:
                return skip("scene_deadline_expired", remaining=remaining)
            if cpu_pressure or (gpu_pressure and self._device == "gpu"):
                return skip("hardware_pressure", remaining=remaining)
            if now_host_ms is None:
                return skip("host_clock_missing", remaining=remaining)
            now = _clock_ms(now_host_ms, "now_host_ms")
            # A host-clock reset must not make a previously expired speed
            # profile eligible again. A new session must be explicitly enabled.
            if self._last_advice_ms is not None and now < self._last_advice_ms:
                return skip("host_clock_reversed", remaining=remaining)
            self._last_advice_ms = now
            if self._last_sample_ms is not None and now < self._last_sample_ms:
                return skip("host_clock_before_samples", remaining=remaining)
            fresh = [duration for at, duration in self._reactive
                     if 0 <= now - at <= self._max_latency_age]
            if len(fresh) < self._minimum:
                return skip("insufficient_recent_latency_samples", remaining=remaining)
            profiled = _p95(fresh)
            if profiled is None or profiled >= remaining:
                return skip("reactive_p95_exceeds_scene_slack",
                            remaining=round(remaining, 3), profiled=profiled)
            self._counts["reactive"] += 1
            return DeadlineAdvice("reactive", "profiled_route_fits_scene_deadline",
                                  round(remaining, 3), profiled)

    def metrics(self) -> dict[str, int | bool | float | None]:
        """No game events, model text, screen data, identities or action IDs."""
        with self._lock:
            return {**self._counts, "enabled": self._enabled,
                    "timing_samples": len(self._reactive),
                    "reactive_p95_ms": _p95([duration for _, duration in self._reactive])}


__all__ = ["DeadlineAdvice", "GameDeadlineRouter"]
