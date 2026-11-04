"""Deterministic end-to-end worker-process / final-reply safety regression.

No OBS, games, microphones, network, model load or Windows actions performed.
"""
from dataclasses import replace
from hashlib import sha256

import pytest

from star.stream_host_artifact_preflight import HostArtifactPaths, verify_host_artifacts
from star.stream_host_live_output_gate import HostLiveOutputGate
from star.stream_host_model_catalog import HostModelRoute
from star.stream_host_process_supervisor import HostOSWorkerSupervisor
from star.stream_host_reply_fence import HostReplyPermit, HostWorkerReplyFence
from star.stream_host_worker_epochs import HostWorkerEpochRegistry
from star.stream_qos import InferenceJob, QoSDecision


class DummyProcess:
    def __init__(self, path):
        self.pid = 100
        self.birth = 1234.5
        self.path = str(path)
        self.running = True
        self.state = "running"
        self.probes = 0

    def is_running(self):
        self.probes += 1
        return self.running

    def status(self):
        return self.state

    def create_time(self):
        return self.birth

    def exe(self):
        return self.path


def scenario(tmp_path):
    (tmp_path / "model.gguf").write_bytes(b"weights")
    runtime = tmp_path / "worker.exe"
    runtime.write_bytes(b"runtime")
    route = HostModelRoute(
        "speech", "speech", "cpu", "fast-voice",
        sha256(b"weights").hexdigest(), sha256(b"runtime").hexdigest(),
        128, 0,
    )
    manifests = {"speech": HostArtifactPaths(("model.gguf",), "worker.exe")}
    checked = verify_host_artifacts(tmp_path, (route,), manifests)
    registry = HostWorkerEpochRegistry(checked, (route,))
    clock = [1000.0]

    def next_ms():
        clock[0] += 10
        return clock[0]

    proc = DummyProcess(runtime)
    supervisor = HostOSWorkerSupervisor(
        registry, tmp_path, manifests, clock_ms=next_ms,
        process_factory=lambda pid: proc,
    )
    supervisor.enable(owner_approved=True)
    epoch = supervisor.attach("speech", pid=100, owner_approved=True)
    fence = HostWorkerReplyFence(registry)
    fence.enable(owner_approved=True)
    job = registry.bind(
        InferenceJob("speech-turn", "speech", 1010, 1500, 1, 0, "auto"),
        epoch=epoch, now_ms=1011)
    permit = fence.arm(
        epoch=epoch, job=job,
        admission=QoSDecision(True, "admitted", "cpu", 1, None, 1300),
        now_ms=1011,
    )
    gate = HostLiveOutputGate(supervisor, fence)
    return gate, fence, supervisor, registry, epoch, permit, proc, clock


def test_last_moment_os_probe_before_speech_candidate(tmp_path):
    gate, fence, _, _, epoch, permit, proc, _ = scenario(tmp_path)
    with pytest.raises(PermissionError):
        gate.enable()
    assert not gate.claim(
        epoch, permit, host_output_ready=True
    ).eligible
    assert fence.pending == 0
    # Re-create with a fresh scenario; a failed opt-in consumes the ticket.
    gate, fence, _, _, epoch, permit, proc, _ = scenario(tmp_path)
    gate.enable(owner_approved=True)
    before = proc.probes
    assert gate.claim(epoch, permit, host_output_ready=False).reason == "worker_output_not_ready"
    assert fence.pending == 1 and proc.probes > before
    candidate = gate.claim(epoch, permit, host_output_ready=True)
    assert candidate.eligible and candidate.reason == "fresh_worker_output_candidate"
    assert not candidate.authorizes_audio and not candidate.authorizes_broadcast
    assert fence.pending == 0
    assert not gate.claim(epoch, permit, host_output_ready=True).eligible


@pytest.mark.parametrize("change", ["dead", "zombie", "pid_reused", "runtime_swapped"])
def test_stale_os_worker_cancels_queued_speech(tmp_path, change):
    gate, fence, supervisor, registry, epoch, permit, proc, _ = scenario(tmp_path)
    gate.enable(owner_approved=True)
    if change == "dead":
        proc.running = False
    elif change == "zombie":
        proc.state = "zombie"
    elif change == "pid_reused":
        proc.birth += 1.0
    else:
        (tmp_path / "worker.exe").write_bytes(b"changed runtime")
    bad = gate.claim(epoch, permit, host_output_ready=True)
    assert not bad.eligible
    assert bad.reason == "host_process_not_current"
    assert fence.pending == 0
    assert registry.active_workers == 0
    assert not supervisor.refresh(epoch).current
    assert not gate.claim(epoch, permit, host_output_ready=True).eligible


def test_disable_flushes_all_queued_output_without_stopping_process(tmp_path):
    gate, fence, _, _, epoch, permit, proc, _ = scenario(tmp_path)
    gate.enable(owner_approved=True)
    gate.disable()
    assert fence.pending == 0
    assert proc.running
    gate.enable(owner_approved=True)
    assert not gate.claim(epoch, permit, host_output_ready=True).eligible


def test_different_registry_is_never_mixed(tmp_path):
    gate, fence, supervisor, registry, epoch, permit, _, _ = scenario(tmp_path)
    other = HostWorkerReplyFence.__new__(HostWorkerReplyFence)
    other._registry = object()
    with pytest.raises(ValueError, match="registry differ"):
        HostLiveOutputGate(supervisor, other)
    with pytest.raises(TypeError):
        HostLiveOutputGate(object(), fence)
    with pytest.raises(TypeError):
        HostLiveOutputGate(supervisor, object())


def test_forged_copy_cannot_consume_valid_receipt(tmp_path):
    gate, fence, _, _, epoch, permit, _, _ = scenario(tmp_path)
    gate.enable(owner_approved=True)
    forged = replace(permit)
    assert not gate.claim(epoch, forged, host_output_ready=True).eligible
    assert fence.pending == 1
    assert gate.claim(epoch, permit, host_output_ready=True).eligible
    assert fence.pending == 0


def test_wrong_epoch_fails_closed_and_drops_ticket(tmp_path):
    gate, fence, _, _, epoch, permit, _, _ = scenario(tmp_path)
    gate.enable(owner_approved=True)
    forged = replace(epoch, route_profile="epoch-other")
    advice = gate.claim(forged, permit, host_output_ready=True)
    assert not advice.eligible
    assert advice.reason == "worker_output_route_mismatch"
    assert fence.pending == 0


def test_invalid_host_clock_and_readiness_never_release(tmp_path):
    gate, fence, _, _, epoch, permit, _, clock = scenario(tmp_path)
    gate.enable(owner_approved=True)
    with pytest.raises(ValueError, match="readiness"):
        gate.claim(epoch, permit, host_output_ready=1)
    assert fence.pending == 1
    clock[0] -= 100  # a clock rollback revokes all worker epochs
    assert not gate.claim(epoch, permit, host_output_ready=True).eligible
    assert fence.pending == 0


def test_cancel_is_identity_bound_and_idempotent(tmp_path):
    _, fence, _, _, _, permit, _, _ = scenario(tmp_path)
    forged = HostReplyPermit(permit.serial, permit.kind,
                             permit.route_profile, permit.deadline_ms)
    assert not fence.cancel(forged)
    assert fence.pending == 1
    assert fence.cancel(permit)
    assert not fence.cancel(permit)
    assert fence.pending == 0
    with pytest.raises(TypeError):
        fence.cancel(None)
