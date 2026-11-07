"""Read-only, host-pinned NVIDIA VRAM observations for private Windows rehearsals.

nvidia-smi is a subprocess and MUST run on a supervisor/telemetry worker,
never in a game, streaming, avatar-animation or audio callback. This is not
GPU-memory attestation, a process launcher, a model benchmark or permission
to use the GPU. On failed or ambiguous observations optional lease admission
is disabled; existing claims remain charged until host-confirmed worker exit.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
import io
import math
from pathlib import Path
import platform
import re
import subprocess
import time
from typing import Callable

from .stream_admission import StreamHealthSample
from .stream_realtime_gpu_leases import RealtimeGPUWorkLeases

_GPU_UUID = re.compile(r"GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")
_QUERY = "--query-gpu=uuid,memory.total,memory.free"
_FORMAT = "--format=csv,noheader,nounits"
_MAX_OUTPUT = 512


class GPUProbeUnavailable(RuntimeError):
    """No usable GPU capacity evidence; no device-path or stdout details."""


@dataclass(frozen=True)
class NVIDIAFreeMemory:
    """Read-only local measurement, not a guarantee of future free memory."""

    observed_ms: float
    total_mib: int
    free_mib: int


class WindowsNVIDIAMemoryProbe:
    """Pinned executable and GPU UUID; no PATH lookup or model-supplied args.

    Owner chooses a non-symlink, absolute nvidia-smi.exe path and GPU UUID at
    configuration time. UUID selection avoids accidentally measuring an idle
    secondary GPU while launching a model on the gaming GPU.
    """

    def __init__(
        self,
        executable: Path,
        gpu_uuid: str,
        *,
        system_name: Callable[[], str] = platform.system,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        monotonic_ms: Callable[[], float] = lambda: time.monotonic() * 1000.0,
        timeout_seconds: float = 0.9,
    ) -> None:
        if (
            not isinstance(executable, Path)
            or not executable.is_absolute()
            or executable.suffix.lower() != ".exe"
            or executable.is_symlink()
            or not executable.is_file()
        ):
            raise ValueError("trusted, existing absolute nvidia-smi.exe is required")
        if type(gpu_uuid) is not str or not _GPU_UUID.fullmatch(gpu_uuid):
            raise ValueError("owner must pin a valid GPU UUID")
        if not all(callable(x) for x in (system_name, run, monotonic_ms)):
            raise TypeError("trusted local host dependencies must be callable")
        if (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds)
            or not 0.1 <= timeout_seconds <= 2.0
        ):
            raise ValueError("bounded query timeout required")
        self._executable = executable
        self._uuid = gpu_uuid
        self._system_name = system_name
        self._run = run
        self._clock = monotonic_ms
        self._timeout_seconds = float(timeout_seconds)

    def read(self) -> NVIDIAFreeMemory:
        """Query only the pinned local device. Fail closed on any uncertainty."""
        if self._system_name() != "Windows":
            raise GPUProbeUnavailable("Windows GPU host is required")
        if self._executable.is_symlink() or not self._executable.is_file():
            raise GPUProbeUnavailable("pinned NVIDIA executable unavailable")
        argv = [
            str(self._executable),
            _QUERY,
            _FORMAT,
            f"--id={self._uuid}",
        ]
        try:
            result = self._run(
                argv,
                check=False,
                shell=False,
                text=True,
                capture_output=True,
                timeout=self._timeout_seconds,
                stdin=subprocess.DEVNULL,
            )
            if (
                not isinstance(result, subprocess.CompletedProcess)
                or result.returncode != 0
                or type(result.stdout) is not str
                or len(result.stdout) > _MAX_OUTPUT
            ):
                raise GPUProbeUnavailable("GPU utility query failed")
            rows = list(csv.reader(io.StringIO(result.stdout)))
            if len(rows) != 1 or len(rows[0]) != 3:
                raise GPUProbeUnavailable("GPU utility returned ambiguous devices")
            uuid, total, free = (cell.strip() for cell in rows[0])
            if uuid.casefold() != self._uuid.casefold():
                raise GPUProbeUnavailable("GPU identity changed")
            if not re.fullmatch(r"[0-9]{1,6}", total) or not re.fullmatch(r"[0-9]{1,6}", free):
                raise GPUProbeUnavailable("GPU utility memory is not numeric")
            total_mib, free_mib = int(total), int(free)
            if not 256 <= total_mib <= 262144 or not 0 <= free_mib <= total_mib:
                raise GPUProbeUnavailable("GPU memory evidence invalid")
            observed = self._clock()
            if type(observed) not in (float, int) or not math.isfinite(observed) or not 0 <= observed <= 1e13:
                raise GPUProbeUnavailable("host monotonic clock invalid")
            return NVIDIAFreeMemory(float(observed), total_mib, free_mib)
        except (OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
            raise GPUProbeUnavailable("GPU utility unavailable or timed out") from exc


@dataclass(frozen=True)
class GPUObservationResult:
    """Admission observation result, never a permission to start or stop jobs."""

    accepted: bool
    reason: str
    authorizes_execution: bool = False
    authorizes_gameplay: bool = False
    authorizes_broadcast: bool = False


class WindowsGPUHealthObserver:
    """Merge pinned real GPU memory with host-verified game/OBS/voice signals.

    The host supplies all *other* signals through StreamHealthSample, sampled
    on the same system-monotonic clock. Unverified or clock-skewed inputs
    disable optional reservations immediately, never silently substitute
    synthetic telemetry or accept a stale previous GPU reading. DO NOT pass
    user-, viewer-, or LLM-authored StreamHealthSample objects.
    """

    def __init__(
        self,
        probe: WindowsNVIDIAMemoryProbe,
        leases: RealtimeGPUWorkLeases,
        *,
        maximum_skew_ms: int = 1000,
    ) -> None:
        if not isinstance(probe, WindowsNVIDIAMemoryProbe):
            raise TypeError("trusted GPU probe required")
        if not isinstance(leases, RealtimeGPUWorkLeases):
            raise TypeError("trusted GPU lease ledger required")
        if type(maximum_skew_ms) is not int or not 100 <= maximum_skew_ms <= 1500:
            raise ValueError("bounded host-sample skew required")
        self._probe = probe
        self._leases = leases
        self._max_skew_ms = maximum_skew_ms

    def observe(self, local: StreamHealthSample) -> GPUObservationResult:
        """Read-only GPU poll; does not perform any process or streaming action."""
        if type(local) is not StreamHealthSample or local.host_verified is not True:
            self._leases.disable()
            return GPUObservationResult(False, "untrusted_local_health_signals")
        try:
            reading = self._probe.read()
            if abs(local.observed_ms - reading.observed_ms) > self._max_skew_ms:
                raise GPUProbeUnavailable("host telemetry is not contemporaneous")
            old = local.telemetry
            t = replace(
                old,
                total_vram_mib=reading.total_mib,
                free_vram_mib=reading.free_mib,
            )
            fused = StreamHealthSample(
                observed_ms=reading.observed_ms,
                telemetry=t,
                obs_render_lag_pct=local.obs_render_lag_pct,
                obs_encode_lag_pct=local.obs_encode_lag_pct,
                host_verified=True,
            )
            if not self._leases.observe(fused):
                raise GPUProbeUnavailable("GPU observation rejected by lease ledger")
        except (GPUProbeUnavailable, ValueError, TypeError):
            self._leases.disable()
            return GPUObservationResult(False, "live_gpu_evidence_missing_optional_admission_disabled")
        return GPUObservationResult(True, "pinned_live_gpu_memory_observed")


__all__ = [
    "GPUProbeUnavailable",
    "NVIDIAFreeMemory",
    "WindowsNVIDIAMemoryProbe",
    "GPUObservationResult",
    "WindowsGPUHealthObserver",
]
