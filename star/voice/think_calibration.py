"""Paired, epoch-bound calibration sessions for speculative voice preparation.

The host supplies normalized ResourceVector observations captured immediately
before and during a thinker run. This module computes incremental deltas and
prevents samples from different configurations, clock epochs, or overlapping
measurement windows from being combined into one profile.

It performs no OS probes, process inspection, inference, scheduling, or writes.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from ..stream_workload_admission import ResourceVector
from .think_resource_profile import ThinkResourceProfile

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_CLOCK_MS = 10**12
_MAX_SAMPLES = 4096
_MIN_SAMPLES = 8
_DEFAULT_MIN_SAMPLES = 30
_MAX_SESSION_MS = 6 * 60 * 60 * 1000
_MAX_PAIR_WINDOW_MS = 5 * 60 * 1000
_DEFAULT_OBSERVATION_AGE_MS = 30_000


def _clock(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_CLOCK_MS:
        raise ValueError(f"{label} must be a bounded monotonic millisecond value")
    return value


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{label} must be a bounded opaque identifier")
    return value


def _fingerprint(value: object, label: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 fingerprint")
    return value


@dataclass(frozen=True)
class ThinkCalibrationPair:
    """One baseline/active measurement pair from the same host clock epoch.

    Both vectors must already be normalized into the scheduler's abstract
    allocation units. They are not raw OS counters. The host should keep stream,
    game, OBS, and other background load as constant as possible between the
    baseline and active observations.
    """

    sample_id: str
    sequence: int
    clock_epoch: str
    configuration_fingerprint: str
    baseline_monotonic_ms: int
    active_monotonic_ms: int
    baseline: ResourceVector
    active: ResourceVector

    def __post_init__(self) -> None:
        _identifier(self.sample_id, "sample_id")
        if type(self.sequence) is not int or not 1 <= self.sequence <= 1_000_000:
            raise ValueError("sequence must be a positive bounded integer")
        _identifier(self.clock_epoch, "clock_epoch")
        _fingerprint(self.configuration_fingerprint, "configuration_fingerprint")
        baseline_at = _clock(self.baseline_monotonic_ms, "baseline_monotonic_ms")
        active_at = _clock(self.active_monotonic_ms, "active_monotonic_ms")
        if active_at <= baseline_at:
            raise ValueError("active measurement must follow its baseline")
        if active_at - baseline_at > _MAX_PAIR_WINDOW_MS:
            raise ValueError("baseline/active measurement window exceeds five minutes")
        if type(self.baseline) is not ResourceVector or type(self.active) is not ResourceVector:
            raise TypeError("baseline and active must be ResourceVector values")
        if not any((self.cpu_delta, self.ram_delta, self.vram_delta)):
            raise ValueError("paired sample must show positive incremental resource use")

    @property
    def cpu_delta(self) -> int:
        return max(0, self.active.cpu_millicores - self.baseline.cpu_millicores)

    @property
    def ram_delta(self) -> int:
        return max(0, self.active.ram_mb - self.baseline.ram_mb)

    @property
    def vram_delta(self) -> int:
        return max(0, self.active.vram_mb - self.baseline.vram_mb)

    @property
    def incremental_resources(self) -> ResourceVector:
        """Return nonnegative per-dimension deltas; never subtract across epochs."""
        return ResourceVector(self.cpu_delta, self.ram_delta, self.vram_delta)


class ThinkCalibrationSession:
    """Bounded one-shot collection of paired thinker resource measurements.

    The default target is 30 non-overlapping pairs. Eight is the hard minimum
    for compatibility with ThinkResourceProfile, but callers should prefer
    30–50 independent repetitions spanning warm-up and steady-state behavior.
    A session is scoped to one inference fingerprint and one host clock epoch.
    """

    def __init__(
        self,
        *,
        session_id: str,
        configuration_fingerprint: str,
        clock_epoch: str,
        started_monotonic_ms: int,
        min_samples: int = _DEFAULT_MIN_SAMPLES,
        max_samples: int = 256,
        max_duration_ms: int = 60 * 60 * 1000,
        max_pair_window_ms: int = _MAX_PAIR_WINDOW_MS,
        max_observation_age_ms: int = _DEFAULT_OBSERVATION_AGE_MS,
    ) -> None:
        self._session_id = _identifier(session_id, "session_id")
        self._configuration_fingerprint = _fingerprint(
            configuration_fingerprint, "configuration_fingerprint"
        )
        self._clock_epoch = _identifier(clock_epoch, "clock_epoch")
        self._started_ms = _clock(started_monotonic_ms, "started_monotonic_ms")
        if type(min_samples) is not int or not _MIN_SAMPLES <= min_samples <= 512:
            raise ValueError("min_samples must be in 8..512")
        if type(max_samples) is not int or not min_samples <= max_samples <= _MAX_SAMPLES:
            raise ValueError("max_samples must be in min_samples..4096")
        if type(max_duration_ms) is not int or not 1_000 <= max_duration_ms <= _MAX_SESSION_MS:
            raise ValueError("max_duration_ms must be in 1000..21600000")
        if type(max_pair_window_ms) is not int or not 100 <= max_pair_window_ms <= _MAX_PAIR_WINDOW_MS:
            raise ValueError("max_pair_window_ms must be in 100..300000")
        if (type(max_observation_age_ms) is not int
                or not 100 <= max_observation_age_ms <= 300_000):
            raise ValueError("max_observation_age_ms must be in 100..300000")
        self._min_samples = min_samples
        self._max_samples = max_samples
        self._max_duration_ms = max_duration_ms
        self._max_pair_window_ms = max_pair_window_ms
        self._max_observation_age_ms = max_observation_age_ms
        self._deltas: list[ResourceVector] = []
        self._sample_ids: set[str] = set()
        self._last_sequence = 0
        self._last_active_ms: int | None = None
        self._closed = False

    def _check_live(self, now_ms: int) -> int:
        now = _clock(now_ms, "now_ms")
        if now < self._started_ms:
            raise ValueError("calibration clock moved before session start")
        if now - self._started_ms > self._max_duration_ms:
            raise TimeoutError("calibration session exceeded its maximum duration")
        return now

    def add(
        self,
        pair: ThinkCalibrationPair,
        *,
        now_ms: int,
        trusted_host: bool = False,
    ) -> None:
        """Accept one paired sample from the authorized host collector."""
        if self._closed:
            raise RuntimeError("calibration session is already closed")
        now = self._check_live(now_ms)
        if trusted_host is not True:
            raise PermissionError("trusted host measurements are required")
        if type(pair) is not ThinkCalibrationPair:
            raise TypeError("pair must be ThinkCalibrationPair")
        if pair.clock_epoch != self._clock_epoch:
            raise ValueError("sample belongs to another host clock epoch")
        if pair.configuration_fingerprint != self._configuration_fingerprint:
            raise ValueError("sample belongs to another inference configuration")
        if pair.sequence <= self._last_sequence:
            raise ValueError("sample sequence must increase strictly")
        if pair.sample_id in self._sample_ids:
            raise ValueError("duplicate calibration sample_id")
        if pair.baseline_monotonic_ms < self._started_ms:
            raise ValueError("baseline predates calibration session")
        if pair.active_monotonic_ms > now:
            raise ValueError("active measurement is future-dated")
        if now - pair.active_monotonic_ms > self._max_observation_age_ms:
            raise ValueError("active measurement is stale")
        if pair.active_monotonic_ms - pair.baseline_monotonic_ms > self._max_pair_window_ms:
            raise ValueError("measurement pair exceeds this session's window")
        if self._last_active_ms is not None and pair.baseline_monotonic_ms <= self._last_active_ms:
            raise ValueError("measurement windows must not overlap")
        if len(self._deltas) >= self._max_samples:
            raise OverflowError("calibration sample capacity reached")
        self._deltas.append(pair.incremental_resources)
        self._sample_ids.add(pair.sample_id)
        self._last_sequence = pair.sequence
        self._last_active_ms = pair.active_monotonic_ms

    def finalize(
        self,
        *,
        now_ms: int,
        safety_margin_percent: int = 25,
        max_age_ms: int = 86_400_000,
    ) -> ThinkResourceProfile:
        """Create one immutable profile after enough fresh paired samples."""
        if self._closed:
            raise RuntimeError("calibration session is already closed")
        now = self._check_live(now_ms)
        if len(self._deltas) < self._min_samples:
            raise ValueError("insufficient paired calibration samples")
        if self._last_active_ms is None or now - self._last_active_ms > self._max_observation_age_ms:
            raise ValueError("latest calibration sample is stale")
        profile = ThinkResourceProfile.from_samples(
            tuple(self._deltas),
            configuration_fingerprint=self._configuration_fingerprint,
            calibrated_monotonic_ms=self._last_active_ms,
            trusted_host=True,
            min_samples=self._min_samples,
            safety_margin_percent=safety_margin_percent,
            max_age_ms=max_age_ms,
            clock_epoch=self._clock_epoch,
        )
        self._closed = True
        return profile

    def abort(self) -> bool:
        """Discard unfinalized measurements and close the session."""
        if self._closed:
            return False
        self._deltas.clear()
        self._sample_ids.clear()
        self._closed = True
        return True

    def summary(self, *, now_ms: int) -> dict[str, int | bool]:
        """Return content-free aggregate calibration progress."""
        now = self._check_live(now_ms)
        return {
            "samples": len(self._deltas),
            "minimum_samples": self._min_samples,
            "capacity": self._max_samples,
            "ready": len(self._deltas) >= self._min_samples,
            "closed": self._closed,
            "elapsed_ms": now - self._started_ms,
        }


__all__ = ["ThinkCalibrationPair", "ThinkCalibrationSession"]
