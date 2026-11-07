"""Optional Windows job-tree regression tests; all portable tests are offline."""

import os
from hashlib import sha256

import pytest

from star.stream_admission import StreamHealthSample
from star.stream_budget import StreamTelemetry
from star.stream_gpu_lease_host_bridge import HostGPUWorkerLeaseBridge
from star.stream_host_artifact_pins import HostArtifactPin
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


def make(tmp_path, *, job=None, os_name="Windows", pin=False, strict=False):
    binary = tmp_path / "owned_worker.exe"
    binary.write_bytes(b"test fixture; never execute")
    plan = HostOptionalWorkerPlan(
        "optional-research",
        "research",
        300,
        binary,
        ("--offline",),
        tmp_path,
        executable_pin=(HostArtifactPin(binary, sha256(binary.read_bytes()).hexdigest())
                        if pin else None),
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
        require_artifact_pins=strict,
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


def test_artifact_pin_strict_launch_requires_explicit_owner_digest(tmp_path):
    host, plan, leases, _, _, launches = make(tmp_path, strict=True)
    host.enable(owner_approved=True)
    outcome = host.launch(plan, now_ms=1001, owner_approved=True)
    assert outcome.outcome == "deferred"
    assert outcome.reason == "trusted_launch_files_invalid"
    assert host.metrics()["artifact_pins_required"]
    assert not launches
    assert leases.metrics()["outstanding_claims"] == 0


def test_artifact_pin_strict_launch_accepts_matching_digest(tmp_path):
    host, plan, leases, _, _, launches = make(tmp_path, pin=True, strict=True)
    host.enable(owner_approved=True)
    assert host.launch(plan, now_ms=1001, owner_approved=True).outcome == "started"
    assert len(launches) == 1
    assert leases.metrics()["outstanding_claims"] == 1


def test_artifact_pin_refuses_mutated_binary_before_gpu_reservation(tmp_path):
    host, plan, leases, _, _, launches = make(tmp_path, pin=True, strict=True)
    host.enable(owner_approved=True)
    plan.executable.write_bytes(b"tampered binary; never execute")
    outcome = host.launch(plan, now_ms=1001, owner_approved=True)
    assert outcome.outcome == "deferred"
    assert not launches
    assert leases.metrics()["outstanding_claims"] == 0


def test_artifact_pin_refuses_symlink_swap(tmp_path):
    host, plan, leases, _, _, launches = make(tmp_path, pin=True, strict=True)
    host.enable(owner_approved=True)
    target = tmp_path / "replacement.exe"
    target.write_bytes(plan.executable.read_bytes())
    plan.executable.unlink()
    try:
        plan.executable.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("host cannot create symlinks")
    assert host.launch(plan, now_ms=1001, owner_approved=True).outcome == "deferred"
    assert leases.metrics()["outstanding_claims"] == 0
    assert not launches


def test_artifact_pin_rejects_wrong_path_and_digest(tmp_path):
    executable = tmp_path / "fixed.exe"
    executable.write_bytes(b"owned executable")
    correct = HostArtifactPin(executable, sha256(executable.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        HostArtifactPin(executable, "ABC")
    with pytest.raises(ValueError, match="absolute path"):
        HostArtifactPin(type(executable)("fixed.exe"), correct.sha256_hex)
    other = tmp_path / "other.exe"
    other.write_bytes(b"other")
    with pytest.raises(ValueError, match="must match"):
        HostOptionalWorkerPlan("p1", "research", 100, executable,
                               executable_pin=HostArtifactPin(
                                   other, sha256(other.read_bytes()).hexdigest()))
    with pytest.raises(ValueError, match="unique local files"):
        HostOptionalWorkerPlan("p1", "research", 100, executable,
                               additional_pins=(correct, correct))


def test_artifact_pin_additional_script_is_verified_before_launch(tmp_path):
    executable = tmp_path / "launcher.exe"
    executable.write_bytes(b"original launcher")
    script = tmp_path / "worker.py"
    script.write_bytes(b"print('original')")
    executable_pin = HostArtifactPin(executable, sha256(executable.read_bytes()).hexdigest())
    script_pin = HostArtifactPin(script, sha256(script.read_bytes()).hexdigest())
    plan = HostOptionalWorkerPlan(
        "p1", "research", 100, executable, (str(script),), tmp_path,
        executable_pin, (script_pin,),
    )
    assert plan.verified_command(require_artifact_pins=True)[0][0] == str(executable)
    script.write_bytes(b"print('tampered')")
    with pytest.raises(ValueError, match="artifact changed"):
        plan.verified_command(require_artifact_pins=True)


def test_artifact_pin_digest_check_fails_closed_after_missing_file(tmp_path):
    file = tmp_path / "optional.exe"
    file.write_bytes(b"trusted")
    pin = HostArtifactPin(file, sha256(file.read_bytes()).hexdigest())
    assert pin.verify()
    file.unlink()
    assert not pin.verify()


def test_artifact_pin_budget_refuses_oversized_sparse_file(tmp_path):
    from star.stream_host_artifact_pins import MAX_LAUNCH_HASH_BYTES

    file = tmp_path / "model-large.gguf"
    with file.open("wb") as out:
        out.truncate(MAX_LAUNCH_HASH_BYTES + 1)
    pin = HostArtifactPin(file, "0" * 64)
    assert not pin.verify()  # Do not hash the giant file on the live supervisor.
    with pytest.raises(ValueError, match="bounded launch-time"):
        pin.verify(max_bytes=MAX_LAUNCH_HASH_BYTES + 1)


def test_artifact_pin_cumulative_budget_is_enforced(tmp_path):
    from star.stream_host_artifact_pins import MAX_LAUNCH_HASH_BYTES

    binary = tmp_path / "model.exe"
    binary.write_bytes(b"original")
    huge = tmp_path / "data.bin"
    with huge.open("wb") as out:
        out.truncate(MAX_LAUNCH_HASH_BYTES)
    executable_pin = HostArtifactPin(binary, sha256(binary.read_bytes()).hexdigest())
    input_pin = HostArtifactPin(huge, "0" * 64)
    plan = HostOptionalWorkerPlan("p1", "research", 100, binary,
                                  executable_pin=executable_pin,
                                  additional_pins=(input_pin,))
    with pytest.raises(ValueError, match="too large"):
        plan.verified_command(require_artifact_pins=True)
