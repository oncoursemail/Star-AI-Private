"""Opt-in, host-attested, hysteretic admission *advice* for STAR's VTuber PC.

A live game, voice and OBS render path should not compete with unattended
research/training. This module extends the stateless stream budget policy with
OBS render/encode pressure, stale-sample rejection and recovery hysteresis.

It does NOT collect OBS metrics, launch jobs, kill processes, control GPU clocks,
press keys, speak, or grant permissions. The trusted Windows host must measure
and attest telemetry, enforce this advice, and keep independent stop controls.
No raw audio, frames, chat, player identities or system paths are stored.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from threading import RLock
from typing import cast

from .stream_budget import StreamTelemetry, advise_workload

_WORKLOADS = frozenset({"speech", "gameplay", "vision", "research", "training", "render"})
_CRITICAL = frozenset({"speech", "gameplay"})
_MAX_CLOCK_MS = 1e13


def _number(value: object, label: str, limit: float) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite nonnegative number")
    try:
        num = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a finite nonnegative number") from exc
    if not math.isfinite(num) or not 0 <= num <= limit:
        raise ValueError(f"{label} must be within 0..{limit}")
    return num


@dataclass(frozen=True)
class StreamHealthSample:
    """An anonymous sample, all fields reported by one trusted local host."""

    observed_ms: float
    telemetry: StreamTelemetry
    obs_render_lag_pct: float
    obs_encode_lag_pct: float
    host_verified: bool = False

    def __post_init__(self) -> None:
        _number(self.observed_ms, "observed_ms", _MAX_CLOCK_MS)
        if not isinstance(self.telemetry, StreamTelemetry):
            raise TypeError("telemetry must be StreamTelemetry")
        _number(self.obs_render_lag_pct, "obs_render_lag_pct", 100)
        _number(self.obs_encode_lag_pct, "obs_encode_lag_pct", 100)
        if type(self.host_verified) is not bool:
            raise ValueError("host_verified must be an explicit boolean")


@dataclass(frozen=True)
class AdmissionAdvice:
    """Not authorization to run a model, use a GPU or interact with a game."""

    allowed: bool
    profile: str
    sample_fps: float
    reason: str
    authorizes_execution: bool = False


class StreamAdmissionGate:
    """Protect high-priority work from asynchronous background jobs.

    A single bad OBS/resource sample trips overload immediately. Recovery
    needs several spaced, *verified* healthy samples. Read-only advice is
    evaluated against its host-clock age; a stale sample never clears the
    overload latch. Distinct live sessions must call disable() and enable().
    """

    def __init__(self, *, max_sample_age_ms: int = 1500,
                 recovery_samples: int = 3, recovery_ms: int = 1500,
                 min_sample_gap_ms: int = 250) -> None:
        for name, value, low, high in (
            ("max_sample_age_ms", max_sample_age_ms, 250, 5000),
            ("recovery_samples", recovery_samples, 2, 10),
            ("recovery_ms", recovery_ms, 500, 10000),
            ("min_sample_gap_ms", min_sample_gap_ms, 100, 2000),
        ):
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name} must be an integer in {low}..{high}")
        if min_sample_gap_ms >= max_sample_age_ms:
            raise ValueError("sample gap must be shorter than sample max age")
        self._max_sample_age_ms = max_sample_age_ms
        self._recovery_samples = recovery_samples
        self._recovery_ms = recovery_ms
        self._min_gap_ms = min_sample_gap_ms
        self._lock = RLock()
        self._enabled = False
        self._last: StreamHealthSample | None = None
        self._last_query_ms: float | None = None
        self._overloaded = False
        self._healthy_count = 0
        self._healthy_since_ms: float | None = None
        self._last_counted_healthy_ms: float | None = None
        self._counts = {"accepted": 0, "rejected": 0, "overload_trips": 0,
                        "recoveries": 0, "deferred": 0}

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("stream admission needs authorized host approval")
        with self._lock:
            if self._enabled:
                raise RuntimeError("disable before starting a new admission session")
            self._reset()
            self._enabled = True

    def _reset(self) -> None:
        self._last = None
        self._last_query_ms = None
        self._overloaded = False
        self._healthy_count = 0
        self._healthy_since_ms = None
        self._last_counted_healthy_ms = None

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._reset()

    @staticmethod
    def _bad(sample: StreamHealthSample) -> bool:
        t = sample.telemetry
        return (
            t.free_vram_mib < 1536
            or (t.game_active and t.game_fps < 45)
            or t.speech_backlog_ms > 350
            or (t.live and (sample.obs_render_lag_pct > 1.0
                            or sample.obs_encode_lag_pct > 1.0))
        )

    def observe(self, sample: StreamHealthSample) -> bool:
        """Accept ordered, attested local metrics; never trust a model's claim."""
        if not isinstance(sample, StreamHealthSample):
            raise TypeError("expected StreamHealthSample")
        with self._lock:
            if not self._enabled:
                return False
            last = self._last
            # Metric collectors may publish with modest delay relative to
            # advise() calls. Reject ordering relative to the prior *sample*,
            # not relative to the last query; age is checked at advise().
            if (not sample.host_verified or
                    (last is not None and sample.observed_ms <= last.observed_ms)):
                self._counts["rejected"] += 1
                return False
            self._last = sample
            self._counts["accepted"] += 1
            if self._bad(sample):
                if not self._overloaded:
                    self._counts["overload_trips"] += 1
                self._overloaded = True
                self._healthy_count = 0
                self._healthy_since_ms = None
                self._last_counted_healthy_ms = None
            elif self._overloaded:
                # Avoid fake recovery from many observations at one instant.
                if (self._last_counted_healthy_ms is None or
                        sample.observed_ms - self._last_counted_healthy_ms >= self._min_gap_ms):
                    if self._healthy_since_ms is None:
                        self._healthy_since_ms = sample.observed_ms
                    self._last_counted_healthy_ms = sample.observed_ms
                    self._healthy_count += 1
                if (self._healthy_count >= self._recovery_samples and
                        self._healthy_since_ms is not None and
                        sample.observed_ms - self._healthy_since_ms >= self._recovery_ms):
                    self._overloaded = False
                    self._counts["recoveries"] += 1
                    self._healthy_count = 0
                    self._healthy_since_ms = None
                    self._last_counted_healthy_ms = None
            return True

    def advise(self, kind: str, *, now_ms: float) -> AdmissionAdvice:
        """Return a host-owned scheduling hint, never a task execution grant."""
        if type(kind) is not str or kind not in _WORKLOADS:
            raise ValueError("unsupported workload")
        now = _number(now_ms, "now_ms", _MAX_CLOCK_MS)
        with self._lock:
            if not self._enabled:
                return AdmissionAdvice(False, "deferred", 0, "owner_opt_in_missing")
            if self._last_query_ms is not None and now < self._last_query_ms:
                if kind not in _CRITICAL:
                    self._counts["deferred"] += 1
                return AdmissionAdvice(False, "deferred", 0, "host_clock_reversed")
            self._last_query_ms = now
            sample = self._last
            if kind in _CRITICAL:
                # Critical work remains *priority advice*, even if the host has
                # lost telemetry. The host still owns all permissions/capacity.
                return AdmissionAdvice(True, "latency", 0,
                                       "prioritize_realtime_host_policy_required")
            if (sample is None or sample.observed_ms > now or
                    now - sample.observed_ms > self._max_sample_age_ms):
                self._counts["deferred"] += 1
                return AdmissionAdvice(False, "deferred", 0, "telemetry_missing_or_stale")
            if self._overloaded or self._bad(sample):
                self._counts["deferred"] += 1
                return AdmissionAdvice(False, "deferred", 0, "resource_or_obs_pressure")
            basic = advise_workload(kind, sample.telemetry)
            if not basic.allowed:
                self._counts["deferred"] += 1
            return AdmissionAdvice(basic.allowed, basic.profile,
                                   basic.sample_fps, basic.reason)

    def metrics(self) -> dict[str, int | bool]:
        """Only bounded anonymous counters, never screenshots/identities."""
        with self._lock:
            return {**self._counts, "enabled": self._enabled,
                    "overloaded": self._overloaded}


__all__ = ["StreamHealthSample", "AdmissionAdvice", "StreamAdmissionGate"]
