from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from star.process_shutdown import terminate_managed, terminate_managed_async
from star.process_supervisor import start_managed_process, start_managed_async_process


class FakeProcess:
    pid = 4242
    returncode = None

    async def wait(self):
        self.returncode = 0
        return 0


class FakeTree:
    mode = "windows_job"

    def __init__(self):
        self.process = FakeProcess()
        self.terminated = False

    @property
    def pid(self):
        return self.process.pid

    def terminate(self):
        self.terminated = True

    def wait_empty(self, timeout_s=2.0, poll_s=0.02):
        return self.terminated


def _wait_for(path: Path, timeout_s: float = 4.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert path.exists()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    stat = Path(f"/proc/{pid}/stat")
    if stat.exists():
        try:
            return stat.read_text().split()[2] != "Z"
        except OSError:
            return False
    return True


def _wait_pid_gone(pid: int, timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.02)
    return not _pid_alive(pid)


def test_sync_non_posix_uses_supervisor_hard_stop():
    tree = FakeTree()
    assert terminate_managed(tree)
    assert tree.terminated


def test_sync_posix_allows_worker_tree_to_exit_on_sigterm(tmp_path):
    ready = tmp_path / "child-ready"
    pid_file = tmp_path / "child.pid"
    child_code = (
        "import pathlib,signal,sys,time\n"
        "stopping=False\n"
        "def stop(*_):\n global stopping\n stopping=True\n"
        "signal.signal(signal.SIGTERM,stop)\n"
        "pathlib.Path(sys.argv[1]).write_text('ready')\n"
        "while not stopping: time.sleep(0.01)\n"
    )
    parent_code = (
        "import pathlib,signal,subprocess,sys,time\n"
        "stopping=False\n"
        "def stop(*_):\n global stopping\n stopping=True\n"
        "signal.signal(signal.SIGTERM,stop)\n"
        "child=subprocess.Popen([sys.executable,'-c',sys.argv[2],sys.argv[3]])\n"
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n"
        "while not stopping: time.sleep(0.01)\n"
        "child.wait(timeout=2)\n"
    )
    tree = start_managed_process(
        [sys.executable, "-c", parent_code, str(pid_file), child_code, str(ready)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for(pid_file)
        _wait_for(ready)
        child_pid = int(pid_file.read_text())
        assert terminate_managed(tree, grace_period_s=0.6)
        tree.process.wait(timeout=2)
        assert _wait_pid_gone(child_pid)
    finally:
        tree.close()


def test_sync_posix_escalates_when_worker_ignores_sigterm():
    code = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)"
    tree = start_managed_process(
        [sys.executable, "-c", code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert terminate_managed(tree, grace_period_s=0.12, kill_wait_s=2.0)
        tree.process.wait(timeout=2)
    finally:
        tree.close()

def test_async_posix_shutdown_is_bounded_and_reaps_group():
    async def run():
        tree = await start_managed_async_process(
            "/bin/sh",
            "-c",
            "trap 'exit 0' TERM; sleep 60",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert await terminate_managed_async(tree, grace_period_s=0.5)
        assert tree.process.returncode is not None
        tree.close()

    asyncio.run(run())


def test_invalid_shutdown_bounds_are_rejected():
    tree = FakeTree()
    for value in (-1, float("nan"), float("inf"), 5.1, True):
        with pytest.raises(ValueError):
            terminate_managed(tree, grace_period_s=value)
    with pytest.raises(ValueError):
        terminate_managed(tree, poll_s=0)
    with pytest.raises(ValueError):
        terminate_managed(tree, kill_wait_s=10.1)


@pytest.mark.skipif(os.name != "nt", reason="Windows uses Job Object hard-stop")
def test_windows_supervisor_keeps_job_termination_semantics():
    tree = FakeTree()
    assert terminate_managed(tree)
    assert tree.terminated
