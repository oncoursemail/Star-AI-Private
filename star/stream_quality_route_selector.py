"""Offline quality-and-latency gate for choosing STAR's deployed inference route.

Use only trusted, independently scored, pre-registered *matched* task suites
collected under the actual gameplay/OBS workload. Never let an LLM, chat or a
model response submit evidence to this object. It neither runs a model nor
changes a deployed route: the host must separately bind the chosen worker
through HostInferenceCatalog and admit it through its realtime QoS gate.

This is a conservative operator *advisory*, not a demonstration of increased
intelligence, game skill, or real-world latency.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import cast

from .stream_host_model_catalog import HostInferenceCatalog

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_WORKLOADS = frozenset({"game_recording", "game_stream", "offline"})
_Z = 1.96


def _num(value: object, label: str, *, lower: float, upper: float) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite number")
    try:
        result = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be finite") from exc
    if not math.isfinite(result) or not lower <= result <= upper:
        raise ValueError(f"{label} must be between {lower} and {upper}")
    return result


def _id(value: object, label: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{label} must be an opaque bounded identifier")
    return value


def _wilson_lower(successes: int, trials: int) -> float:
    """Conservative 95%-Wilson lower confidence limit for a binary task."""
    p = successes / trials
    z2 = _Z * _Z
    return (p + z2 / (2 * trials) - _Z * math.sqrt(
        p * (1 - p) / trials + z2 / (4 * trials * trials)
    )) / (1 + z2 / trials)


@dataclass(frozen=True)
class VerifiedRouteTrialSummary:
    """One trusted host's held-out paired suite aggregate, no prompts or names.

    Every compared worker MUST execute the same exact preregistered task IDs,
    scoring rubric and task order represented by suite_sha256. 'verified' is a
    host-origin claim, not a cryptographic attestation; this class MUST remain
    behind the local trusted evaluator boundary. A SHA alone does not establish
    test independence.
    """
    route_alias: str
    route_profile: str
    task_kind: str
    workload: str
    suite_sha256: str
    trials: int
    verified_successes: int
    p95_end_to_end_ms: float
    total_gpu_peak_mib: float
    measured_unix_s: int
    host_verified: bool

    def __post_init__(self) -> None:
        _id(self.route_alias, "route_alias")
        _id(self.route_profile, "route_profile")
        _id(self.task_kind, "task_kind")
        if self.workload not in _WORKLOADS or type(self.workload) is not str:
            raise ValueError("workload must be a known measured profile")
        if type(self.suite_sha256) is not str or not _SHA.fullmatch(self.suite_sha256):
            raise ValueError("suite_sha256 must be a lowercase SHA256")
        if type(self.trials) is not int or not 1 <= self.trials <= 2000:
            raise ValueError("trials must be a bounded positive count")
        if (type(self.verified_successes) is not int or not
                0 <= self.verified_successes <= self.trials):
            raise ValueError("verified successes must be within the trial count")
        _num(self.p95_end_to_end_ms, "p95_end_to_end_ms",
             lower=0.001, upper=120_000)
        _num(self.total_gpu_peak_mib, "total_gpu_peak_mib",
             lower=0, upper=262_144)
        if type(self.measured_unix_s) is not int or not 1 <= self.measured_unix_s <= 10**11:
            raise ValueError("measured_unix_s must be a bounded Unix timestamp")
        if type(self.host_verified) is not bool:
            raise ValueError("host_verified must be a strict boolean")


@dataclass(frozen=True)
class QualityRouteAdvice:
    """No authority to dispatch, play, broadcast or publish."""
    route_alias: str | None
    reason: str
    baseline_p95_ms: float | None = None
    selected_p95_ms: float | None = None
    selected_quality_lower_95: float | None = None
    authorizes_model_launch: bool = False
    authorizes_game_action: bool = False


class QualityGatedRouteSelector:
    """Opt-in quality-first advisory built from immutable, matched evaluations.

    A faster but weaker or untested route must NOT silently replace the trusted
    baseline. Evidence is scoped to the exact worker profile, task suite,
    workload and time window. The *actual* scheduler still enforces live
    CPU/GPU pressure and worker admission independently.
    """

    def __init__(self, *, catalog: HostInferenceCatalog,
                 summaries: tuple[VerifiedRouteTrialSummary, ...],
                 minimum_trials: int = 30,
                 minimum_quality_lower_95: float = 0.78,
                 minimum_gain_ms: float = 30.0,
                 max_evidence_age_s: int = 7 * 86400) -> None:
        if not isinstance(catalog, HostInferenceCatalog):
            raise TypeError("host-owned catalog required")
        if type(summaries) is not tuple:
            raise ValueError("trusted summaries must be an immutable tuple")
        if type(minimum_trials) is not int or not 20 <= minimum_trials <= 2000:
            raise ValueError("minimum_trials must be 20..2000")
        quality = _num(minimum_quality_lower_95, "minimum_quality_lower_95",
                       lower=0.5, upper=0.99)
        gain = _num(minimum_gain_ms, "minimum_gain_ms", lower=1, upper=5000)
        if type(max_evidence_age_s) is not int or not 60 <= max_evidence_age_s <= 30 * 86400:
            raise ValueError("invalid evidence age limit")
        entries: dict[tuple[str, str, str, str], VerifiedRouteTrialSummary] = {}
        for item in summaries:
            if not isinstance(item, VerifiedRouteTrialSummary):
                raise TypeError("expected a verified trial summary")
            try:
                actual = catalog.profile_for(item.route_alias)
            except KeyError as exc:
                raise ValueError("calibration names a model not in the host catalog") from exc
            if actual != item.route_profile:
                raise ValueError("calibration does not match current model/runtime/voice")
            if catalog.route_for(item.route_alias).kind != item.task_kind:
                raise ValueError("calibration task kind differs from deployed worker kind")
            key = (item.route_alias, item.task_kind, item.workload, item.suite_sha256)
            if key in entries:
                raise ValueError("duplicate calibration cannot be cherry-picked")
            entries[key] = item
        self._catalog = catalog
        self._entries = entries
        self._trials = minimum_trials
        self._quality = quality
        self._gain = gain
        self._max_age = max_evidence_age_s

    @property
    def catalog(self) -> HostInferenceCatalog:
        """Bound immutable deployment registry (not a worker authorization)."""
        return self._catalog

    def advise(self, *, owner_approved: bool = False, baseline_alias: str,
               task_kind: str, workload: str, suite_sha256: str,
               now_unix_s: int, max_p95_ms: float,
               max_total_gpu_mib: float) -> QualityRouteAdvice:
        if type(owner_approved) is not bool:
            raise ValueError("owner_approved must be boolean")
        if not owner_approved:
            return QualityRouteAdvice(None, "owner_opt_in_missing")
        _id(baseline_alias, "baseline_alias")
        _id(task_kind, "task_kind")
        if type(workload) is not str or workload not in _WORKLOADS:
            raise ValueError("unknown workload")
        if type(suite_sha256) is not str or not _SHA.fullmatch(suite_sha256):
            raise ValueError("invalid suite digest")
        if type(now_unix_s) is not int or not 1 <= now_unix_s <= 10**11:
            raise ValueError("trusted current Unix time required")
        max_latency = _num(max_p95_ms, "max_p95_ms", lower=1, upper=120_000)
        max_gpu = _num(max_total_gpu_mib, "max_total_gpu_mib",
                       lower=512, upper=262_144)
        try:
            baseline_profile = self._catalog.profile_for(baseline_alias)
        except KeyError:
            return QualityRouteAdvice(None, "unknown_baseline")
        baseline = self._entries.get((baseline_alias, task_kind, workload, suite_sha256))
        if baseline is None or baseline.route_profile != baseline_profile:
            return QualityRouteAdvice(None, "matching_baseline_evidence_missing")

        def credible(item: VerifiedRouteTrialSummary) -> bool:
            return (item.host_verified
                    and item.trials >= self._trials
                    and 0 <= now_unix_s - item.measured_unix_s <= self._max_age
                    and _wilson_lower(item.verified_successes, item.trials) >= self._quality)

        if not credible(baseline):
            return QualityRouteAdvice(None, "baseline_quality_or_freshness_unverified")
        base_p95 = baseline.p95_end_to_end_ms
        eligible: list[VerifiedRouteTrialSummary] = []
        for item in self._entries.values():
            if (item.task_kind != task_kind or item.workload != workload
                    or item.suite_sha256 != suite_sha256
                    or item.trials != baseline.trials
                    or item.verified_successes < baseline.verified_successes
                    or not credible(item)
                    or item.p95_end_to_end_ms > max_latency
                    or item.total_gpu_peak_mib > max_gpu):
                continue
            # The immutable manifest defines reserved resources and task kind;
            # a fast benchmark cannot override actual worker configuration.
            route = self._catalog.route_for(item.route_alias)
            if route.kind != task_kind or route.vram_mib > max_gpu:
                continue
            if item.route_alias != baseline_alias and (
                base_p95 - item.p95_end_to_end_ms < self._gain
            ):
                continue
            eligible.append(item)
        if not eligible:
            return QualityRouteAdvice(None, "no_quality_and_resource_qualified_route",
                                      baseline_p95_ms=base_p95)
        chosen = min(eligible, key=lambda x: (
            x.p95_end_to_end_ms, x.total_gpu_peak_mib, x.route_alias
        ))
        return QualityRouteAdvice(
            chosen.route_alias,
            "faster_verified_route_for_manual_pilot"
            if chosen.route_alias != baseline_alias else "verified_baseline_only",
            baseline_p95_ms=base_p95,
            selected_p95_ms=chosen.p95_end_to_end_ms,
            selected_quality_lower_95=round(_wilson_lower(
                chosen.verified_successes, chosen.trials
            ), 4),
        )


__all__ = [
    "VerifiedRouteTrialSummary", "QualityRouteAdvice", "QualityGatedRouteSelector"
]
