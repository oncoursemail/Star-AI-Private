"""Configuration-bound calibration for speculative voice-preparation workers.

A profile is derived from repeated, trusted host measurements of one exact
inference configuration. It stores only the conservative resource envelope,
not raw samples, model paths, transcripts, or machine identifiers.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import re

from ..stream_workload_admission import ResourceVector

_FINGERPRINT = re.compile(r"[0-9a-f]{64}\Z")
_MAX_CLOCK_MS = 10**12
_MAX_SAMPLES = 4096
_MIN_SAMPLES = 8
_MAX_PROFILE_AGE_MS = 7 * 24 * 60 * 60 * 1000


def _validate_clock(value: object) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_CLOCK_MS:
        raise ValueError("calibrated_monotonic_ms/now_ms must be a bounded monotonic integer")
    return value


def _validate_fingerprint(value: object, label: str) -> str:
    if type(value) is not str or _FINGERPRINT.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 hex fingerprint")
    return value


def _with_margin(value: int, margin_percent: int) -> int:
    # Integer ceiling avoids rounding a resource request below the observed peak.
    return (value * (100 + margin_percent) + 99) // 100


@dataclass(frozen=True)
class ThinkResourceProfile:
    """A short-lived, model-configuration-specific resource envelope.

    The envelope is the per-dimension maximum observed across representative
    runs, increased by a fixed safety margin. This is deliberately conservative
    and is not a statistical p99 guarantee.
    """

    configuration_fingerprint: str
    calibrated_monotonic_ms: int
    sample_count: int
    resources: ResourceVector
    safety_margin_percent: int = 25
    max_age_ms: int = 86_400_000

    def __post_init__(self) -> None:
        _validate_fingerprint(self.configuration_fingerprint, "configuration_fingerprint")
        _validate_clock(self.calibrated_monotonic_ms)
        if type(self.sample_count) is not int or not _MIN_SAMPLES <= self.sample_count <= _MAX_SAMPLES:
            raise ValueError("sample_count must be in 8..4096")
        if type(self.resources) is not ResourceVector:
            raise TypeError("resources must be ResourceVector")
        if type(self.safety_margin_percent) is not int or not 0 <= self.safety_margin_percent <= 100:
            raise ValueError("safety_margin_percent must be in 0..100")
        if type(self.max_age_ms) is not int or not 1_000 <= self.max_age_ms <= _MAX_PROFILE_AGE_MS:
            raise ValueError("max_age_ms must be in 1000..604800000")

    @classmethod
    def from_samples(
        cls,
        samples: Sequence[ResourceVector],
        *,
        configuration_fingerprint: str,
        calibrated_monotonic_ms: int,
        trusted_host: bool,
        min_samples: int = _MIN_SAMPLES,
        safety_margin_percent: int = 25,
        max_age_ms: int = 86_400_000,
    ) -> "ThinkResourceProfile":
        """Build a profile from bounded per-worker peak-delta measurements.

        The caller must collect samples from the actual host and exact inference
        configuration. trusted_host is an explicit host assertion, not an
        authentication mechanism or a substitute for process isolation.
        """
        _validate_fingerprint(configuration_fingerprint, "configuration_fingerprint")
        _validate_clock(calibrated_monotonic_ms)
        if trusted_host is not True:
            raise PermissionError("trusted host measurements are required")
        if type(samples) not in (tuple, list):
            raise TypeError("samples must be a bounded tuple or list")
        if type(min_samples) is not int or not _MIN_SAMPLES <= min_samples <= 512:
            raise ValueError("min_samples must be in 8..512")
        if not _MIN_SAMPLES <= len(samples) <= _MAX_SAMPLES:
            raise ValueError("samples must contain 8..4096 measurements")
        if len(samples) < min_samples:
            raise ValueError("insufficient calibration samples")
        if any(type(sample) is not ResourceVector for sample in samples):
            raise TypeError("every calibration sample must be ResourceVector")

        peak = ResourceVector(
            max(sample.cpu_millicores for sample in samples),
            max(sample.ram_mb for sample in samples),
            max(sample.vram_mb for sample in samples),
        )
        try:
            envelope = ResourceVector(
                _with_margin(peak.cpu_millicores, safety_margin_percent),
                _with_margin(peak.ram_mb, safety_margin_percent),
                _with_margin(peak.vram_mb, safety_margin_percent),
            )
        except ValueError as exc:
            raise ValueError("calibrated resource envelope exceeds supported bounds") from exc

        return cls(
            configuration_fingerprint=configuration_fingerprint,
            calibrated_monotonic_ms=calibrated_monotonic_ms,
            sample_count=len(samples),
            resources=envelope,
            safety_margin_percent=safety_margin_percent,
            max_age_ms=max_age_ms,
        )

    def rejection_reason(
        self,
        *,
        now_ms: int,
        expected_configuration_fingerprint: str,
    ) -> str | None:
        """Return a fail-closed reason, or None when this profile is usable."""
        now = _validate_clock(now_ms)
        expected = _validate_fingerprint(
            expected_configuration_fingerprint,
            "expected_configuration_fingerprint",
        )
        if expected != self.configuration_fingerprint:
            return "configuration_mismatch"
        if now < self.calibrated_monotonic_ms:
            return "profile_from_future"
        if now - self.calibrated_monotonic_ms > self.max_age_ms:
            return "profile_stale"
        return None

    def resources_for(
        self,
        *,
        now_ms: int,
        expected_configuration_fingerprint: str,
    ) -> ResourceVector | None:
        """Return the envelope only while its clock and configuration still match."""
        if self.rejection_reason(
            now_ms=now_ms,
            expected_configuration_fingerprint=expected_configuration_fingerprint,
        ) is not None:
            return None
        return self.resources


__all__ = ["ThinkResourceProfile"]
