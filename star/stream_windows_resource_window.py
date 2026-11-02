"""Bounded, read-only Windows GPU/process stability check for a NONBROADCAST VTuber lab.

A single low-utilization GPU query or briefly free VRAM is not evidence of
headroom during gaming. This module gathers a small time-window of independent
OS observations. It never plays a game, starts OBS, opens sockets, stores
process identities, or grants stream/game permissions.

All source readers must be supplied by a trusted local host. Merely passing
plausible Python objects is not cryptographic attestation.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import islice
import math
import platform
import time
from typing import Callable, Iterable, Sequence

from star.stream_windows_rehearsal_preflight import (
    GpuHeadroom,
    ProcessWitness,
    _INFRA_ROLE_BY_BASENAME,
    _game_identity,
    _validated_gpu_uuid,
    enumerate_windows_processes,
    evaluate_preflight,
    query_nvidia_gpu,
)


@dataclass(frozen=True)
class _WindowSample:
    """Ephemeral process identities: do not serialize, log or persist."""
    at_monotonic_s: float
    processes: tuple[ProcessWitness, ...]
    gpu: GpuHeadroom | None


@dataclass(frozen=True)
class ResourceWindowReport:
    """Privacy-minimal advisory. Candidate is NOT permission to play or stream."""
    status: str  # candidate | deferred | unavailable
    reasons: tuple[str, ...]
    sample_count: int
    observed_span_ms: int | None
    gpu_total_mib: int | None
    gpu_min_free_mib: int | None
    gpu_max_utilization_pct: int | None
    host_processes_stable: bool
    authorized_to_play: bool = False
    authorized_to_broadcast: bool = False

    @property
    def candidate_for_nonbroadcast_rehearsal(self) -> bool:
        return self.status == "candidate"


def _unavailable(reason: str) -> ResourceWindowReport:
    return ResourceWindowReport(
        "unavailable", (reason,), 0, None, None, None, None, False,
    )


def _process_fingerprint(
    processes: tuple[ProcessWitness, ...],
    pinned_game_identity: tuple[int, float] | None,
) -> tuple[tuple[str, int, float], ...]:
    """Local-only app PID + creation-time check, to detect restarts between samples."""
    identities = []
    for p in processes:
        role = _INFRA_ROLE_BY_BASENAME.get(p.name.casefold())
        if role is not None:
            identities.append((role, p.pid, p.created_unix_s))
        if pinned_game_identity is not None and p.pid == pinned_game_identity[0]:
            identities.append(("pinned_game", p.pid, p.created_unix_s))
    return tuple(sorted(identities))


def evaluate_resource_window(
    samples: Sequence[_WindowSample],
    *,
    pinned_game_identity: tuple[int, float] | None,
    expected_gpu_uuid: str | None = None,
    gpu_reserve_mib: int = 1536,
    max_gpu_utilization_pct: int = 90,
) -> ResourceWindowReport:
    """Pure fail-closed evaluation: require sustained, not instantaneous, headroom."""
    game = _game_identity(pinned_game_identity)
    expected_uuid = (
        _validated_gpu_uuid(expected_gpu_uuid) if expected_gpu_uuid is not None else None
    )
    if not 3 <= len(samples) <= 9:
        raise ValueError("expected 3..9 bounded host samples")

    reasons: list[str] = []
    total_mib: int | None = None
    first_gpu_uuid: str | None = None
    free_values: list[int] = []
    utilization_values: list[int] = []
    previous_at: float | None = None
    first_at: float | None = None
    fingerprints: list[tuple[tuple[str, int, float], ...]] = []
    all_gpus_present = True

    for sample in samples:
        if not isinstance(sample, _WindowSample):
            raise ValueError("invalid host sample type")
        at = sample.at_monotonic_s
        if type(at) not in (int, float) or not math.isfinite(at) or not 0 <= at <= 10**12:
            raise ValueError("invalid monotonic host timestamp")
        if first_at is None:
            first_at = at
        if previous_at is not None and not 0.2 <= at - previous_at <= 4.0:
            reasons.append("irregular_sample_cadence")
        previous_at = at

        # Reuse the same strictly validated process/GPU checks as the one-shot
        # Windows preflight. A failed intermediate sample cannot be averaged away.
        result = evaluate_preflight(
            sample.processes, sample.gpu,
            pinned_game_identity=game,
            gpu_reserve_mib=gpu_reserve_mib,
            max_gpu_utilization_pct=max_gpu_utilization_pct,
        )
        reasons.extend(result.reasons)
        fingerprints.append(_process_fingerprint(sample.processes, game))
        if sample.gpu is None:
            all_gpus_present = False
            continue
        total_mib = total_mib if total_mib is not None else sample.gpu.total_mib
        if sample.gpu.total_mib != total_mib:
            reasons.append("gpu_total_changed_during_window")
        # Identical VRAM/utilization readings can belong to different GPUs.
        # Index-only selection cannot prove the sampled device was stable.
        if sample.gpu.device_uuid is None:
            reasons.append("gpu_device_identity_missing")
        else:
            uuid = _validated_gpu_uuid(sample.gpu.device_uuid)
            if first_gpu_uuid is None:
                first_gpu_uuid = uuid
            elif uuid != first_gpu_uuid:
                reasons.append("gpu_device_identity_changed_during_window")
            if expected_uuid is not None and uuid != expected_uuid:
                reasons.append("gpu_device_identity_mismatch")
        free_values.append(sample.gpu.free_mib)
        utilization_values.append(sample.gpu.utilization_pct)

    assert first_at is not None and previous_at is not None
    span = previous_at - first_at
    if span < 1.5:
        reasons.append("sampling_window_too_short")
    if span > 30.0:
        reasons.append("sampling_window_too_long")

    consistent_fingerprints = all(f == fingerprints[0] for f in fingerprints[1:])
    expected_roles = {"obs", "avatar", "model", "pinned_game"}
    roles = [role for role, _, _ in fingerprints[0]]
    # Four role labels are not four distinct processes. A mistakenly pinned
    # OBS/avatar/model worker must not count as an actual game process.
    distinct_pids = {pid for _, pid, _ in fingerprints[0]}
    processes_stable = (consistent_fingerprints
                        and len(roles) == 4 and set(roles) == expected_roles
                        and len(distinct_pids) == 4)
    if not consistent_fingerprints:
        reasons.append("process_identity_changed_during_window")
    return ResourceWindowReport(
        "deferred" if reasons else "candidate",
        tuple(dict.fromkeys(reasons)),
        len(samples),
        round(span * 1000),
        total_mib if all_gpus_present else None,
        min(free_values) if all_gpus_present else None,
        max(utilization_values) if all_gpus_present else None,
        processes_stable,
    )


def probe_windows_resource_window(
    *,
    owner_approved: bool = False,
    pinned_game_identity: tuple[int, float] | None,
    expected_gpu_uuid: str | None = None,
    gpu_index: int = 0,
    sample_count: int = 5,
    sample_spacing_s: float = 0.5,
    process_reader: Callable[[], Iterable[ProcessWitness]] = enumerate_windows_processes,
    gpu_reader: Callable[[int], GpuHeadroom] = query_nvidia_gpu,
    system_name: Callable[[], str] = platform.system,
    monotonic_clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> ResourceWindowReport:
    """Opt-in passive 2-second Windows stability check, without service changes.

    Never calls OBS, VTube Studio, game input, network endpoints or microphone.
    Calls nvidia-smi via the already bounded read-only GPU reader. A candidate
    only means resource/proc evidence looked stable in this short sample window.
    """
    if owner_approved is not True:
        raise PermissionError("host opt-in required for read-only resource observations")
    _game_identity(pinned_game_identity)
    if expected_gpu_uuid is not None:
        _validated_gpu_uuid(expected_gpu_uuid)
    if type(gpu_index) is not int or not 0 <= gpu_index <= 7:
        raise ValueError("GPU index must be 0..7")
    if type(sample_count) is not int or not 3 <= sample_count <= 9:
        raise ValueError("sample count must be 3..9")
    if (type(sample_spacing_s) not in (int, float)
            or not math.isfinite(sample_spacing_s)
            or not 0.25 <= sample_spacing_s <= 2.0):
        raise ValueError("sample spacing must be 0.25..2 seconds")
    if not all(callable(f) for f in (
        process_reader, gpu_reader, system_name, monotonic_clock, sleeper,
    )):
        raise TypeError("trusted local host readers and clock must be callable")
    if system_name() != "Windows":
        return _unavailable("windows_host_required")

    samples: list[_WindowSample] = []
    for i in range(sample_count):
        try:
            if i:
                sleeper(float(sample_spacing_s))
            # Bound generator materialization even if a faulty host reader
            # produces unbounded entries. The validator rejects 32,769 rows.
            processes = tuple(islice(process_reader(), 32769))
        except Exception:
            return _unavailable("local_process_snapshot_unavailable")
        try:
            gpu: GpuHeadroom | None = gpu_reader(gpu_index)
        except Exception:
            gpu = None
        try:
            at = monotonic_clock()
        except Exception:
            return _unavailable("local_monotonic_clock_unavailable")
        samples.append(_WindowSample(at, processes, gpu))
    try:
        return evaluate_resource_window(
            samples, pinned_game_identity=pinned_game_identity,
            expected_gpu_uuid=expected_gpu_uuid,
        )
    except (TypeError, ValueError):
        return _unavailable("resource_window_evidence_invalid")


__all__ = ["ResourceWindowReport", "evaluate_resource_window", "probe_windows_resource_window"]
