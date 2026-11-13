"""Per-process telemetry windows for calibrating STAR's background thinker.

The reader captures only an explicitly supplied PID, its process-start token,
CPU time, working set, and an optional provider-supplied GPU-memory value.
It never enumerates processes or reads names, paths, command lines, or content.

Windows GPU memory must come from a WDDM-aware provider. NVML per-process
usedGpuMemory is unavailable under WDDM, so a missing GPU reading remains
unknown and cannot be converted into an authorized calibration vector.
"""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
import os
import re
from pathlib import Path
from typing import Callable

from ..stream_workload_admission import ResourceVector
from .think_calibration import ThinkCalibrationPair

_MAX_PID = 2**32 - 1
_MAX_COUNTER = 2**63 - 1
_MAX_CLOCK_MS = 10**12
_MAX_WINDOW_MS = 5 * 60 * 1000
_MIB = 1024 * 1024


class IncompleteProcessTelemetry(RuntimeError):
    """A required process metric is unknown, stale, or unavailable."""


def _integer(value: object, label: str, *, minimum: int = 0, maximum: int = _MAX_COUNTER) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer in {minimum}..{maximum}")
    return value


def _opaque(value: object, label: str) -> str:
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}", value) is None:
        raise ValueError(f"{label} must be a bounded opaque identifier")
    return value


def _ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


@dataclass(frozen=True)
class ProcessIdentity:
    """PID plus a process-start token, preventing PID-reuse attribution."""

    pid: int
    start_token: int

    def __post_init__(self) -> None:
        _integer(self.pid, "pid", minimum=1, maximum=_MAX_PID)
        _integer(self.start_token, "start_token", minimum=1)


@dataclass(frozen=True)
class ProcessCounters:
    """One read-only process snapshot; GPU memory is explicitly nullable."""

    identity: ProcessIdentity
    cpu_time_100ns: int
    working_set_bytes: int
    gpu_memory_bytes: int | None = None

    def __post_init__(self) -> None:
        if type(self.identity) is not ProcessIdentity:
            raise TypeError("identity must be ProcessIdentity")
        _integer(self.cpu_time_100ns, "cpu_time_100ns")
        _integer(self.working_set_bytes, "working_set_bytes")
        if self.gpu_memory_bytes is not None:
            _integer(self.gpu_memory_bytes, "gpu_memory_bytes")


@dataclass(frozen=True)
class ThinkProcessWindow:
    """Bounded aggregate for one process over a monotonic observation window."""

    sample_id: str
    identity: ProcessIdentity
    clock_epoch: str
    configuration_fingerprint: str
    start_ms: int
    end_ms: int
    cpu_millicores: int
    peak_working_set_bytes: int
    peak_gpu_memory_bytes: int | None
    sample_count: int

    def __post_init__(self) -> None:
        _opaque(self.sample_id, "sample_id")
        if type(self.identity) is not ProcessIdentity:
            raise TypeError("identity must be ProcessIdentity")
        _opaque(self.clock_epoch, "clock_epoch")
        if (type(self.configuration_fingerprint) is not str
                or len(self.configuration_fingerprint) != 64
                or any(char not in "0123456789abcdef" for char in self.configuration_fingerprint)):
            raise ValueError("configuration_fingerprint must be lowercase SHA-256 hex")
        start = _integer(self.start_ms, "start_ms", maximum=_MAX_CLOCK_MS)
        end = _integer(self.end_ms, "end_ms", maximum=_MAX_CLOCK_MS)
        if end - start < 100 or end - start > _MAX_WINDOW_MS:
            raise ValueError("process window must span 100 ms to five minutes")
        _integer(self.cpu_millicores, "cpu_millicores", maximum=1_000_000_000)
        _integer(self.peak_working_set_bytes, "peak_working_set_bytes")
        if self.peak_gpu_memory_bytes is not None:
            _integer(self.peak_gpu_memory_bytes, "peak_gpu_memory_bytes")
        if type(self.sample_count) is not int or not 2 <= self.sample_count <= 4096:
            raise ValueError("sample_count must be in 2..4096")

    def to_resource_vector(self) -> ResourceVector:
        """Convert only complete measurements; unknown GPU memory is never zero."""
        if self.peak_gpu_memory_bytes is None:
            raise IncompleteProcessTelemetry("per-process GPU memory is unavailable")
        return ResourceVector(
            self.cpu_millicores,
            _ceil_div(self.peak_working_set_bytes, _MIB),
            _ceil_div(self.peak_gpu_memory_bytes, _MIB),
        )


class ThinkProcessWindowAccumulator:
    """Build a bounded process window from frequent snapshots of one PID.

    Sample at roughly 100–250 ms on a background collector thread. A gap over
    max_sample_gap_ms invalidates the window because the observed memory peak
    may otherwise miss a transient allocation. This object performs no I/O.
    """

    def __init__(
        self,
        *,
        sample_id: str,
        identity: ProcessIdentity,
        clock_epoch: str,
        configuration_fingerprint: str,
        started_monotonic_ms: int,
        max_duration_ms: int = 60_000,
        max_sample_gap_ms: int = 500,
        max_samples: int = 1024,
    ) -> None:
        self._sample_id = _opaque(sample_id, "sample_id")
        if type(identity) is not ProcessIdentity:
            raise TypeError("identity must be ProcessIdentity")
        self._identity = identity
        self._clock_epoch = _opaque(clock_epoch, "clock_epoch")
        if (type(configuration_fingerprint) is not str
                or len(configuration_fingerprint) != 64
                or any(char not in "0123456789abcdef" for char in configuration_fingerprint)):
            raise ValueError("configuration_fingerprint must be lowercase SHA-256 hex")
        self._fingerprint = configuration_fingerprint
        self._started_ms = _integer(started_monotonic_ms, "started_monotonic_ms", maximum=_MAX_CLOCK_MS)
        if type(max_duration_ms) is not int or not 100 <= max_duration_ms <= _MAX_WINDOW_MS:
            raise ValueError("max_duration_ms must be in 100..300000")
        if type(max_sample_gap_ms) is not int or not 50 <= max_sample_gap_ms <= 5_000:
            raise ValueError("max_sample_gap_ms must be in 50..5000")
        if type(max_samples) is not int or not 2 <= max_samples <= 4096:
            raise ValueError("max_samples must be in 2..4096")
        self._max_duration_ms = max_duration_ms
        self._max_gap_ms = max_sample_gap_ms
        self._max_samples = max_samples
        self._first_at: int | None = None
        self._last_at: int | None = None
        self._first_cpu: int | None = None
        self._last_cpu: int | None = None
        self._peak_working_set = 0
        self._peak_gpu: int | None = None
        self._gpu_complete = True
        self._sample_count = 0
        self._closed = False

    def observe(self, counters: ProcessCounters, *, at_ms: int) -> None:
        """Add one process snapshot; identity, counter, and clock regressions fail closed."""
        if self._closed:
            raise RuntimeError("process window is closed")
        if type(counters) is not ProcessCounters:
            raise TypeError("counters must be ProcessCounters")
        if counters.identity != self._identity:
            raise ValueError("process identity changed; possible PID reuse or worker restart")
        at = _integer(at_ms, "at_ms", maximum=_MAX_CLOCK_MS)
        if at < self._started_ms or at - self._started_ms > self._max_duration_ms:
            raise ValueError("observation is outside the configured process window")
        if self._sample_count >= self._max_samples:
            raise OverflowError("process window sample capacity reached")
        if self._last_at is not None:
            if at <= self._last_at:
                raise ValueError("process observation timestamps must increase")
            if at - self._last_at > self._max_gap_ms:
                raise IncompleteProcessTelemetry("sampling gap is too large to trust peak memory")
            assert self._last_cpu is not None
            if counters.cpu_time_100ns < self._last_cpu:
                raise ValueError("process CPU counter moved backwards")
        else:
            self._first_at = at
            self._first_cpu = counters.cpu_time_100ns

        self._last_at = at
        self._last_cpu = counters.cpu_time_100ns
        self._peak_working_set = max(self._peak_working_set, counters.working_set_bytes)
        if counters.gpu_memory_bytes is None:
            self._gpu_complete = False
        elif self._gpu_complete:
            self._peak_gpu = max(self._peak_gpu or 0, counters.gpu_memory_bytes)
        self._sample_count += 1

    def finalize(self, *, now_ms: int) -> ThinkProcessWindow:
        """Freeze the aggregate once; stale final observations are rejected."""
        if self._closed:
            raise RuntimeError("process window is already closed")
        now = _integer(now_ms, "now_ms", maximum=_MAX_CLOCK_MS)
        if self._sample_count < 2 or self._first_at is None or self._last_at is None:
            raise ValueError("at least two process observations are required")
        if now < self._last_at or now - self._last_at > self._max_gap_ms:
            raise IncompleteProcessTelemetry("latest process observation is stale")
        assert self._first_cpu is not None and self._last_cpu is not None
        duration_ms = self._last_at - self._first_at
        if duration_ms < 100:
            raise ValueError("process window must span at least 100 ms")
        cpu_delta = self._last_cpu - self._first_cpu
        cpu_millicores = _ceil_div(cpu_delta * 1000, duration_ms * 10_000)
        if cpu_millicores > 1_000_000_000:
            raise ValueError("process CPU measurement exceeds supported allocation units")
        result = ThinkProcessWindow(
            sample_id=self._sample_id,
            identity=self._identity,
            clock_epoch=self._clock_epoch,
            configuration_fingerprint=self._fingerprint,
            start_ms=self._first_at,
            end_ms=self._last_at,
            cpu_millicores=cpu_millicores,
            peak_working_set_bytes=self._peak_working_set,
            peak_gpu_memory_bytes=self._peak_gpu if self._gpu_complete else None,
            sample_count=self._sample_count,
        )
        self._closed = True
        return result

    def abort(self) -> bool:
        """Discard measurements without returning a partial resource estimate."""
        if self._closed:
            return False
        self._first_at = None
        self._last_at = None
        self._first_cpu = None
        self._last_cpu = None
        self._peak_working_set = 0
        self._peak_gpu = None
        self._sample_count = 0
        self._closed = True
        return True


def build_think_calibration_pair(
    *,
    sample_id: str,
    sequence: int,
    baseline: ThinkProcessWindow,
    active: ThinkProcessWindow,
) -> ThinkCalibrationPair:
    """Convert non-overlapping windows for the same worker into a calibration pair."""
    if type(baseline) is not ThinkProcessWindow or type(active) is not ThinkProcessWindow:
        raise TypeError("baseline and active must be ThinkProcessWindow values")
    if baseline.identity != active.identity:
        raise ValueError("baseline and active windows must belong to the same process lifetime")
    if baseline.clock_epoch != active.clock_epoch:
        raise ValueError("baseline and active windows must share a host clock epoch")
    if baseline.configuration_fingerprint != active.configuration_fingerprint:
        raise ValueError("baseline and active windows must share an inference configuration")
    if baseline.end_ms > active.start_ms:
        raise ValueError("baseline and active process windows must not overlap")
    if active.end_ms - baseline.end_ms > _MAX_WINDOW_MS:
        raise ValueError("baseline-to-active calibration interval exceeds five minutes")
    return ThinkCalibrationPair(
        sample_id=sample_id,
        sequence=sequence,
        clock_epoch=baseline.clock_epoch,
        configuration_fingerprint=baseline.configuration_fingerprint,
        baseline_monotonic_ms=baseline.end_ms,
        active_monotonic_ms=active.end_ms,
        baseline=baseline.to_resource_vector(),
        active=active.to_resource_vector(),
    )


def _gpu_value(probe: Callable[[int, int], int | None] | None, pid: int, start_token: int) -> int | None:
    if probe is None:
        return None
    try:
        value = probe(pid, start_token)
        if value is None:
            return None
        return _integer(value, "gpu_memory_probe result")
    except Exception:
        return None


def read_windows_process_counters(
    pid: int,
    *,
    gpu_memory_probe: Callable[[int, int], int | None] | None = None,
) -> ProcessCounters | None:
    """Read CPU time and working set for one PID using Win32 APIs.

    GPU memory is supplied by an optional WDDM-aware provider. Do not use
    NVML usedGpuMemory for this on WDDM; it is documented as unavailable.
    """
    _integer(pid, "pid", minimum=1, maximum=_MAX_PID)
    if os.name != "nt":
        return None
    try:
        from ctypes import wintypes

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

        class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME),
            ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME),
        ]
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX), wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

        # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ. No write/terminate rights.
        handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            return None
        try:
            created, exited, kernel, user = FILETIME(), FILETIME(), FILETIME(), FILETIME()
            memory = PROCESS_MEMORY_COUNTERS_EX()
            memory.cb = ctypes.sizeof(memory)
            if not kernel32.GetProcessTimes(
                handle, ctypes.byref(created), ctypes.byref(exited),
                ctypes.byref(kernel), ctypes.byref(user),
            ):
                return None
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
                return None

            def filetime_value(value: FILETIME) -> int:
                return (value.dwHighDateTime << 32) | value.dwLowDateTime

            start_token = filetime_value(created)
            cpu_time = filetime_value(kernel) + filetime_value(user)
            gpu_bytes = _gpu_value(gpu_memory_probe, pid, start_token)
            return ProcessCounters(
                ProcessIdentity(pid, start_token),
                cpu_time,
                int(memory.WorkingSetSize),
                gpu_bytes,
            )
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None


def parse_proc_stat(
    pid: int,
    text: str,
    *,
    page_size: int,
    clock_ticks: int,
    gpu_memory_probe: Callable[[int, int], int | None] | None = None,
) -> ProcessCounters:
    """Parse Linux /proc/<pid>/stat without splitting the parenthesized comm field."""
    _integer(pid, "pid", minimum=1, maximum=_MAX_PID)
    if type(text) is not str:
        raise TypeError("text must be str")
    _integer(page_size, "page_size", minimum=1, maximum=1_000_000)
    _integer(clock_ticks, "clock_ticks", minimum=1, maximum=1_000_000)
    left = text.find("(")
    right = text.rfind(")")
    if left <= 0 or right <= left or text[:left].strip() != str(pid):
        raise ValueError("proc stat PID or comm field is malformed")
    fields = text[right + 1:].strip().split()
    if len(fields) <= 21:
        raise ValueError("proc stat record is truncated")
    try:
        user_ticks = int(fields[11])
        kernel_ticks = int(fields[12])
        start_token = int(fields[19])
        resident_pages = int(fields[21])
    except ValueError as exc:
        raise ValueError("proc stat contains invalid numeric fields") from exc
    if min(user_ticks, kernel_ticks, resident_pages) < 0 or start_token <= 0:
        raise ValueError("proc stat contains negative counters or invalid process start")
    cpu_time = (user_ticks + kernel_ticks) * 10_000_000 // clock_ticks
    working_set = resident_pages * page_size
    gpu_bytes = _gpu_value(gpu_memory_probe, pid, start_token)
    return ProcessCounters(
        ProcessIdentity(pid, start_token),
        cpu_time,
        working_set,
        gpu_bytes,
    )


class ProcfsProcessReader:
    """Linux /proc reader for one explicit PID; no process enumeration."""

    def __init__(
        self,
        *,
        proc_root: str | Path = "/proc",
        gpu_memory_probe: Callable[[int, int], int | None] | None = None,
        page_size: int | None = None,
        clock_ticks: int | None = None,
    ) -> None:
        self._root = Path(proc_root)
        self._gpu_probe = gpu_memory_probe
        self._page_size = page_size or int(os.sysconf("SC_PAGE_SIZE"))
        self._clock_ticks = clock_ticks or int(os.sysconf("SC_CLK_TCK"))
        _integer(self._page_size, "page_size", minimum=1, maximum=1_000_000)
        _integer(self._clock_ticks, "clock_ticks", minimum=1, maximum=1_000_000)

    def read(self, pid: int) -> ProcessCounters | None:
        _integer(pid, "pid", minimum=1, maximum=_MAX_PID)
        if os.name == "nt":
            return None
        try:
            content = (self._root / str(pid) / "stat").read_text(encoding="ascii")
            return parse_proc_stat(
                pid,
                content,
                page_size=self._page_size,
                clock_ticks=self._clock_ticks,
                gpu_memory_probe=self._gpu_probe,
            )
        except (OSError, UnicodeError, ValueError, TypeError):
            return None


class WindowsProcessReader:
    """Windows per-process CPU/RAM reader with an injected WDDM GPU provider."""

    def __init__(
        self,
        *,
        gpu_memory_probe: Callable[[int, int], int | None] | None = None,
    ) -> None:
        self._gpu_probe = gpu_memory_probe

    def read(self, pid: int) -> ProcessCounters | None:
        return read_windows_process_counters(pid, gpu_memory_probe=self._gpu_probe)


def system_process_reader(
    *,
    gpu_memory_probe: Callable[[int, int], int | None] | None = None,
) -> WindowsProcessReader | ProcfsProcessReader:
    """Choose the local process reader without starting background polling."""
    if os.name == "nt":
        return WindowsProcessReader(gpu_memory_probe=gpu_memory_probe)
    return ProcfsProcessReader(gpu_memory_probe=gpu_memory_probe)


__all__ = [
    "IncompleteProcessTelemetry",
    "ProcessIdentity",
    "ProcessCounters",
    "ThinkProcessWindow",
    "ThinkProcessWindowAccumulator",
    "build_think_calibration_pair",
    "read_windows_process_counters",
    "parse_proc_stat",
    "ProcfsProcessReader",
    "WindowsProcessReader",
    "system_process_reader",
]
