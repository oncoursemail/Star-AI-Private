"""Read-only, owner-host recording-storage headroom fence for STAR rehearsals.

A healthy GPU and OBS process are insufficient if the recording volume is
nearly full. This guard samples the actual owner-selected output directory,
adds a fixed OS headroom reserve to a bounded bitrate/duration estimate,
and latches failures. It NEVER starts/stops OBS or authorizes recording.

The recording host must check it before and periodically during recording,
stop recording itself on a failure, and verify file finalization separately.
No file paths, volume serials, or private recording names enter the report.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from threading import RLock
from typing import Callable


_MIB = 1024 * 1024
_MAX_BYTES = 1 << 63


@dataclass(frozen=True)
class RecordingDiskAdvice:
    status: str  # candidate | deferred | unavailable
    reason: str
    free_mib: int | None
    required_mib: int
    stop_recording_requested: bool = False
    recording_authorized: bool = False
    broadcast_authorized: bool = False


class RecordingDiskGuard:
    """One-shot host fence for a local, existing recording output directory.

    `reserve_mib` is free space to protect the OS/other applications.
    `bitrate_mbps` is a planning estimate for total video+audio throughput.
    `maximum_seconds` is the initial recording horizon. The trusted host may
    reduce `remaining_seconds` on periodic checks, never increase the cap.
    A successful check is only an advisory, not consent or a recording permit.
    """

    def __init__(
        self,
        directory: str,
        *,
        reserve_mib: int = 8192,
        bitrate_mbps: int = 12,
        maximum_seconds: int = 1800,
        disk_reader: Callable[[str], object] = shutil.disk_usage,
    ) -> None:
        if (type(directory) is not str or not 1 <= len(directory) <= 1024
                or "\x00" in directory):
            raise ValueError("bounded recording directory required")
        if (type(reserve_mib) is not int or not 1024 <= reserve_mib <= 65536
                or type(bitrate_mbps) is not int or not 1 <= bitrate_mbps <= 200
                or type(maximum_seconds) is not int
                or not 30 <= maximum_seconds <= 14400):
            raise ValueError("invalid recording space budget")
        if not callable(disk_reader):
            raise TypeError("trusted disk reader required")
        # No filesystem I/O until the owner explicitly opts into a probe.
        path = Path(directory)
        if not path.is_absolute() or directory.startswith(("\\\\", "//")):
            raise ValueError("local absolute recording directory required")
        self._path = path
        self._reader = disk_reader
        self._reserve = reserve_mib * _MIB
        self._bitrate = bitrate_mbps * 1_000_000
        self._maximum_seconds = maximum_seconds
        self._lock = RLock()
        self._revoked = False
        self._samples = 0

    def check(
        self,
        *,
        owner_approved: bool = False,
        remaining_seconds: int | None = None,
        recording_active: bool = False,
    ) -> RecordingDiskAdvice:
        """Measure free bytes on the selected output volume, fail closed.

        For an active recording, the host must act on stop_recording_requested;
        this module cannot actually stop OBS or attest a finalized recording.
        """
        if owner_approved is not True:
            raise PermissionError("explicit local recording-headroom probe required")
        if type(recording_active) is not bool:
            raise ValueError("recording_active must be a strict host boolean")
        remaining = self._maximum_seconds if remaining_seconds is None else remaining_seconds
        if type(remaining) is not int or not 0 <= remaining <= self._maximum_seconds:
            raise ValueError("remaining recording horizon out of bounds")
        # Integer ceiling avoids underestimating the expected recording size.
        projected_bytes = (self._bitrate * remaining + 7) // 8
        required = self._reserve + projected_bytes
        required_mib = (required + _MIB - 1) // _MIB
        with self._lock:
            if self._revoked:
                return RecordingDiskAdvice(
                    "deferred", "recording_storage_revoked", None, required_mib,
                    stop_recording_requested=recording_active,
                )
            try:
                # A symlink or missing directory may point outside the host's
                # selected output volume; never promote uncertain evidence.
                if self._path.is_symlink() or not self._path.is_dir():
                    raise OSError("untrusted recording output directory")
                usage = self._reader(str(self._path))
                free = getattr(usage, "free")
                total = getattr(usage, "total")
                if (type(free) is not int or type(total) is not int
                        or not 0 <= free <= total <= _MAX_BYTES):
                    raise ValueError("invalid storage measurements")
                self._samples += 1
            except Exception:
                self._revoked = True
                return RecordingDiskAdvice(
                    "unavailable", "recording_disk_probe_unavailable",
                    None, required_mib,
                    stop_recording_requested=recording_active,
                )
            if free < required:
                self._revoked = True
                return RecordingDiskAdvice(
                    "deferred", "insufficient_recording_disk_headroom",
                    free // _MIB, required_mib,
                    stop_recording_requested=recording_active,
                )
            return RecordingDiskAdvice(
                "candidate", "recording_storage_headroom_observed",
                free // _MIB, required_mib,
            )

    def metrics(self) -> dict[str, int | bool]:
        with self._lock:
            return {"samples": self._samples, "revoked": self._revoked,
                    "recording_authorized": False, "broadcast_authorized": False}


__all__ = ["RecordingDiskAdvice", "RecordingDiskGuard"]
