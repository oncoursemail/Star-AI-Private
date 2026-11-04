"""Read-only OS process identity bridge for Star's gaming/VTuber inference workers.

A verified on-disk model catalog is not evidence that a currently running
worker uses the model. This *opt-in* bridge connects a host-owned psutil process
handle to an already verified runtime artifact and the worker epoch registry.
It checks executable identity and process creation time before refreshing QoS
epochs. It never starts/stops processes, proves loaded model weights, or grants
microphone, playback, OBS, streaming, or game permissions.

An authorized local supervisor must select PIDs from processes it started;
never accept a PID, executable path or route mapping from a prompt, LLM,
viewer, Discord message or browser request. The process can exit just after a
probe: the supervisor must still perform final output and PCM-release checks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Callable, Mapping, Protocol, cast
import math
import stat

from .stream_host_artifact_preflight import HostArtifactPaths, _Reader, _is_link_or_reparse
from .stream_host_worker_epochs import (
    HostWorkerEpoch, HostWorkerEpochRegistry, HostWorkerObservation,
)

_MAX_EXEC_BYTES = 1 << 30


def _time_ms(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("monotonic host time required")
    try:
        number = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError("invalid monotonic host time") from exc
    if not math.isfinite(number) or not 0 <= number <= 1e13:
        raise ValueError("invalid monotonic host time")
    return number


class _ProcessHandle(Protocol):
    pid: int

    def is_running(self) -> bool: ...

    def status(self) -> str: ...

    def create_time(self) -> float: ...

    def exe(self) -> str: ...


def _default_process_factory(pid: int) -> _ProcessHandle:
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError("psutil desktop dependency is not installed") from exc
    return psutil.Process(pid)


@dataclass(frozen=True)
class WorkerProcessAdvice:
    current: bool
    reason: str
    authorizes_audio: bool = False
    authorizes_stream: bool = False


@dataclass
class _Pinned:
    handle: _ProcessHandle = field(repr=False)
    epoch: HostWorkerEpoch
    pid: int = field(repr=False)
    born: float = field(repr=False)
    executable_identity: tuple[int, int, int, int] = field(repr=False)


class HostOSWorkerSupervisor:
    """Bind a verified catalog route to an observed, live OS worker.

    attach() performs a one-time executable hash and OS identity check;
    refresh() performs cheap identity/liveness checks (no repeated hashing).
    Failure retires the route's epoch so old replies cannot be accepted by
    HostWorkerReplyFence. This is advisory infrastructure: the actual worker
    supervisor must own process handles, sockets, and output queue flushing.
    """

    def __init__(
        self,
        registry: HostWorkerEpochRegistry,
        artifact_root: str | Path,
        manifests: Mapping[str, HostArtifactPaths],
        *,
        clock_ms: Callable[[], float] = lambda: monotonic() * 1000,
        process_factory: Callable[[int], _ProcessHandle] | None = None,
    ) -> None:
        if not isinstance(registry, HostWorkerEpochRegistry):
            raise TypeError("verified host worker registry required")
        if type(manifests) is not dict or set(manifests) != set(registry._routes):
            raise ValueError("require owner-managed artifact manifest for every route")
        if any(not isinstance(x, HostArtifactPaths) for x in manifests.values()):
            raise TypeError("validated artifact paths required")
        if not callable(clock_ms):
            raise TypeError("trusted monotonic clock required")
        self._registry = registry
        self._root = Path(artifact_root)
        self._manifests = dict(manifests)
        self._clock = clock_ms
        self._factory = process_factory or _default_process_factory
        self._lock = RLock()
        self._enabled = False
        self._last_ms = 0.0
        self._active: dict[str, _Pinned] = {}
        self._accepted = 0
        self._retired = 0

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("trusted owner opt-in required")
        with self._lock:
            self._enabled = True

    def _now(self) -> float:
        now = _time_ms(self._clock())
        if now <= self._last_ms:
            raise ValueError("host clock reversed or repeated")
        self._last_ms = now
        return now

    def _runtime_path(self, alias: str) -> Path:
        # HostArtifactPaths validates every component; no traversal permitted.
        return self._root.joinpath(*self._manifests[alias].runtime_file.split("/"))

    @staticmethod
    def _identity(path: Path) -> tuple[int, int, int, int]:
        if _is_link_or_reparse(path.lstat()):
            raise ValueError("worker executable path cannot be symlink or reparse")
        info = path.stat()
        if (not stat.S_ISREG(info.st_mode) or info.st_size <= 0
                or info.st_size > _MAX_EXEC_BYTES):
            raise ValueError("worker runtime is not a bounded regular executable")
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)

    def _read_process(
        self, handle: _ProcessHandle, *, alias: str,
        expected_pid: int, expected_birth: float | None,
        expected_identity: tuple[int, int, int, int] | None,
    ) -> tuple[float, tuple[int, int, int, int]]:
        """Two-sided process recheck, with intentionally sanitized errors."""
        try:
            pid = handle.pid
            if type(pid) is not int or pid != expected_pid:
                raise ValueError("worker PID mismatch")
            if handle.is_running() is not True:
                raise ValueError("worker process is not running")
            if str(handle.status()).lower() in {"zombie", "dead", "stopped"}:
                raise ValueError("worker process is not active")
            born = float(handle.create_time())
            if not math.isfinite(born) or born <= 0:
                raise ValueError("invalid process birth")
            if expected_birth is not None and born != expected_birth:
                raise ValueError("worker PID was reused")
            proc_path = Path(handle.exe())
            expected_path = self._runtime_path(alias)
            # Executable is the ACTUAL OS process executable, not a model/client
            # assertion about which weights were loaded or Python entrypoint.
            if not proc_path.samefile(expected_path):
                raise ValueError("worker executable differs from verified runtime")
            identity = self._identity(expected_path)
            if expected_identity is not None and identity != expected_identity:
                raise ValueError("worker executable changed after enrollment")
            # A process may have exited or been replaced during the path check.
            if handle.is_running() is not True or float(handle.create_time()) != born:
                raise ValueError("worker process changed during observation")
            if not proc_path.samefile(expected_path):
                raise ValueError("worker runtime moved during observation")
            if self._identity(expected_path) != identity:
                raise ValueError("worker runtime changed during observation")
            return born, identity
        except (OSError, RuntimeError, ValueError, AttributeError, TypeError):
            raise ValueError("OS worker identity unavailable or changed") from None

    def attach(self, alias: str, *, pid: int, owner_approved: bool = False) -> HostWorkerEpoch:
        """Attach a supervisor-selected PID; verify the executable once."""
        if owner_approved is not True:
            raise PermissionError("owner-approved local worker enrollment required")
        if type(pid) is not int or not 1 <= pid < 2**31:
            raise ValueError("valid host-selected PID required")
        with self._lock:
            if not self._enabled:
                raise PermissionError("host worker probe is disabled")
            if type(alias) is not str or alias not in self._manifests:
                raise ValueError("unknown host worker route")
            if alias in self._active:
                raise ValueError("retire previous worker before replacement")
            now = self._now()
            try:
                handle = self._factory(pid)
                born, identity = self._read_process(
                    handle, alias=alias, expected_pid=pid,
                    expected_birth=None, expected_identity=None)
                # Hash only at enrollment. Uses the existing descriptor-anchored
                # preflight reader on Linux and reparse checks on Windows.
                reader = _Reader(self._root, _MAX_EXEC_BYTES)
                _, digest = reader.digest(self._manifests[alias].runtime_file)
                if digest != self._registry._routes[alias].runtime_sha256:
                    raise ValueError("runtime digest changed since preflight")
                second_born, second_identity = self._read_process(
                    handle, alias=alias, expected_pid=pid,
                    expected_birth=born, expected_identity=identity)
                if second_born != born or second_identity != identity:
                    raise ValueError("worker changed during enrollment")
            except (OSError, ValueError, RuntimeError, TypeError):
                raise ValueError("worker executable or process verification failed") from None
            epoch = self._registry.observe(
                alias, HostWorkerObservation(pid, born, now, digest),
                now_ms=now, owner_approved=True)
            self._active[alias] = _Pinned(handle, epoch, pid, born, identity)
            self._accepted += 1
            return epoch

    def refresh(self, epoch: HostWorkerEpoch) -> WorkerProcessAdvice:
        """Fail closed if the pinned OS process is dead or replaced."""
        if not isinstance(epoch, HostWorkerEpoch):
            raise TypeError("pinned worker epoch required")
        with self._lock:
            try:
                now = self._now()
            except ValueError:
                # A reset/rollback invalidates every monotonic freshness lease.
                self.disable()
                return WorkerProcessAdvice(False, "host_clock_invalid_and_routes_retired")
            pinned = self._active.get(epoch.alias)
            if not self._enabled or pinned is None or pinned.epoch is not epoch:
                return WorkerProcessAdvice(False, "worker_not_pinned")
            try:
                self._read_process(
                    pinned.handle, alias=epoch.alias, expected_pid=pinned.pid,
                    expected_birth=pinned.born, expected_identity=pinned.executable_identity)
                observed = HostWorkerObservation(
                    pinned.pid, pinned.born, now,
                    self._registry._routes[epoch.alias].runtime_sha256)
                current = self._registry.observe(
                    epoch.alias, observed, now_ms=now, owner_approved=True)
                if current is not epoch:
                    raise ValueError("unexpected OS worker epoch rotation")
            except (OSError, ValueError, RuntimeError, TypeError):
                self._registry.retire(epoch=epoch)
                del self._active[epoch.alias]
                self._retired += 1
                return WorkerProcessAdvice(False, "worker_process_stale_or_unavailable")
            return WorkerProcessAdvice(True, "live_matching_host_executable")

    def retire(self, epoch: HostWorkerEpoch) -> bool:
        """Remove only the exact handle; never stop/kill a user process."""
        if not isinstance(epoch, HostWorkerEpoch):
            raise TypeError("pinned worker epoch required")
        with self._lock:
            pinned = self._active.get(epoch.alias)
            if pinned is None or pinned.epoch is not epoch:
                return False
            del self._active[epoch.alias]
            self._registry.retire(epoch=epoch)
            self._retired += 1
            return True

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            for pinned in tuple(self._active.values()):
                self._registry.retire(epoch=pinned.epoch)
                self._retired += 1
            self._active.clear()

    def metrics(self) -> dict[str, int | bool]:
        """Never log process paths, PIDs, model bytes, voice or chat."""
        with self._lock:
            return {
                "enabled": self._enabled,
                "active": len(self._active),
                "accepted": self._accepted,
                "retired": self._retired,
            }


__all__ = ["HostOSWorkerSupervisor", "WorkerProcessAdvice"]
