"""Offline launch-to-lease integration tests; no real Windows process starts."""
from pathlib import Path
from subprocess import Popen

import pytest

from star.stream_admission import StreamHealthSample
from star.stream_budget import StreamTelemetry
from star.stream_gpu_lease_host_bridge import HostGPUWorkerLeaseBridge
from star.stream_gpu_owned_worker_host import HostOwnedOptionalGPUWorkers
from star.stream_optional_gpu_launch_supervisor import (
    HostOptionalGPUWorkerLaunchSupervisor, HostOptionalWorkerPlan,
)
from star.stream_realtime_gpu_leases import RealtimeGPUWorkLeases


class Owned(Popen):
    def __init__(self, pid: int = 4271) -> None:
        self.pid = pid
        self.code = None
        self.termination_requests = 0
        self.fail_termination = False

    def poll(self):
        return self.code

    def terminate(self):
        self.termination_requests += 1
        if self.fail_termination:
            raise OSError("termination unavailable")


class Witness:
    def __init__(self, proc: Owned) -> None:
        self.proc = proc
        self.birth = 1_750_000_000.0
        self.uncertain = False

    @property
    def pid(self) -> int:
        return self.proc.pid

    def is_running(self) -> bool:
        if self.uncertain:
            raise OSError("unknown process")
        return self.proc.code is None

    def create_time(self) -> float:
        if self.uncertain:
            raise OSError("unknown creation time")
        return self.birth


def sample(now=1000, free=6500):
    return StreamHealthSample(
        now,
        StreamTelemetry(
            live=False, game_active=False, total_vram_mib=8192,
            free_vram_mib=free, game_fps=60, speech_backlog_ms=0,
        ),
        0, 0, True,
    )


def setup(tmp_path, *, free=6500, os="Windows", spawn_error=False,
          witness_error=False, process=None):
    binary = tmp_path / "fixed_worker.exe"
    binary.write_bytes(b"fixed owner binary for isolated tests")
    plan = HostOptionalWorkerPlan(
        "optional-research", "research", 500, binary, ("--local",),
        tmp_path,
    )
    proc = process or Owned()
    witness = Witness(proc)
    witness.uncertain = witness_error
    leases = RealtimeGPUWorkLeases()
    leases.enable(owner_approved=True)
    assert leases.observe(sample(free=free))
    bridge = HostGPUWorkerLeaseBridge(
        leases, process_factory=lambda _pid: witness,
    )
    workers = HostOwnedOptionalGPUWorkers(
        leases, bridge, system_name=lambda: os,
    )
    captured = []

    def spawn(argv, cwd):
        captured.append((argv, cwd))
        if spawn_error:
            raise OSError("ambiguous creation failure")
        return proc

    supervisor = HostOptionalGPUWorkerLaunchSupervisor(
        leases, workers, (plan,), system_name=lambda: os,
        spawn=spawn,
    )
    return supervisor, plan, leases, workers, proc, witness, captured


def test_windows_disabled_by_default_and_explicit_approval(tmp_path):
    host, plan, leases, _, _, _, captured = setup(tmp_path)
    with pytest.raises(PermissionError):
        host.enable()
    assert host.launch(plan, now_ms=1000, owner_approved=True).outcome == "deferred"
    assert not captured
    with pytest.raises(PermissionError):
        host.launch(plan, now_ms=1000)
    host.enable(owner_approved=True)
    assert host.metrics()["enabled"]
    with pytest.raises(RuntimeError):
        host.enable(owner_approved=True)
    assert leases.metrics()["outstanding_claims"] == 0


def test_windows_only_and_no_critical_workers(tmp_path):
    host, plan, _, _, _, _, captured = setup(tmp_path, os="Linux")
    with pytest.raises(RuntimeError):
        host.enable(owner_approved=True)
    assert not captured
    with pytest.raises(ValueError):
        HostOptionalWorkerPlan("obs", "speech", 1, plan.executable)
    with pytest.raises(ValueError):
        HostOptionalWorkerPlan("game", "gameplay", 1, plan.executable)
    with pytest.raises(ValueError):
        HostOptionalWorkerPlan("obs", "OBS", 1, plan.executable)


def test_only_original_host_plan_is_accepted(tmp_path):
    host, plan, leases, _, _, _, captured = setup(tmp_path)
    host.enable(owner_approved=True)
    copied = HostOptionalWorkerPlan(
        plan.alias, plan.kind, plan.vram_mib, plan.executable,
        plan.arguments, plan.working_directory,
    )
    with pytest.raises(PermissionError):
        host.launch(copied, now_ms=1001, owner_approved=True)
    assert not captured
    assert leases.metrics()["outstanding_claims"] == 0


def test_reject_untrusted_mutable_commands_and_missing_files(tmp_path):
    binary = tmp_path / "fake.exe"
    binary.write_bytes(b"safe fixture")
    with pytest.raises(ValueError):
        HostOptionalWorkerPlan("invalid", "research", 100, Path("relative.exe"))
    with pytest.raises(ValueError):
        HostOptionalWorkerPlan("bad", "research", 100, tmp_path / "missing.exe")
    with pytest.raises(ValueError):
        HostOptionalWorkerPlan("bad", "research", 100, binary, ["--shell"])
    with pytest.raises(ValueError):
        HostOptionalWorkerPlan("bad", "research", 100, binary, ("bad\x00",))
    with pytest.raises(ValueError):
        HostOptionalWorkerPlan("bad", "research", 100, binary, ("bad\n",))
    with pytest.raises(ValueError):
        HostOptionalWorkerPlan("bad", "research", True, binary)
    with pytest.raises(ValueError):
        HostOptionalWorkerPlan("bad", "research", 100, binary, (), tmp_path / "nope")


def test_launch_pins_host_owned_process_and_does_not_kill_without_pressure(tmp_path):
    host, plan, leases, workers, process, _, captured = setup(tmp_path)
    host.enable(owner_approved=True)
    result = host.launch(plan, now_ms=1001, owner_approved=True)
    assert result.outcome == "started"
    assert not result.authorizes_execution
    assert not result.authorizes_gameplay
    assert not result.authorizes_broadcast
    assert captured == [([str(plan.executable), "--local"], str(tmp_path))]
    assert leases.metrics()["started"] == 1
    assert workers.metrics()["owned_workers"] == 1
    assert host.tick(now_ms=1050).stop_requests_sent == 0
    assert process.termination_requests == 0
    assert leases.metrics()["outstanding_claims"] == 1


def test_pressure_revokes_then_requires_independent_confirmed_exit(tmp_path):
    host, plan, leases, _, process, _, _ = setup(tmp_path)
    host.enable(owner_approved=True)
    assert host.launch(plan, now_ms=1001, owner_approved=True).outcome == "started"
    assert leases.observe(sample(1100, free=700))
    assert host.tick(now_ms=1101).stop_requests_sent == 1
    assert host.tick(now_ms=1102).stop_requests_sent == 0
    assert process.termination_requests == 1
    assert leases.metrics()["outstanding_claims"] == 1
    assert host.launch(plan, now_ms=1103, owner_approved=True).outcome == "deferred"
    process.code = -15
    assert host.tick(now_ms=1104).exits_confirmed == 1
    assert leases.metrics()["outstanding_claims"] == 0


def test_low_vram_refuses_launch_before_spawning(tmp_path):
    host, plan, leases, _, _, _, captured = setup(tmp_path, free=1000)
    host.enable(owner_approved=True)
    result = host.launch(plan, now_ms=1001, owner_approved=True)
    assert result.outcome == "deferred"
    assert not captured
    assert leases.metrics()["outstanding_claims"] == 0


def test_stale_host_telemetry_refuses_launch(tmp_path):
    host, plan, _, _, _, _, captured = setup(tmp_path)
    host.enable(owner_approved=True)
    assert host.launch(plan, now_ms=9000, owner_approved=True).outcome == "deferred"
    assert not captured


def test_failed_witness_quarantines_original_host_handle(tmp_path):
    host, plan, leases, _, process, _, _ = setup(tmp_path, witness_error=True)
    host.enable(owner_approved=True)
    result = host.launch(plan, now_ms=1001, owner_approved=True)
    assert result.outcome == "quarantined"
    assert process.termination_requests == 1
    assert leases.metrics()["outstanding_claims"] == 1
    process.code = -1
    assert host.tick(now_ms=1002).exits_confirmed == 1


def test_ambiguous_spawn_error_faults_and_retains_reservation(tmp_path):
    host, plan, leases, _, _, _, captured = setup(tmp_path, spawn_error=True)
    host.enable(owner_approved=True)
    result = host.launch(plan, now_ms=1001, owner_approved=True)
    assert result.outcome == "fault"
    assert result.reason == "launch_uncertain_claim_retained"
    assert len(captured) == 1
    assert host.metrics()["faulted"]
    assert leases.metrics()["outstanding_claims"] == 1
    assert leases.metrics()["enabled"] is False
    with pytest.raises(RuntimeError):
        host.enable(owner_approved=True)


def test_stale_registry_executable_refused_on_launch(tmp_path):
    host, plan, leases, _, _, _, captured = setup(tmp_path)
    host.enable(owner_approved=True)
    plan.executable.unlink()
    result = host.launch(plan, now_ms=1001, owner_approved=True)
    assert result.reason == "trusted_launch_files_invalid"
    assert not captured
    assert leases.metrics()["outstanding_claims"] == 0


def test_owner_disable_revokes_real_worker_then_tracks_exit(tmp_path):
    host, plan, leases, _, process, _, _ = setup(tmp_path)
    host.enable(owner_approved=True)
    assert host.launch(plan, now_ms=1001, owner_approved=True).outcome == "started"
    host.disable()
    assert host.tick(now_ms=1010).stop_requests_sent == 1
    assert leases.metrics()["outstanding_claims"] == 1
    process.code = 0
    assert host.tick(now_ms=1011).exits_confirmed == 1
    assert leases.metrics()["outstanding_claims"] == 0


def test_insufficient_optional_concurrency_never_spawns_second_process(tmp_path):
    host, plan, leases, _, process, _, captured = setup(tmp_path)
    host.enable(owner_approved=True)
    assert host.launch(plan, now_ms=1001, owner_approved=True).outcome == "started"
    # Same host plan may not launch again while its prior lease is active.
    denied = host.launch(plan, now_ms=1002, owner_approved=True)
    assert denied.outcome == "deferred"
    assert denied.reason == "optional_plan_worker_already_outstanding"
    assert len(captured) == 1
    assert leases.metrics()["outstanding_claims"] == 1
    assert process.termination_requests == 0


def test_invalid_registry_cannot_be_instantiated(tmp_path):
    _, plan, leases, workers, _, _, _ = setup(tmp_path)
    with pytest.raises(ValueError):
        HostOptionalGPUWorkerLaunchSupervisor(
            leases, workers, (plan, plan), system_name=lambda: "Windows",
        )
    with pytest.raises(TypeError):
        HostOptionalGPUWorkerLaunchSupervisor(
            leases, workers, (object(),), system_name=lambda: "Windows",
        )
