"""Host-only worker-epoch routing for STAR's real-time game/VTuber QoS.

A verified ON-DISK model catalog is not evidence that a process loaded those
bytes. The authorized launcher must separately pin PID + OS creation time,
check actual running worker identity and report fresh process observations.
This module does not inspect/launch a process or verify in-memory weights.

The purpose is narrower and useful: process restarts must never inherit
previous workers' 'fast model' latency calibration or queued admissions.
A new epoch gets a fresh QoS route profile while retaining host-declared
CPU/VRAM reservations. No permission to game, speak or broadcast is granted.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
import secrets
from threading import RLock
from typing import Mapping

from .stream_host_artifact_preflight import HostArtifactPreflight
from .stream_host_model_catalog import HostModelRoute
from .stream_qos import InferenceJob

_MAX_MS = 1e13
_MAX_UNIX_S = 1e11
_MAX_PID = (1 << 31) - 1
_MAX_STALENESS_MS = 250.0


def _real(value: object, name: str, maximum: float) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a finite host number")
    try:
        converted = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} is not finite") from exc
    if not math.isfinite(converted) or not 0 <= converted <= maximum:
        raise ValueError(f"{name} outside bounded range")
    return converted


@dataclass(frozen=True)
class HostWorkerObservation:
    """Host-attested OS identity, NOT a certificate of loaded model weights.

    process_birth_unix_s is OS process create-time, not the host wall clock.
    observed_monotonic_ms must use the same monotonic clock as QoS.
    A model request, viewer or LLM must never construct these observations.
    """

    pid: int = field(repr=False)
    process_birth_unix_s: float = field(repr=False)
    observed_monotonic_ms: float
    runtime_sha256: str = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.pid) is not int or not 1 <= self.pid <= _MAX_PID:
            raise ValueError("invalid OS process identifier")
        if not 0 < _real(self.process_birth_unix_s, "process birth", _MAX_UNIX_S):
            raise ValueError("invalid OS process creation time")
        _real(self.observed_monotonic_ms, "observation time", _MAX_MS)
        if (type(self.runtime_sha256) is not str
                or len(self.runtime_sha256) != 64
                or any(ch not in "0123456789abcdef" for ch in self.runtime_sha256)):
            raise ValueError("host-observed runtime identity must be lowercase SHA256")


@dataclass(frozen=True)
class HostWorkerEpoch:
    """Non-secret, ephemeral routing handle from a host worker observation."""

    alias: str
    route_profile: str
    generation: int
    # Do not expose these OS identifiers in telemetry, logs, or prompts.
    _pid: int = field(repr=False)
    _born_unix_s: float = field(repr=False)


class HostWorkerEpochRegistry:
    """Bounded lifecycle registry for independently observed model workers.

    The verified catalog is a prerequisite; it does not establish which model
    is in process memory. An authorized launcher/host must (1) verify files
    before launching, (2) observe process identity independently of inference
    requests, (3) call observe before dispatch, and (4) retire on process death.
    HostWorkerEpoch is not an authorization credential and cannot replace those
    checks or the host's own worker-liveness enforcement.
    """

    def __init__(
        self,
        preflight: HostArtifactPreflight,
        routes: tuple[HostModelRoute, ...],
        *,
        max_workers: int = 16,
        max_observation_age_ms: float = _MAX_STALENESS_MS,
    ) -> None:
        if not isinstance(preflight, HostArtifactPreflight):
            raise TypeError("successful host artifact preflight required")
        if (type(routes) is not tuple
                or len(routes) != preflight.catalog.route_count
                or any(not isinstance(r, HostModelRoute) for r in routes)):
            raise ValueError("routes must match the verified artifact catalog")
        known: dict[str, HostModelRoute] = {}
        for route in routes:
            if route.alias in known:
                raise ValueError("duplicate host route")
            if preflight.catalog.profile_for(route.alias) != route.route_profile:
                raise ValueError("routes differ from the preflight catalog")
            known[route.alias] = route
        if type(max_workers) is not int or not 1 <= max_workers <= 64:
            raise ValueError("invalid worker registry capacity")
        freshness = _real(max_observation_age_ms, "max age", 1000)
        if not 50 <= freshness <= 1000:
            raise ValueError("observation age must be 50..1000 ms")
        self._catalog = preflight.catalog
        self._routes: Mapping[str, HostModelRoute] = known
        self._max_workers = max_workers
        self._freshness = freshness
        self._lock = RLock()
        self._epochs: dict[str, HostWorkerEpoch] = {}
        self._last_seen: dict[str, float] = {}
        self._generation = 0
        self._last_now = 0.0

    def _time(self, now_ms: float) -> float:
        now = _real(now_ms, "worker host clock", _MAX_MS)
        if now < self._last_now:
            raise ValueError("host monotonic clock reversed")
        self._last_now = now
        return now

    def observe(
        self, alias: str, witness: HostWorkerObservation, *,
        now_ms: float, owner_approved: bool = False,
    ) -> HostWorkerEpoch:
        """Refresh from a trusted OS process observer, never an inference job."""
        if owner_approved is not True:
            raise PermissionError("host process observation requires owner opt-in")
        if type(alias) is not str or alias not in self._routes:
            raise ValueError("unknown host route")
        if not isinstance(witness, HostWorkerObservation):
            raise TypeError("trusted OS process observation required")
        with self._lock:
            now = self._time(now_ms)
            if (witness.observed_monotonic_ms > now + 20
                    or now - witness.observed_monotonic_ms > self._freshness):
                raise ValueError("stale or future worker observation")
            if witness.runtime_sha256 != self._routes[alias].runtime_sha256:
                raise ValueError("observed runtime digest differs from host manifest")
            # Fence *all* per-alias observations, not only refreshes of the
            # current PID. Otherwise a delayed old-PID sample could resurrect
            # an already replaced or explicitly retired worker.
            last = self._last_seen.get(alias)
            if last is not None and witness.observed_monotonic_ms <= last:
                raise ValueError("replayed or reordered worker observation")
            previous = self._epochs.get(alias)
            if previous is not None and (previous._pid, previous._born_unix_s) == (
                    witness.pid, witness.process_birth_unix_s):
                self._last_seen[alias] = witness.observed_monotonic_ms
                return previous
            if previous is None and len(self._epochs) >= self._max_workers:
                raise ValueError("host worker capacity exhausted")
            self._generation += 1
            # Process restarts, PID reuse and even identical worker builds must
            # receive fresh calibration. An opaque nonce prevents session reuse.
            profile = "epoch-" + secrets.token_hex(16)
            result = HostWorkerEpoch(
                alias, profile, self._generation, witness.pid,
                witness.process_birth_unix_s,
            )
            self._epochs[alias] = result
            self._last_seen[alias] = witness.observed_monotonic_ms
            return result

    def bind(
        self, job: InferenceJob, *, epoch: HostWorkerEpoch, now_ms: float,
    ) -> InferenceJob:
        """Bind owner-selected job only to its fresh and current worker epoch.

        Call the trusted OS observer again independently before each dispatch;
        this function does not itself prove the process is alive.
        """
        if not isinstance(job, InferenceJob) or not isinstance(epoch, HostWorkerEpoch):
            raise TypeError("inference job and current worker epoch required")
        with self._lock:
            now = self._time(now_ms)
            if self._epochs.get(epoch.alias) is not epoch:
                raise ValueError("worker restarted or lease was retired")
            if (now < self._last_seen[epoch.alias]
                    or now - self._last_seen[epoch.alias] > self._freshness):
                raise ValueError("worker observation expired")
            bound = self._catalog.bind(job, route_alias=epoch.alias)
            return replace(bound, route_profile=epoch.route_profile)

    def retire(self, *, epoch: HostWorkerEpoch) -> bool:
        """Revoke one exact epoch, never a replacement sharing the old PID."""
        if not isinstance(epoch, HostWorkerEpoch):
            raise TypeError("current worker epoch required")
        with self._lock:
            if self._epochs.get(epoch.alias) is not epoch:
                return False
            del self._epochs[epoch.alias]
            # Retired routes keep a tiny timestamp watermark (one per catalog
            # alias), so queued pre-retirement process observations cannot be
            # accepted after retirement. Never remove this on worker death.
            return True

    def is_current(self, epoch: HostWorkerEpoch, *, now_ms: float) -> bool:
        """Advisory late-output fence; host must still observe OS liveness.

        Call at the FINAL speech/text/vision output boundary. A valid epoch
        only proves this registry has not seen a newer worker; it is not
        runtime attestation, permission to broadcast, or audio authorization.
        """
        if not isinstance(epoch, HostWorkerEpoch):
            raise TypeError("current worker epoch required")
        with self._lock:
            now = self._time(now_ms)
            if self._epochs.get(epoch.alias) is not epoch:
                return False
            seen = self._last_seen[epoch.alias]
            return seen <= now and now - seen <= self._freshness

    @property
    def active_workers(self) -> int:
        with self._lock:
            return len(self._epochs)


__all__ = ["HostWorkerObservation", "HostWorkerEpoch", "HostWorkerEpochRegistry"]
