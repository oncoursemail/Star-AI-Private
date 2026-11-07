"""Optional Windows job-tree regression tests; all portable tests are offline."""

import os

import pytest

from star.stream_admission import StreamHealthSample
from star.stream_budget import StreamTelemetry
from star.stream_gpu_lease_host_bridge import HostGPUWorkerLeaseBridge
from star.stream_gpu_owned_worker_host import HostOwnedOptionalGPUWorkers
from star.stream_optional_gpu_launch_supervisor import (
    HostOptionalGPUWorkerLaunchSupervisor,
    HostOptionalWorkerPlan,
)
from star.stream_realtime_gpu_leases import RealtimeGPUWorkLeases
from star.stream_windows_job_worker import WindowsJobWorker


class FakeJob(WindowsJobWorker):
    """Test double; must not initialize any real Win32 handles."""

    def __init__(self):
        self.pid = 4321
        self.code = None
        self.members = 1
        self.requests = 0
        self.closed = False
        self.query_fails = False
        self.poll_fails = False

    def poll(self):
        if self.poll_fails:
            raise OSError("original root handle unavailable")
        return self.code

    def active_processes(self):
        if self.query_fails:
            raise OSError("cannot read kernel Job Object")
        return self.members

    def terminate(self):
        self.requests += 1

    def close(self):
        self.closed = True

    def __del__(self):
        pass


def make(tmp_path, *, job=None, os_name="Windows"):
    binary = tmp_path / "owned_worker.exe"
    binary.write_bytes(b"test fixture; never execute")
    plan = HostOptionalWorkerPlan(
        "optional-research",
        "research",
        300,
        binary,
        ("--offline",),
        tmp_path,
    )
    leases = RealtimeGPUWorkLeases()
    leases.enable(owner_approved=True)
    health = StreamHealthSample(
        1000,
        StreamTelemetry(
            live=False,
            game_active=False,
            total_vram_mib=8192,
            free_vram_mib=6500,
            game_fps=60,
            speech_backlog_ms=0,
        ),
        0,
        0,
        True,
    )
    assert leases.observe(health)

    # A job-bound process must NOT be independently released by a psutil root
    # witness: the job's ActiveProcesses count is the release authority.
    def fail_root_witness(_pid):
        raise AssertionError("job mode must never bind root-only witness")

    bridge = HostGPUWorkerLeaseBridge(
        leases,
        process_factory=fail_root_witness,
    )
    workers = HostOwnedOptionalGPUWorkers(
        leases,
        bridge,
        system_name=lambda: os_name,
    )
    process = job or FakeJob()
    launches = []

    def spawn(argv, cwd):
        launches.append((argv, cwd))
        return process

    host = HostOptionalGPUWorkerLaunchSupervisor(
        leases,
        workers,
        (plan,),
        system_name=lambda: os_name,
        require_job_tree=True,
        job_spawn=spawn,
    )
    return host, plan, leases, workers, process, launches


def test_off_by_default_requires_owner_and_containment_policy(tmp_path):
    host, plan, leases, _, _, launches = make(tmp_path)
    assert host.metrics()["job_tree_containment_required"]
    assert host.launch(plan, now_ms=1001, owner_approved=True).outcome == "deferred"
    assert not launches
    with pytest.raises(PermissionError):
        host.enable()
    host.enable(owner_approved=True)
    assert host.launch(plan, now_ms=1001, owner_approved=True).outcome == "started"
    assert len(launches) == 1
    assert leases.metrics()["outstanding_claims"] == 1


def test_root_exits_but_child_remains_reservation_held(tmp_path):
    host, plan, leases, workers, job, _ = make(tmp_path)
    host.enable(owner_approved=True)
    assert host.launch(plan, now_ms=1001, owner_approved=True).outcome == "started"
    assert workers.metrics()["contained_jobs"] == 1
    job.code = 0  # original process exited
    job.members = 1  # still-running grandchild consumes VRAM
    result = host.tick(now_ms=1002)
    assert result.exits_confirmed == 0
    assert leases.metrics()["outstanding_claims"] == 1
    assert not job.closed
    host.disable()
    stopped = host.tick(now_ms=1003)
    assert stopped.stop_requests_sent == 1
    assert job.requests == 1  # terminate entire job, NOT just root
    assert leases.metrics()["outstanding_claims"] == 1
    assert host.tick(now_ms=1004).stop_requests_sent == 0
    job.members = 0
    assert host.tick(now_ms=1005).exits_confirmed == 1
    assert leases.metrics()["outstanding_claims"] == 0
    assert job.closed


def test_job_accounting_error_disables_admission_retains_claim(tmp_path):
    host, plan, leases, workers, job, _ = make(tmp_path)
    host.enable(owner_approved=True)
    assert host.launch(plan, now_ms=1001, owner_approved=True).outcome == "started"
    job.query_fails = True
    result = host.tick(now_ms=1002)
    assert result.uncertain_workers >= 1
    assert job.requests == 1
    assert not leases.metrics()["enabled"]
    assert leases.metrics()["outstanding_claims"] == 1
    job.query_fails = False
    job.code = 1
    job.members = 0
    assert host.tick(now_ms=1003).exits_confirmed == 1
    assert job.closed


def test_root_exited_before_enrollment_with_children_is_tracked(tmp_path):
    job = FakeJob()
    job.code = 0
    job.members = 2
    host, plan, leases, _, _, _ = make(tmp_path, job=job)
    host.enable(owner_approved=True)
    assert host.launch(plan, now_ms=1001, owner_approved=True).outcome == "started"
    assert leases.metrics()["outstanding_claims"] == 1
    assert host.tick(now_ms=1002).exits_confirmed == 0
    job.members = 0
    assert host.tick(now_ms=1003).exits_confirmed == 1
    assert job.closed


def test_already_empty_job_is_released_without_new_reservation_leak(tmp_path):
    job = FakeJob()
    job.code = 0
    job.members = 0
    host, plan, leases, _, _, _ = make(tmp_path, job=job)
    host.enable(owner_approved=True)
    result = host.launch(plan, now_ms=1001, owner_approved=True)
    assert result.outcome == "started"
    assert leases.metrics()["outstanding_claims"] == 0
    assert job.closed


def test_invalid_active_count_never_releases_claim(tmp_path):
    job = FakeJob()
    host, plan, leases, _, _, _ = make(tmp_path, job=job)
    host.enable(owner_approved=True)
    assert host.launch(plan, now_ms=1001, owner_approved=True).outcome == "started"
    job.members = -1
    job.code = 0
    assert host.tick(now_ms=1002).uncertain_workers
    assert leases.metrics()["outstanding_claims"] == 1
    assert job.requests == 1


def test_linux_cannot_enable_windows_job_mode(tmp_path):
    host, _plan, _, _, _job, launches = make(tmp_path, os_name="Linux")
    with pytest.raises(RuntimeError):
        host.enable(owner_approved=True)
    assert not launches


def test_win32_launcher_rejects_missing_absolute_executable():
    with pytest.raises(ValueError):
        WindowsJobWorker(["relative.exe"])
    if os.name != "nt":
        with pytest.raises(RuntimeError, match="requires Windows"):
            WindowsJobWorker(["/tmp/not_real.exe"])


def test_root_handle_failure_requests_whole_tree_stop(tmp_path):
    job = FakeJob()
    host, plan, leases, _, _, _ = make(tmp_path, job=job)
    host.enable(owner_approved=True)
    assert host.launch(plan, now_ms=1001, owner_approved=True).outcome == "started"
    job.poll_fails = True
    result = host.tick(now_ms=1002)
    assert result.uncertain_workers >= 1
    assert result.stop_requests_sent == 1
    assert job.requests == 1
    assert leases.metrics()["outstanding_claims"] == 1
    job.poll_fails = False
    job.code = 1
    job.members = 0
    assert host.tick(now_ms=1003).exits_confirmed == 1
