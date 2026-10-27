"""Running other programs and listing processes, behind small interfaces so tests can use fakes.

Nothing here opens a window, uses a shell, or reads from stdin.
"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Protocol

CREATE_NO_WINDOW = 0x08000000


@dataclass
class CmdResult:
    code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


class Runner(Protocol):
    def run(self, argv: list[str], *, timeout: float, cwd: str | None = None,
            cancelled: Callable[[], bool] | None = None) -> CmdResult: ...

    def spawn(self, argv: list[str], *, cwd: str | None = None) -> int: ...


def _read(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            data = fh.read(4 * 1024 * 1024)
    except OSError:
        return ""
    for _ in range(3):
        try:
            os.unlink(path)
            break
        except OSError:
            time.sleep(0.05)  # a child that outlived us may still hold it; it is cleaned up on the next run
    return data.decode("utf-8", "replace")


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=10,
                           creationflags=CREATE_NO_WINDOW)
        else:
            proc.kill()
    except Exception:
        proc.kill()


class SubprocessRunner:
    """Runs a program to completion with output captured in temp FILES, not pipes.

    The RC tools start the game as a child process. A child started that way can inherit our pipe handles, and then a
    pipe read would not see end-of-file until the *game* closed. Files do not have that problem: we wait for the tool
    to exit, then read what it wrote.
    """

    def __init__(self, scratch: str | None = None):
        self.scratch = scratch

    def run(self, argv, *, timeout, cwd=None, cancelled=None) -> CmdResult:
        import tempfile
        if self.scratch:
            os.makedirs(self.scratch, exist_ok=True)
        out_f = tempfile.NamedTemporaryFile(prefix="run-", suffix=".out", dir=self.scratch, delete=False)
        err_f = tempfile.NamedTemporaryFile(prefix="run-", suffix=".err", dir=self.scratch, delete=False)
        timed_out = was_cancelled = False
        try:
            proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=out_f, stderr=err_f,
                                    creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
            end = time.monotonic() + timeout
            while True:
                try:
                    proc.wait(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if cancelled and cancelled():
                    was_cancelled = True
                elif time.monotonic() > end:
                    timed_out = True
                if timed_out or was_cancelled:
                    _kill_tree(proc)
                    proc.wait()
                    break
        finally:
            out_f.close()
            err_f.close()
        code = -1 if (timed_out or was_cancelled) else proc.returncode
        out, err = _read(out_f.name), _read(err_f.name)
        return CmdResult(code, out, err, timed_out=timed_out)

    def spawn(self, argv, *, cwd=None) -> int:
        proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                close_fds=True, creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        return proc.pid


class ProcessLister(Protocol):
    def snapshot(self) -> dict[int, str]: ...


def _toolhelp_snapshot() -> dict[int, str]:
    """pid -> lower-cased image name via the Windows ToolHelp API: a few milliseconds, no child process."""
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if snap in (None, wintypes.HANDLE(-1).value):
        return {}
    procs: dict[int, str] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            procs[int(entry.th32ProcessID)] = entry.szExeFile.lower()
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return procs


def _tasklist_snapshot() -> dict[int, str]:
    try:
        out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, timeout=20,
                             creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0).stdout.decode("utf-8", "replace")
    except Exception:
        return {}
    procs: dict[int, str] = {}
    for line in out.splitlines():
        parts = line.strip().strip('"').split('","')
        if len(parts) >= 2 and parts[1].isdigit():
            procs[int(parts[1])] = parts[0].lower()
    return procs


class WindowsProcesses:
    """pid -> lower-cased image name of every running process (ToolHelp, with `tasklist` as the fallback)."""

    def snapshot(self) -> dict[int, str]:
        if os.name == "nt":
            try:
                got = _toolhelp_snapshot()
                if got:
                    return got
            except Exception:
                pass
        return _tasklist_snapshot()


TasklistProcesses = WindowsProcesses  # older name
