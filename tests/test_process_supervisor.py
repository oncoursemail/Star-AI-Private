from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from star.process_supervisor import (
    ProcessTreeError,
    ProcessTreeSupervisor,
    start_managed_async_process,
    start_managed_process,
)


class FakeProcess:
    def __init__(self, pid: int = 4242):
        self.pid = pid
        self.returncode: int | None = None
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class FakeJobApi:
    def __init__(self):
        self.calls: list[tuple] = []
        self.active = 1
        self.fail_assign = False
        self.fail_resume = False

    def create_job(self):
        self.calls.append(("create",))
        return "job-1"

    def set_kill_on_close(self, job):
        self.calls.append(("kill_on_close", job))

    def assign_pid(self, job, pid):
        self.calls.append(("assign", job, pid))
        if self.fail_assign:
            raise OSError("assignment refused")

    def terminate(self, job, exit_code):
        self.calls.append(("terminate", job, exit_code))
        self.active = 0

    def active_processes(self, job):
        return self.active

    def close(self, job):
        self.calls.append(("close", job))
        self.active = 0

    def resume_primary_thread(self, pid):
        self.calls.append(("resume", pid))
        if self.fail_resume:
            raise OSError("resume refused")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    if Path(f"/proc/{pid}/stat").exists():
        try:
            return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
        except OSError:
            return False
    return True


def _wait_pid_gone(pid: int, timeout: float = 4.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not _pid_alive(pid):
            return True
        time.sleep(0.02)
    return not _pid_alive(pid)


def test_windows_job_object_is_assigned_and_close_reaps_members():
    api = FakeJobApi()
    process = FakeProcess()
    tree = ProcessTreeSupervisor(process, platform="nt", job_api=api)
    assert tree.mode == "windows_job"
    assert ("assign", "job-1", process.pid) in api.calls
    tree.close()
    assert api.calls[-1] == ("close", "job-1")
    assert api.active == 0  # fake KILL_ON_JOB_CLOSE


def test_windows_job_termination_uses_job_not_only_root():
    api = FakeJobApi()
    process = FakeProcess()
    tree = ProcessTreeSupervisor(process, platform="nt", job_api=api)
    tree.terminate(exit_code=23)
    assert ("terminate", "job-1", 23) in api.calls
    assert tree.wait_empty(0.1)


def test_windows_assignment_failure_is_reported_and_root_fallback_works():
    api = FakeJobApi()
    api.fail_assign = True
    process = FakeProcess()
    tree = ProcessTreeSupervisor(process, platform="nt", job_api=api)
    assert tree.mode == "root_only" and "assignment refused" in tree.error
    tree.terminate()
    assert process.killed


def test_managed_windows_worker_is_suspended_until_job_assignment():
    api = FakeJobApi()
    process = FakeProcess()
    captured = {}

    def factory(args, **kwargs):
        captured.update(kwargs)
        return process

    tree = start_managed_process(
        ["worker"], platform="nt", job_api=api, popen_factory=factory, require_tree=True
    )
    flags = captured["creationflags"]
    assert flags & 0x00000200  # CREATE_NEW_PROCESS_GROUP
    assert flags & 0x00000004  # CREATE_SUSPENDED
    assign_index = api.calls.index(("assign", "job-1", process.pid))
    resume_index = api.calls.index(("resume", process.pid))
    assert assign_index < resume_index
    assert tree.mode == "windows_job"


def test_assignment_failure_resumes_only_explicit_root_fallback():
    api = FakeJobApi()
    api.fail_assign = True
    process = FakeProcess()
    tree = start_managed_process(
        ["worker"], platform="nt", job_api=api, popen_factory=lambda *a, **k: process
    )
    assert tree.mode == "root_only"
    assert ("resume", process.pid) in api.calls
    assert not process.killed


def test_required_tree_assignment_failure_kills_suspended_worker_without_resuming():
    api = FakeJobApi()
    api.fail_assign = True
    process = FakeProcess()
    with pytest.raises(ProcessTreeError):
        start_managed_process(
            ["worker"], platform="nt", job_api=api, popen_factory=lambda *a, **k: process,
            require_tree=True,
        )
    assert process.killed
    assert ("resume", process.pid) not in api.calls


def test_resume_failure_after_assignment_fails_closed():
    api = FakeJobApi()
    api.fail_resume = True
    process = FakeProcess()
    with pytest.raises(ProcessTreeError):
        start_managed_process(
            ["worker"], platform="nt", job_api=api, popen_factory=lambda *a, **k: process,
            require_tree=True,
        )
    assert process.killed
    assert ("close", "job-1") in api.calls


def test_required_windows_tree_fails_closed_when_assignment_fails():
    api = FakeJobApi()
    api.fail_assign = True
    process = FakeProcess()
    with pytest.raises(ProcessTreeError):
        ProcessTreeSupervisor(process, platform="nt", job_api=api, require_tree=True)
    assert process.killed


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects only")
def test_windows_job_object_contains_child_created_after_assignment(tmp_path):
    ready = tmp_path / "ready"
    go = tmp_path / "go"
    pid_file = tmp_path / "child.pid"
    script = (
        "import pathlib,subprocess,sys,time\\n"
        "ready,go,pid_file=map(pathlib.Path,sys.argv[1:])\\n"
        "ready.write_text('ready')\\n"
        "deadline=time.monotonic()+10\\n"
        "while not go.exists() and time.monotonic()<deadline: time.sleep(0.01)\\n"
        "if not go.exists(): raise SystemExit(2)\\n"
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\\n"
        "pid_file.write_text(str(child.pid))\\n"
        "time.sleep(60)\\n"
    )
    tree = start_managed_process(
        [sys.executable, "-c", script, str(ready), str(go), str(pid_file)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        require_tree=True,
    )
    try:
        end = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < end:
            time.sleep(0.01)
        assert ready.exists()
        assert tree.mode == "windows_job"
        go.write_text("go")
        end = time.monotonic() + 5
        while not pid_file.exists() and time.monotonic() < end:
            time.sleep(0.01)
        assert pid_file.exists()
        tree.terminate()
        assert tree.wait_empty(5)
        tree.process.wait(timeout=5)
    finally:
        tree.close()


def test_invalid_wait_bounds_are_rejected():
    tree = ProcessTreeSupervisor(FakeProcess(), platform="other")
    for value in (-1, float("nan"), float("inf"), 31):
        with pytest.raises(ValueError):
            tree.wait_empty(value)
    with pytest.raises(ValueError):
        tree.wait_empty(1, 0)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process-group state checks")
def test_sync_close_kills_descendant_after_root_exits(tmp_path):
    pid_file = tmp_path / "child.pid"
    script = f"sleep 60 & echo $! > '{pid_file}'; exit 0"
    tree = start_managed_process(
        ["/bin/sh", "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert tree.mode == "posix_process_group"
    assert tree.process.wait(timeout=5) == 0
    child_pid = int(pid_file.read_text())
    tree.close()
    assert _wait_pid_gone(child_pid)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process-group state checks")
def test_sync_terminate_kills_running_descendants(tmp_path):
    pid_file = tmp_path / "child.pid"
    script = f"sleep 60 & echo $! > '{pid_file}'; wait"
    tree = start_managed_process(
        ["/bin/sh", "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    end = time.monotonic() + 3
    while not pid_file.exists() and time.monotonic() < end:
        time.sleep(0.01)
    child_pid = int(pid_file.read_text())
    tree.terminate()
    tree.process.wait(timeout=5)
    tree.close()
    assert _wait_pid_gone(child_pid)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process-group state checks")
def test_async_terminate_kills_running_descendants(tmp_path):
    async def run():
        pid_file = tmp_path / "async-child.pid"
        script = f"sleep 60 & echo $! > '{pid_file}'; wait"
        tree = await start_managed_async_process(
            "/bin/sh", "-c", script,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        end = time.monotonic() + 3
        while not pid_file.exists() and time.monotonic() < end:
            await asyncio.sleep(0.01)
        child_pid = int(pid_file.read_text())
        tree.terminate()
        await tree.process.wait()
        tree.close()
        assert _wait_pid_gone(child_pid)

    asyncio.run(run())
