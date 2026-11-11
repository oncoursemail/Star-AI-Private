"""Cross-platform process-tree containment for STAR-owned workers.

POSIX workers are started in a fresh session and stopped as a process group.
Windows workers are attached to a Job Object with KILL_ON_JOB_CLOSE. Windows
attachment happens immediately after process creation; a creation-time
PROC_THREAD_ATTRIBUTE_JOB_LIST launcher is a future hardening step.
"""
from __future__ import annotations

import asyncio
import ctypes
import math
import os
import signal
import subprocess
import time
from typing import Any, Protocol


class ProcessTreeError(RuntimeError):
    """A worker could not be placed under the requested process-tree supervisor."""


class JobApi(Protocol):
    def create_job(self) -> Any: ...
    def set_kill_on_close(self, job: Any) -> None: ...
    def assign_pid(self, job: Any, pid: int) -> None: ...
    def terminate(self, job: Any, exit_code: int) -> None: ...
    def active_processes(self, job: Any) -> int: ...
    def close(self, job: Any) -> None: ...


class _Win32JobApi:
    """Small ctypes wrapper around the documented Windows Job Object APIs."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise ProcessTreeError("Windows Job Objects are only available on Windows")
        from ctypes import wintypes

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_longlong),
                ("WriteOperationCount", ctypes.c_longlong),
                ("OtherOperationCount", ctypes.c_longlong),
                ("ReadTransferCount", ctypes.c_longlong),
                ("WriteTransferCount", ctypes.c_longlong),
                ("OtherTransferCount", ctypes.c_longlong),
            ]

        class BasicLimit(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class ExtendedLimit(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimit),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        class BasicAccounting(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_longlong),
                ("TotalKernelTime", ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", ctypes.c_longlong),
                ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                ("TotalPageFaultCount", wintypes.DWORD),
                ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD),
                ("TotalTerminatedProcesses", wintypes.DWORD),
            ]

        self._ExtendedLimit = ExtendedLimit
        self._BasicAccounting = BasicAccounting
        windll = getattr(ctypes, "WinDLL", None)
        if windll is None:
            raise ProcessTreeError("ctypes WinDLL is unavailable on this platform")
        self._kernel = windll("kernel32", use_last_error=True)

        self._create = self._kernel.CreateJobObjectW
        self._create.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self._create.restype = wintypes.HANDLE

        self._set = self._kernel.SetInformationJobObject
        self._set.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self._set.restype = wintypes.BOOL

        self._open = self._kernel.OpenProcess
        self._open.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._open.restype = wintypes.HANDLE

        self._assign = self._kernel.AssignProcessToJobObject
        self._assign.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self._assign.restype = wintypes.BOOL

        self._terminate = self._kernel.TerminateJobObject
        self._terminate.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self._terminate.restype = wintypes.BOOL

        self._query = self._kernel.QueryInformationJobObject
        self._query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                ctypes.POINTER(wintypes.DWORD)]
        self._query.restype = wintypes.BOOL

        self._close = self._kernel.CloseHandle
        self._close.argtypes = [wintypes.HANDLE]
        self._close.restype = wintypes.BOOL

    @staticmethod
    def _check(ok: Any, operation: str) -> None:
        if not ok:
            get_error = getattr(ctypes, "get_last_error", lambda: 0)
            format_error = getattr(ctypes, "FormatError", lambda code: f"Windows error {code}")
            error = get_error()
            raise OSError(error, f"{operation} failed: {format_error(error)}")

    def create_job(self) -> Any:
        handle = self._create(None, None)
        self._check(handle, "CreateJobObjectW")
        return handle

    def set_kill_on_close(self, job: Any) -> None:
        info = self._ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        self._check(self._set(job, 9, ctypes.byref(info), ctypes.sizeof(info)), "SetInformationJobObject")

    def assign_pid(self, job: Any, pid: int) -> None:
        process = self._open(0x0001 | 0x0100, False, pid)  # PROCESS_TERMINATE | PROCESS_SET_QUOTA
        self._check(process, "OpenProcess")
        try:
            self._check(self._assign(job, process), "AssignProcessToJobObject")
        finally:
            self._close(process)

    def terminate(self, job: Any, exit_code: int) -> None:
        self._check(self._terminate(job, exit_code), "TerminateJobObject")

    def active_processes(self, job: Any) -> int:
        info = self._BasicAccounting()
        self._check(self._query(job, 1, ctypes.byref(info), ctypes.sizeof(info), None),
                    "QueryInformationJobObject")
        return int(info.ActiveProcesses)

    def close(self, job: Any) -> None:
        self._check(self._close(job), "CloseHandle")


class ProcessTreeSupervisor:
    """Owns one process group (POSIX) or Job Object (Windows) for a STAR worker."""

    def __init__(
        self,
        process: Any,
        *,
        platform: str | None = None,
        group_owned: bool = False,
        job_api: JobApi | None = None,
        require_tree: bool = False,
    ) -> None:
        self.process = process
        self.pid = int(process.pid)
        self.platform = platform or os.name
        self.mode = "root_only"
        self.error = ""
        self._api: JobApi | None = None
        self._job: Any = None
        self._group_owned = self.platform == "posix" and group_owned
        self._closed = False

        if self._group_owned:
            self.mode = "posix_process_group"
        elif self.platform == "nt":
            api = job_api
            job = None
            try:
                api = api or _Win32JobApi()
                job = api.create_job()
                api.set_kill_on_close(job)
                api.assign_pid(job, self.pid)
                self._api, self._job = api, job
                self.mode = "windows_job"
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"[:240]
                if job is not None and api is not None:
                    try:
                        api.close(job)
                    except Exception:
                        pass
                if require_tree:
                    self._kill_root()
                    raise ProcessTreeError(f"could not contain worker process tree: {self.error}") from exc
        elif require_tree:
            self._kill_root()
            raise ProcessTreeError(f"process-tree supervision is unsupported on {self.platform!r}")

    def _alive(self) -> bool:
        poll = getattr(self.process, "poll", None)
        if callable(poll):
            return poll() is None
        return getattr(self.process, "returncode", None) is None

    def _kill_root(self) -> None:
        if self._alive():
            try:
                self.process.kill()
            except OSError:
                pass

    def _group_alive(self) -> bool:
        if not self._group_owned:
            return self._alive()
        try:
            os.killpg(self.pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def terminate(self, *, exit_code: int = 1) -> None:
        """Immediately stop the whole managed group; callers separately await the root process."""
        if self._closed:
            return
        if self._job is not None and self._api is not None:
            try:
                self._api.terminate(self._job, exit_code)
                return
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"[:240]
        if self._group_owned:
            try:
                os.killpg(self.pid, signal.SIGKILL)
                return
            except ProcessLookupError:
                return
            except OSError:
                pass
        self._kill_root()

    def wait_empty(self, timeout_s: float = 2.0, poll_s: float = 0.02) -> bool:
        """Boundedly verify that the job/process group has no active members."""
        if (type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or timeout_s < 0 or timeout_s > 30
                or type(poll_s) not in (int, float) or not math.isfinite(poll_s) or poll_s <= 0 or poll_s > 1):
            raise ValueError("invalid process-tree wait bounds")
        deadline = time.monotonic() + float(timeout_s)
        while True:
            if self._job is not None and self._api is not None:
                try:
                    empty = self._api.active_processes(self._job) == 0
                except Exception:
                    return False
            elif self._group_owned:
                empty = not self._group_alive()
            else:
                empty = not self._alive()
            if empty:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(min(float(poll_s), max(0.0, deadline - time.monotonic())))

    def close(self) -> None:
        """Release the Job Object or kill any POSIX descendants still in the worker's group."""
        if self._closed:
            return
        self._closed = True
        if self._job is not None and self._api is not None:
            job, api = self._job, self._api
            self._job = None
            try:
                api.close(job)  # KILL_ON_JOB_CLOSE cleans up descendants after the root exits.
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"[:240]
                try:
                    api.terminate(job, 1)
                except Exception:
                    self._kill_root()
        elif self._group_owned:
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                self._kill_root()
        else:
            self._kill_root()


def _creation_kwargs(platform: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    if platform == "posix":
        kwargs["start_new_session"] = True
    elif platform == "nt":
        # CREATE_NEW_PROCESS_GROUP; Job Object membership is attached immediately after launch.
        kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | 0x00000200
    return kwargs


def start_managed_process(
    args: Any,
    *,
    platform: str | None = None,
    job_api: JobApi | None = None,
    require_tree: bool = False,
    popen_factory: Any = subprocess.Popen,
    **kwargs: Any,
) -> ProcessTreeSupervisor:
    """Start a sync worker in a new process group / Windows Job Object."""
    target = platform or os.name
    proc = popen_factory(args, **_creation_kwargs(target, dict(kwargs)))
    try:
        return ProcessTreeSupervisor(proc, platform=target, group_owned=target == "posix",
                                     job_api=job_api, require_tree=require_tree)
    except Exception:
        if getattr(proc, "returncode", None) is None:
            try:
                proc.kill()
                proc.wait()
            except OSError:
                pass
        raise


async def start_managed_async_process(
    *args: Any,
    platform: str | None = None,
    job_api: JobApi | None = None,
    require_tree: bool = False,
    **kwargs: Any,
) -> ProcessTreeSupervisor:
    """Start an asyncio worker in a new process group / Windows Job Object."""
    target = platform or os.name
    proc = await asyncio.create_subprocess_exec(*args, **_creation_kwargs(target, dict(kwargs)))
    try:
        return ProcessTreeSupervisor(proc, platform=target, group_owned=target == "posix",
                                     job_api=job_api, require_tree=require_tree)
    except Exception:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise
