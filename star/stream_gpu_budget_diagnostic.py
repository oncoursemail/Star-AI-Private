"""Passive Windows GPU-budget diagnostic for STAR's gaming/VTuber host.

This is a READ-ONLY, owner-opted *hardware preflight*, not a GPU allocator.
A fast LLM in isolation may monopolize VRAM needed for game frames, OBS
rendering/encoding, avatar animation and TTS. Three to nine samples on the
same NVIDIA GPU establish a conservative minimum headroom, not future FPS.

This module never starts/stops programs, loads models, contacts OBS, collects
chat/video/audio/window titles or configures broadcasts. NVIDIA/WDDM telemetry
can be stale or imperfect; the output is *not* permission to play or stream.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from itertools import islice
import json
import math
import platform
import time
from typing import Callable, Iterable, cast

from .stream_windows_rehearsal_preflight import (
    GpuHeadroom,
    query_nvidia_gpu,
    _validated_gpu_uuid,
)

_MAX_CLOCK = 1e12


def _real(value: object, label: str, limit: float) -> float:
    if type(value) not in (float, int):
        raise ValueError(f"{label}: finite host reading required")
    try:
        number = float(cast(int | float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{label}: invalid host reading") from exc
    if not math.isfinite(number) or not 0 <= number <= limit:
        raise ValueError(f"{label}: out of range")
    return number


@dataclass(frozen=True)
class GpuBudgetTick:
    """Ephemeral GPU UUID lives only in GpuHeadroom and is never exported."""
    monotonic_s: float
    gpu: GpuHeadroom

    def __post_init__(self) -> None:
        _real(self.monotonic_s, "monotonic_s", _MAX_CLOCK)
        if type(self.gpu) is not GpuHeadroom:
            raise ValueError("typed NVIDIA sample required")


@dataclass(frozen=True)
class GpuBudgetReport:
    """Privacy-limited preflight; not execution or broadcasting authority."""
    status: str  # unavailable | saturated | constrained | preflight_only
    reasons: tuple[str, ...]
    samples: int
    observed_span_ms: int | None
    gpu_total_mib: int | None
    minimum_free_mib: int | None
    peak_utilization_pct: int | None
    unreserved_mib: int | None
    proposed_placement: str
    may_launch_new_gpu_workers: bool = False
    authorizes_gameplay: bool = False
    authorizes_broadcast: bool = False
    verified_game_fps: bool = False

    def to_json(self) -> str:
        """Never export UUIDs, device IDs, process identifiers or raw samples."""
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)


def _unavailable(reason: str) -> GpuBudgetReport:
    return GpuBudgetReport(
        "unavailable", (reason,), 0, None, None, None, None, None,
        "do_not_start_new_gpu_work",
    )


def assess_gpu_budget(
    ticks: Iterable[GpuBudgetTick], *, reserve_mib: int = 1536,
    optional_voice_mib: int = 512, max_util_pct: int = 90,
) -> GpuBudgetReport:
    """Minimum across one valid, consecutive GPU sampling window.

    A high GPU-utilization sample can indicate compute saturation even with
    free VRAM. Headroom is merely an *advisory* for a prospective private
    rehearsal: real game/OBS/voice headroom must be measured again under load.
    """
    if type(reserve_mib) is not int or not 512 <= reserve_mib <= 16384:
        raise ValueError("invalid minimum graphics/OBS reserve")
    if type(optional_voice_mib) is not int or not 0 <= optional_voice_mib <= 8192:
        raise ValueError("invalid optional GPU voice estimate")
    if type(max_util_pct) is not int or not 50 <= max_util_pct <= 100:
        raise ValueError("invalid GPU utilization caution threshold")
    items = tuple(islice(ticks, 10))
    if not 3 <= len(items) <= 9:
        raise ValueError("expect exactly 3..9 ordered GPU samples")
    first = items[0]
    if any(type(tick) is not GpuBudgetTick for tick in items):
        raise ValueError("typed GPU sample required")
    assert type(first) is GpuBudgetTick
    reference = first.gpu
    if reference.device_uuid is None:
        return _unavailable("gpu_uuid_unavailable")
    uuid = _validated_gpu_uuid(reference.device_uuid)
    last: float | None = None
    mins: list[int] = []
    utilization: list[int] = []
    for tick in items:
        if tick.gpu.device_uuid is None:
            return _unavailable("gpu_uuid_unavailable")
        if (_validated_gpu_uuid(tick.gpu.device_uuid) != uuid
                or tick.gpu.total_mib != reference.total_mib):
            return _unavailable("gpu_identity_or_capacity_changed")
        current = _real(tick.monotonic_s, "sample clock", _MAX_CLOCK)
        if last is not None and not 0.2 <= current - last <= 4.0:
            return _unavailable("sampling_cadence_unreliable")
        last = current
        mins.append(tick.gpu.free_mib)
        utilization.append(tick.gpu.utilization_pct)
    assert last is not None
    span = last - items[0].monotonic_s
    if not 0.7 <= span <= 30:
        return _unavailable("sampling_window_unreliable")
    free = min(mins)
    peak_util = max(utilization)
    usable = max(0, free - reserve_mib)
    if free < reserve_mib:
        status = "saturated"
        reasons = ("graphics_obs_vram_reserve_not_available",)
        placement = "do_not_start_new_gpu_work"
    elif (free < reserve_mib + optional_voice_mib
          or peak_util >= max_util_pct):
        status = "constrained"
        reasons = ("voice_gpu_budget_or_compute_pressure",)
        placement = "prefer_cpu_voice_after_quality_benchmark"
    else:
        status = "preflight_only"
        reasons = ("idle_headroom_requires_loaded_game_obs_voice_recheck",)
        placement = "benchmark_one_optional_worker_only"
    return GpuBudgetReport(
        status, reasons, len(items), round(span * 1000),
        reference.total_mib, free, peak_util, usable, placement,
    )


def probe_windows_gpu_budget(
    *, owner_approved: bool = False, index: int = 0, sample_count: int = 5,
    spacing_s: float = 0.5, reserve_mib: int = 1536,
    optional_voice_mib: int = 512,
    gpu_reader: Callable[[int], GpuHeadroom] = query_nvidia_gpu,
    system_name: Callable[[], str] = platform.system,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> GpuBudgetReport:
    """Read-only repeated nvidia-smi survey from a Windows background worker.

    Fail on ANY missed sample; do not let a last good snapshot masquerade as
    verified sustained headroom. Errors are sanitized (no OS paths/secrets).
    """
    if owner_approved is not True:
        raise PermissionError("explicit local read-only probe opt-in required")
    if type(index) is not int or not 0 <= index <= 7:
        raise ValueError("GPU index must be 0..7")
    if type(sample_count) is not int or not 3 <= sample_count <= 9:
        raise ValueError("sample count must be 3..9")
    interval = _real(spacing_s, "spacing_s", 4)
    if not 0.25 <= interval <= 2:
        raise ValueError("spacing_s must be 0.25..2")
    # Fail early, before hardware I/O, on untrusted configuration.
    if type(reserve_mib) is not int or not 512 <= reserve_mib <= 16384:
        raise ValueError("invalid GPU reserve")
    if type(optional_voice_mib) is not int or not 0 <= optional_voice_mib <= 8192:
        raise ValueError("invalid GPU voice estimate")
    if not all(callable(f) for f in (gpu_reader, system_name, clock, sleeper)):
        raise TypeError("host-owned GPU, clock and sleep callbacks required")
    if system_name() != "Windows":
        return _unavailable("windows_host_required")
    ticks: list[GpuBudgetTick] = []
    try:
        for n in range(sample_count):
            if n:
                sleeper(interval)
            gpu = gpu_reader(index)
            at = clock()
            ticks.append(GpuBudgetTick(at, gpu))
        return assess_gpu_budget(
            ticks, reserve_mib=reserve_mib, optional_voice_mib=optional_voice_mib,
        )
    except Exception:
        return _unavailable("gpu_sample_failed_or_invalid")


def main(argv: list[str] | None = None) -> int:
    """One-command private hardware diagnostic; default is no sampling."""
    parser = argparse.ArgumentParser(
        description="STAR read-only Windows GPU survey (never starts a stream)."
    )
    parser.add_argument("--observe", action="store_true",
                        help="explicitly opt into local nvidia-smi sampling")
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--interval-ms", type=int, default=500)
    parser.add_argument("--reserve-mib", type=int, default=1536)
    args = parser.parse_args(argv)
    if not args.observe:
        print(_unavailable("explicit_observe_flag_required").to_json())
        return 2
    try:
        report = probe_windows_gpu_budget(
            owner_approved=True, index=args.index, sample_count=args.samples,
            spacing_s=args.interval_ms / 1000, reserve_mib=args.reserve_mib,
        )
    except (TypeError, ValueError, PermissionError):
        print(_unavailable("invalid_probe_configuration").to_json())
        return 2
    print(report.to_json())
    return 0 if report.status != "unavailable" else 1


if __name__ == "__main__":
    raise SystemExit(main())
