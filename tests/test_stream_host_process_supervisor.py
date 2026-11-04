"""Offline fake-OS tests for host executable identity, restarts and output fencing."""
from hashlib import sha256

import pytest

from star.stream_host_artifact_preflight import HostArtifactPaths, verify_host_artifacts
from star.stream_host_model_catalog import HostModelRoute
from star.stream_host_worker_epochs import HostWorkerEpochRegistry
from star.stream_host_process_supervisor import HostOSWorkerSupervisor
from star.stream_host_reply_fence import HostWorkerReplyFence
from star.stream_qos import InferenceJob, QoSDecision


class FakeProcess:
    def __init__(self, pid, exe, *, born=100.0):
        self.pid = pid
        self.path = str(exe)
        self.born = born
        self.running = True
        self.state = "running"
        self.fail_after = None
        self.checks = 0

    def is_running(self):
        self.checks += 1
        if self.fail_after is not None and self.checks >= self.fail_after:
            self.running = False
        return self.running

    def status(self):
        return self.state

    def create_time(self):
        return self.born

    def exe(self):
        return self.path


def setup(tmp_path, *, pid=64):
    (tmp_path / "model.gguf").write_bytes(b"mini-model")
    exe = tmp_path / "worker.exe"
    exe.write_bytes(b"trusted-runtime")
    route = HostModelRoute(
        "voice", "speech", "cpu", "small-local-tts",
        sha256(b"mini-model").hexdigest(),
        sha256(b"trusted-runtime").hexdigest(), 256, 0,
    )
    manifest = HostArtifactPaths(("model.gguf",), "worker.exe")
    verified = verify_host_artifacts(tmp_path, (route,), {"voice": manifest})
    registry = HostWorkerEpochRegistry(verified, (route,))
    times = [1000.0]

    def clock():
        times[0] += 10
        return times[0]

    proc = FakeProcess(pid, exe)
    processes = {pid: proc}

    def factory(which):
        return processes[which]

    supervisor = HostOSWorkerSupervisor(
        registry, tmp_path, {"voice": manifest},
        clock_ms=clock, process_factory=factory)
    return supervisor, registry, proc, times, processes, route


def test_owner_opt_in_executable_attestation_and_liveness(tmp_path):
    supervisor, registry, proc, _, _, _ = setup(tmp_path)
    with pytest.raises(PermissionError):
        supervisor.enable()
    with pytest.raises(PermissionError):
        supervisor.attach("voice", pid=64, owner_approved=True)
    supervisor.enable(owner_approved=True)
    with pytest.raises(PermissionError):
        supervisor.attach("voice", pid=64)
    epoch = supervisor.attach("voice", pid=64, owner_approved=True)
    assert registry.active_workers == 1
    decision = supervisor.refresh(epoch)
    assert decision.current and not decision.authorizes_audio and not decision.authorizes_stream
    assert registry.is_current(epoch, now_ms=1031)
    assert proc.checks >= 4
    assert supervisor.metrics() == {
        "enabled": True, "active": 1, "accepted": 1, "retired": 0}


def test_death_retires_epoch_blocks_delayed_speech_then_reenroll(tmp_path):
    supervisor, registry, proc, _, processes, _ = setup(tmp_path)
    supervisor.enable(owner_approved=True)
    epoch = supervisor.attach("voice", pid=64, owner_approved=True)
    job = registry.bind(
        InferenceJob("utterance", "speech", 1010, 1500, 1, 0, "auto"),
        epoch=epoch, now_ms=1011)
    fence = HostWorkerReplyFence(registry)
    fence.enable(owner_approved=True)
    permit = fence.arm(
        epoch=epoch, job=job,
        admission=QoSDecision(True, "admitted", "cpu", 17, None, 1300),
        now_ms=1011)
    proc.running = False
    failure = supervisor.refresh(epoch)
    assert failure.reason == "worker_process_stale_or_unavailable"
    assert registry.active_workers == 0
    assert not fence.claim(permit, now_ms=1030, host_output_ready=True).eligible
    replacement = FakeProcess(64, proc.path, born=101.0)
    processes[64] = replacement
    new_epoch = supervisor.attach("voice", pid=64, owner_approved=True)
    assert new_epoch.route_profile != epoch.route_profile
    assert supervisor.refresh(new_epoch).current
    assert not supervisor.retire(epoch)
    assert supervisor.metrics()["retired"] == 1


def test_executable_substitution_rejected(tmp_path):
    supervisor, registry, proc, _, _, _ = setup(tmp_path)
    other = tmp_path / "other.exe"
    other.write_bytes(b"untrusted")
    proc.path = str(other)
    supervisor.enable(owner_approved=True)
    with pytest.raises(ValueError, match="verification failed"):
        supervisor.attach("voice", pid=64, owner_approved=True)
    assert registry.active_workers == 0


def test_runtime_mutation_after_preflight_rejected_at_attach(tmp_path):
    supervisor, _, _, _, _, _ = setup(tmp_path)
    (tmp_path / "worker.exe").write_bytes(b"tampered runtime")
    supervisor.enable(owner_approved=True)
    with pytest.raises(ValueError, match="verification failed"):
        supervisor.attach("voice", pid=64, owner_approved=True)


@pytest.mark.parametrize("mutation", [
    "dead", "birth", "exe", "modified", "missing",
])
def test_runtime_or_process_changes_retire_worker(tmp_path, mutation):
    supervisor, registry, proc, _, _, _ = setup(tmp_path)
    supervisor.enable(owner_approved=True)
    epoch = supervisor.attach("voice", pid=64, owner_approved=True)
    if mutation == "dead":
        proc.state = "zombie"
    elif mutation == "birth":
        proc.born = 101.0  # PID reused
    elif mutation == "exe":
        other = tmp_path / "other.exe"
        other.write_bytes(b"other")
        proc.path = str(other)
    elif mutation == "modified":
        (tmp_path / "worker.exe").write_bytes(b"changed")
    elif mutation == "missing":
        (tmp_path / "worker.exe").unlink()
    assert not supervisor.refresh(epoch).current
    assert registry.active_workers == 0


def test_mid_observation_process_exit_cannot_attach(tmp_path):
    supervisor, registry, proc, _, _, _ = setup(tmp_path)
    supervisor.enable(owner_approved=True)
    proc.fail_after = 2
    with pytest.raises(ValueError, match="verification failed"):
        supervisor.attach("voice", pid=64, owner_approved=True)
    assert registry.active_workers == 0


def test_registry_rejects_reused_pid_and_untrusted_claim(tmp_path):
    supervisor, registry, proc, _, _, _ = setup(tmp_path)
    supervisor.enable(owner_approved=True)
    for pid in [True, 0, -1, 2**31, "64"]:
        with pytest.raises(ValueError):
            supervisor.attach("voice", pid=pid, owner_approved=True)
    with pytest.raises(ValueError, match="unknown"):
        supervisor.attach("unknown", pid=64, owner_approved=True)
    proc.pid = 65
    with pytest.raises(ValueError, match="verification failed"):
        supervisor.attach("voice", pid=64, owner_approved=True)
    proc.pid = 64
    epoch = supervisor.attach("voice", pid=64, owner_approved=True)
    with pytest.raises(ValueError, match="retire"):
        supervisor.attach("voice", pid=64, owner_approved=True)
    assert supervisor.retire(epoch)
    assert not supervisor.retire(epoch)
    assert registry.active_workers == 0


def test_readonly_disable_cannot_stop_process_or_reactivate_old_epoch(tmp_path):
    supervisor, registry, proc, _, _, _ = setup(tmp_path)
    supervisor.enable(owner_approved=True)
    epoch = supervisor.attach("voice", pid=64, owner_approved=True)
    supervisor.disable()
    assert proc.running and registry.active_workers == 0
    assert not supervisor.refresh(epoch).current
    assert supervisor.metrics()["enabled"] is False
    supervisor.enable(owner_approved=True)
    new = supervisor.attach("voice", pid=64, owner_approved=True)
    assert new is not epoch
    assert not registry.is_current(epoch, now_ms=1040)


def test_monotonic_clock_rollback_fails_closed(tmp_path):
    supervisor, registry, proc, times, _, _ = setup(tmp_path)
    supervisor.enable(owner_approved=True)
    epoch = supervisor.attach("voice", pid=64, owner_approved=True)
    times[0] -= 100
    assert supervisor.refresh(epoch).reason == "host_clock_invalid_and_routes_retired"
    assert registry.active_workers == 0
    assert supervisor.metrics()["enabled"] is False


def test_manifest_required_and_private_os_identifiers_not_logged(tmp_path):
    supervisor, registry, proc, _, _, _ = setup(tmp_path)
    with pytest.raises(ValueError, match="every route"):
        HostOSWorkerSupervisor(registry, tmp_path, {})
    with pytest.raises(TypeError, match="validated"):
        HostOSWorkerSupervisor(registry, tmp_path, {"voice": "worker.exe"})
    supervisor.enable(owner_approved=True)
    epoch = supervisor.attach("voice", pid=64, owner_approved=True)
    stats = str(supervisor.metrics())
    assert proc.path not in stats and "trusted-runtime" not in stats
    assert "pid" not in stats and "born" not in stats
    assert "_pid" not in repr(epoch) and "_born_unix_s" not in repr(epoch)


def test_symbolic_runtime_swap_is_not_accepted(tmp_path):
    supervisor, registry, proc, _, _, _ = setup(tmp_path)
    supervisor.enable(owner_approved=True)
    epoch = supervisor.attach("voice", pid=64, owner_approved=True)
    protected = tmp_path / "saved.exe"
    (tmp_path / "worker.exe").rename(protected)
    try:
        (tmp_path / "worker.exe").symlink_to(protected)
    except (NotImplementedError, OSError):
        pytest.skip("no symlink support on host")
    assert not supervisor.refresh(epoch).current
    assert registry.active_workers == 0
