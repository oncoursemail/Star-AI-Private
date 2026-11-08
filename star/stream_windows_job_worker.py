"""Opt-in Windows Job Object containment for *disposable* optional AI workers.

CreateProcessW(CREATE_SUSPENDED) -> AssignProcessToJobObject -> ResumeThread
avoids a child-spawn race. No breakaway flags are granted. A retained job handle
with KILL_ON_JOB_CLOSE owns descendants; root exit alone is not tree exit.

This is NOT a sandbox or protection against a process deliberately creating
unrelated work via WMI, services, shell elevation, remote agents, etc.
Do not run hostile programs. Executable/argv must come only from the trusted
owner-configured HostOptionalWorkerPlan registry.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import subprocess
from typing import Any, Callable

_CREATE_SUSPENDED = 0x00000004
_CREATE_NO_WINDOW = 0x08000000
_JOB_KILL_ON_CLOSE = 0x00002000
_JOB_EXTENDED_LIMIT = 9
_JOB_BASIC_ACCOUNTING = 1
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258


class _BasicLimit(ctypes.Structure):
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


class _IOCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimit),
        ("IoInfo", _IOCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _BasicAccounting(ctypes.Structure):
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


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def _winapi() -> Any:
    if os.name != "nt":
        raise RuntimeError("Windows Job Object launch requires Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    void = ctypes.c_void_p
    DWORD = wintypes.DWORD
    BOOL = wintypes.BOOL
    kernel.CreateJobObjectW.argtypes = [void, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = void
    kernel.SetInformationJobObject.argtypes = [void, ctypes.c_int, void, DWORD]
    kernel.SetInformationJobObject.restype = BOOL
    kernel.AssignProcessToJobObject.argtypes = [void, void]
    kernel.AssignProcessToJobObject.restype = BOOL
    kernel.CreateProcessW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        void,
        void,
        BOOL,
        DWORD,
        void,
        wintypes.LPCWSTR,
        void,
        void,
    ]
    kernel.CreateProcessW.restype = BOOL
    kernel.ResumeThread.argtypes = [void]
    kernel.ResumeThread.restype = DWORD
    kernel.TerminateJobObject.argtypes = [void, wintypes.UINT]
    kernel.TerminateJobObject.restype = BOOL
    kernel.TerminateProcess.argtypes = [void, wintypes.UINT]
    kernel.TerminateProcess.restype = BOOL
    kernel.QueryInformationJobObject.argtypes = [void, ctypes.c_int, void, DWORD, void]
    kernel.QueryInformationJobObject.restype = BOOL
    kernel.WaitForSingleObject.argtypes = [void, DWORD]
    kernel.WaitForSingleObject.restype = DWORD
    kernel.GetExitCodeProcess.argtypes = [void, ctypes.POINTER(DWORD)]
    kernel.GetExitCodeProcess.restype = BOOL
    kernel.CloseHandle.argtypes = [void]
    kernel.CloseHandle.restype = BOOL
    return kernel


def _win_error() -> OSError:
    """Windows-only error helper, unavailable in POSIX ctypes type stubs."""
    return getattr(ctypes, "WinError")(getattr(ctypes, "get_last_error")())


class WindowsJobWorker:
    """Host-owned, race-free optional process tree with an original OS job handle.

    poll() observes the root only. active_processes() independently checks job
    members and MUST reach zero before a GPU lease may be released. terminate()
    targets the entire job, not just the root process.
    """

    def __init__(
        self, argv: list[str], cwd: str | None = None,
        *, pre_resume: Callable[[], bool] | None = None,
    ) -> None:
        if not argv or not os.path.isabs(argv[0]) or not argv[0].lower().endswith(".exe"):
            raise ValueError("host must select a fixed absolute .exe command")
        if any(not isinstance(x, str) or chr(0) in x for x in argv):
            raise ValueError("invalid command argument")
        if cwd is not None and not os.path.isabs(cwd):
            raise ValueError("host working directory must be absolute")
        if pre_resume is not None and not callable(pre_resume):
            raise TypeError("host-owned pre-resume verification must be callable")
        k = _winapi()
        self._kernel = k
        self._job = None
        self._process = None
        self._closed = False
        self.pid = 0
        thread = None
        assigned = False
        try:
            job = k.CreateJobObjectW(None, None)
            if not job:
                raise _win_error()
            self._job = job
            limits = _ExtendedLimit()
            limits.BasicLimitInformation.LimitFlags = _JOB_KILL_ON_CLOSE
            if not k.SetInformationJobObject(
                job,
                _JOB_EXTENDED_LIMIT,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ):
                raise _win_error()
            startup = _StartupInfo()
            startup.cb = ctypes.sizeof(startup)
            pi = _ProcessInfo()
            # Mutable buffer is mandatory for CreateProcessW. No shell, PATH
            # lookup or inherited handles. Root begins suspended.
            cmd = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
            if not k.CreateProcessW(
                argv[0],
                cmd,
                None,
                None,
                False,
                _CREATE_SUSPENDED | _CREATE_NO_WINDOW,
                None,
                cwd,
                ctypes.byref(startup),
                ctypes.byref(pi),
            ):
                raise _win_error()
            self._process = pi.hProcess
            thread = pi.hThread
            self.pid = int(pi.dwProcessId)
            if not k.AssignProcessToJobObject(job, pi.hProcess):
                raise _win_error()
            assigned = True
            # Run the trusted host's SECOND artifact check after a kernel Job
            # owns this still-suspended process, before a single instruction
            # from the optional worker is permitted to run. If files change
            # between reservation and execution, abort the entire Job.
            # This narrows but does not eliminate filesystem TOCTOU risks.
            if pre_resume is not None and pre_resume() is not True:
                raise ValueError("trusted artifact changed before worker resume")
            if k.ResumeThread(thread) == 0xFFFFFFFF:
                raise _win_error()
        except BaseException:
            # Any suspended root remains OUR handle. Kill on uncertainty and
            # never let it resume without a successfully assigned job.
            if self._process:
                if assigned and self._job:
                    k.TerminateJobObject(self._job, 1)
                else:
                    k.TerminateProcess(self._process, 1)
            self.close()
            raise
        finally:
            if thread:
                k.CloseHandle(thread)

    def poll(self) -> int | None:
        if self._closed or not self._process:
            raise RuntimeError("original Windows worker handle is closed")
        state = self._kernel.WaitForSingleObject(self._process, 0)
        if state == _WAIT_TIMEOUT:
            return None
        if state != _WAIT_OBJECT_0:
            raise _win_error()
        code = wintypes.DWORD()
        if not self._kernel.GetExitCodeProcess(self._process, ctypes.byref(code)):
            raise _win_error()
        return int(code.value)

    def active_processes(self) -> int:
        if self._closed or not self._job:
            raise RuntimeError("original Windows job handle is closed")
        info = _BasicAccounting()
        if not self._kernel.QueryInformationJobObject(
            self._job,
            _JOB_BASIC_ACCOUNTING,
            ctypes.byref(info),
            ctypes.sizeof(info),
            None,
        ):
            raise _win_error()
        return int(info.ActiveProcesses)

    def terminate(self) -> None:
        if self._closed or not self._job:
            raise RuntimeError("original Windows job handle is closed")
        if not self._kernel.TerminateJobObject(self._job, 1):
            raise _win_error()

    def close(self) -> None:
        if not getattr(self, "_closed", True):
            self._closed = True
            k = self._kernel
            if self._process:
                k.CloseHandle(self._process)
                self._process = None
            if self._job:
                # KILL_ON_JOB_CLOSE prevents surviving children on host exit.
                k.CloseHandle(self._job)
                self._job = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def spawn_windows_job(
    argv: list[str], cwd: str | None,
    *, pre_resume: Callable[[], bool] | None = None,
) -> WindowsJobWorker:
    """Only the trusted host may supply an optional pre-resume verifier."""
    return WindowsJobWorker(argv, cwd, pre_resume=pre_resume)


__all__ = ["WindowsJobWorker", "spawn_windows_job"]
