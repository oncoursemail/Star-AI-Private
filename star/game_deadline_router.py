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

from .stream_load_governor import StreamLoadGovernor

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
                 max_latency_sample_age_ms: float = 15_000.0,
                 strict_workload_profile: bool = False,
                 strict_input_ack_profile: bool = False) -> None:
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
        if type(strict_workload_profile) is not bool:
            raise ValueError("strict_workload_profile must be boolean")
        if type(strict_input_ack_profile) is not bool:
            raise ValueError("strict_input_ack_profile must be boolean")
        self._strict_input_ack_profile = strict_input_ack_profile
        self._strict_workload_profile = strict_workload_profile
        self._max_latency_age = sample_age
        self._minimum = minimum_samples
        self._reserve = reserve
        self._device = reactive_device
        self._lock = RLock()
        self._enabled = False
        self._scope = ""
        # Tag measured completion speed with the independently attested OBS
        # state. In strict mode, idle timings never qualify live decisions.
        self._reactive: deque[tuple[float, float, bool]] = deque(maxlen=history)
        # Actual OS input acknowledgement latency is a separate bottleneck
        # from model decoding. Trusted same-clock host measurements only.
        self._input_ack: deque[tuple[float, float, bool]] = deque(maxlen=history)
        self._last_input_ack_id = 0
        self._last_input_ack_ms: float | None = None
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
            self._input_ack.clear()
            self._last_input_ack_id = 0
            self._last_input_ack_ms = None
            self._last_sample_id = 0
            # The next host sample must not race a reset outside this lock.
            self._last_sample_ms = None
            self._last_advice_ms = None

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._scope = ""
            self._reactive.clear()
            self._input_ack.clear()
            self._last_input_ack_id = 0
            self._last_input_ack_ms = None
            self._last_sample_id = 0
            # The next host sample must not race a reset outside this lock.
            self._last_sample_ms = None
            self._last_advice_ms = None

    def record_reactive_latency(
        self, *, game_scope: str, sample_id: int, duration_ms: float,
        sample_host_ms: float,
        host_measured: bool = False, completed: bool = True,
        stream_live: bool = False,
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
        if any(type(flag) is not bool for flag in (
            host_measured, completed, stream_live,
        )):
            raise ValueError("timing attestation flags must be booleans")
        with self._lock:
            if not self._enabled or not host_measured or game_scope != self._scope:
                return False
            if (sample_id <= self._last_sample_id or
                    (self._last_sample_ms is not None and at <= self._last_sample_ms)):
                self._counts["replays"] += 1
                return False
            self._last_sample_id = sample_id
            self._last_sample_ms = at
            self._reactive.append((at, duration if completed else 5000.0, stream_live))
            self._counts["measured"] += 1
            if not completed:
                self._counts["timeouts"] += 1
            return True

    def record_input_ack_latency(
        self, *, game_scope: str, sample_id: int, duration_ms: float,
        sample_host_ms: float, host_measured: bool = False,
        completed: bool = True, stream_live: bool = False,
    ) -> bool:
        """Record actual host-observed input acknowledgement, never a model estimate.

        Completion should be measured at the OS-input acknowledgement edge,
        not at model output or a request to press a key. A missing OS ack is
        recorded as a 5s timeout rather than silently omitted. Neither this
        timing nor its host attestation proves that the game accepted input.
        """
        if type(sample_id) is not int or not 1 <= sample_id < 2**63:
            raise ValueError("invalid input ack timing sample ID")
        duration = _milliseconds(duration_ms, "duration_ms", minimum=0.001)
        at = _clock_ms(sample_host_ms, "sample_host_ms")
        if any(type(flag) is not bool for flag in (
            host_measured, completed, stream_live,
        )):
            raise ValueError("input ack attestation flags must be booleans")
        with self._lock:
            if not self._enabled or not host_measured or game_scope != self._scope:
                return False
            if (sample_id <= self._last_input_ack_id
                    or (self._last_input_ack_ms is not None
                        and at <= self._last_input_ack_ms)):
                self._counts["replays"] += 1
                return False
            self._last_input_ack_id = sample_id
            self._last_input_ack_ms = at
            self._input_ack.append((at, duration if completed else 5000.0, stream_live))
            return True

    def advise(
        self, *, game_scope: str, game_active: bool,
        observation_age_ms: float | None = None,
        now_host_ms: float | None = None,
        max_observation_age_ms: float = 350.0,
        host_verified: bool = False,
        cpu_pressure: bool = False, gpu_pressure: bool = False,
        offline_teacher_approved: bool = False,
        stream_live: bool = False,
        stream_governor: StreamLoadGovernor | None = None,
        completed_inference: bool = False,
    ) -> DeadlineAdvice:
        """Admission or completed-inference advisory, not game permission.

        For live play, success means the profiled p95 PLUS dispatch reserve is
        strictly within the remaining *scene* lifetime. These are anonymous
        timing statistics, not a guarantee or a game input permit.

        stream_live is an independently attested OBS broadcast state. A
        provided governor must use the SAME host monotonic clock epoch as
        now_host_ms (seconds versus milliseconds); its recommendation is
        recomputed at decision time, never reused from an old snapshot.
        Offline teacher study is not eligible during a live broadcast, even
        when game_active is False. The live GPU fast path requires fresh,
        normal stream telemetry; CPU fast play can continue through missing
        stream telemetry unless independent CPU pressure forbids it.

        Only a trusted caller holding the original, previously admitted and
        now host-verified *completed* inference lease may request the
        completed_inference postflight route. It repeats the scope, deadline,
        host-clock, OBS and hardware checks without charging an already-finished
        inference its estimated p95 latency a second time. This advisory
        NEVER authorizes a model launch or game action by itself.
        """
        if any(type(flag) is not bool for flag in (
            game_active, host_verified, cpu_pressure, gpu_pressure,
            offline_teacher_approved, stream_live, completed_inference,
        )):
            raise ValueError("flags must be strict booleans")
        if stream_governor is not None and not isinstance(stream_governor, StreamLoadGovernor):
            raise TypeError("stream_governor must be a StreamLoadGovernor")
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
            # A host-clock rollback must not revive teacher work *or*
            # previously fast reactive timings after a newer decision.
            # Treat both kinds of work as part of the same monotonic session.
            now: float | None = None
            if now_host_ms is not None:
                now = _clock_ms(now_host_ms, "now_host_ms")
                if self._last_advice_ms is not None and now < self._last_advice_ms:
                    return skip("host_clock_reversed")
                self._last_advice_ms = now

            # Paused gameplay is not the same as an idle streaming computer.
            # The stream governor's pause_background_workers bit is binding
            # *for advice*, even if its overall pressure profile is "normal".
            # Normal OBS performance is not permission to start a teacher job.
            if not game_active:
                if stream_live:
                    return skip("live_stream_precludes_offline_teacher")
                if not offline_teacher_approved:
                    return skip("offline_teacher_not_approved")
                if cpu_pressure or gpu_pressure:
                    return skip("hardware_pressure")
                if stream_governor is not None:
                    if now is None:
                        return skip("host_clock_missing")
                    try:
                        load = stream_governor.recommend(now_s=now / 1000.0)
                    except ValueError:
                        return skip("stream_clock_mismatch")
                    if load.profile != "normal":
                        return skip("stream_headroom_unverified_for_offline_study")
                    if load.pause_background_workers:
                        return skip("stream_governor_precludes_offline_teacher")
                self._counts["offline_teacher"] += 1
                return DeadlineAdvice("teacher_offline", "offline_study_only")

            # Record the monotonic host clock even when pressure or stale
            # observations make this particular routing opportunity a skip.
            # Otherwise a later backward clock could revive old fast samples.
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
            if now is None:
                return skip("host_clock_missing", remaining=remaining)
            if self._last_sample_ms is not None and now < self._last_sample_ms:
                return skip("host_clock_before_samples", remaining=remaining)
            if stream_live:
                if stream_governor is None:
                    if self._device == "gpu":
                        return skip("stream_telemetry_missing", remaining=remaining)
                else:
                    # Query fresh pressure using the host's shared monotonic
                    # clock. Cached "normal" status may outlive OBS stability.
                    # A mismatch fails closed for GPU inference rather than
                    # crashing the game or falsely treating telemetry as fresh.
                    try:
                        stream_advice = stream_governor.recommend(now_s=now / 1000.0)
                    except ValueError:
                        return skip("stream_clock_mismatch", remaining=remaining)
                    if stream_advice.profile == "critical":
                        return skip("stream_critical_pressure", remaining=remaining)
                    if self._device == "gpu" and stream_advice.profile != "normal":
                        return skip("stream_gpu_headroom_unverified", remaining=remaining)
            # Strict mode budgets verified OS acknowledgement latency too.
            # Idle measurements cannot qualify live input timing, even when
            # model decoding itself has a fresh non-strict profile.
            if self._strict_input_ack_profile:
                matching_ack = [
                    duration for at, duration, observed_live in self._input_ack
                    if 0 <= now - at <= self._max_latency_age
                    and observed_live == stream_live
                ]
                if len(matching_ack) < self._minimum:
                    return skip("insufficient_recent_input_ack_latency_samples",
                                remaining=remaining)
                ack_p95 = _p95(matching_ack)
                if ack_p95 is None:
                    return skip("input_ack_profile_missing", remaining=remaining)
                # The original reserve still provides a minimum guard.
                required_reserve = max(self._reserve, ack_p95)
                remaining = max(0.0, max_age - age - required_reserve)
                if remaining <= 0:
                    return skip("input_ack_p95_exceeds_scene_slack",
                                remaining=remaining, profiled=ack_p95)
            # At admission, budget a complete p95 inference. At completion,
            # that work has *already happened*. Charging p95 again can reject
            # a genuinely timely model response despite the host-verified
            # game scene and action gate still having enough time to act.
            # The completed route is advisory only; RealtimeGameLoop.finish
            # holds the original object-identity-bound lease before using it.
            if completed_inference:
                return DeadlineAdvice(
                    "completed", "verified_completion_fits_scene_deadline",
                    round(remaining, 3),
                )
            fresh = [duration for at, duration, observed_stream_live in self._reactive
                     if 0 <= now - at <= self._max_latency_age
                     and (not self._strict_workload_profile
                          or observed_stream_live == stream_live)]
            if len(fresh) < self._minimum:
                reason = ("insufficient_matching_workload_latency_samples"
                          if self._strict_workload_profile else
                          "insufficient_recent_latency_samples")
                return skip(reason, remaining=remaining)
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
                    "input_ack_samples": len(self._input_ack),
                    "input_ack_p95_ms": _p95([duration for _, duration, _ in self._input_ack]),
                    "strict_input_ack_profile": self._strict_input_ack_profile,
                    "reactive_p95_ms": _p95([duration for _, duration, _ in self._reactive])}


__all__ = ["DeadlineAdvice", "GameDeadlineRouter"]
