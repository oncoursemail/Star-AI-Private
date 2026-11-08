"""Pure offline tests: no model, OBS, audio, or game is launched."""
from dataclasses import replace
from hashlib import sha256

import pytest

from star.stream_host_artifact_preflight import HostArtifactPaths, verify_host_artifacts
from star.stream_host_model_catalog import HostModelRoute
from star.stream_host_worker_epochs import HostWorkerEpochRegistry, HostWorkerObservation
from star.stream_host_reply_fence import HostReplyPermit, HostWorkerReplyFence
from star.stream_qos import AdaptiveQoS, InferenceJob, QoSDecision, QoSSnapshot
from star.stream_budget import StreamTelemetry


def setup(tmp_path):
    (tmp_path / "model.gguf").write_bytes(b"model")
    (tmp_path / "worker.exe").write_bytes(b"worker")
    route = HostModelRoute("talk", "speech", "cpu", "tiny-tts",
                           sha256(b"model").hexdigest(), sha256(b"worker").hexdigest(),
                           256, 0)
    verified = verify_host_artifacts(tmp_path, (route,),
        {"talk": HostArtifactPaths(("model.gguf",), "worker.exe")})
    registry = HostWorkerEpochRegistry(verified, (route,))
    epoch = registry.observe("talk", HostWorkerObservation(
        42, 1000, 1000, route.runtime_sha256),
        now_ms=1000, owner_approved=True)
    job = registry.bind(InferenceJob("j1", "speech", 1000, 1500, 1, 0, "auto"),
                        epoch=epoch, now_ms=1000)
    decision = QoSDecision(True, "admitted", "cpu", 1, None, 1300)
    fence = HostWorkerReplyFence(registry)
    return fence, registry, route, epoch, job, decision


def test_real_qos_admission_and_one_shot_reply(tmp_path):
    fence, registry, _, epoch, job, _ = setup(tmp_path)
    with pytest.raises(PermissionError):
        fence.enable()
    fence.enable(owner_approved=True)
    qos = AdaptiveQoS(require_route_profiles=True)
    qos.enable(owner_approved=True)
    snap = QoSSnapshot(1000, StreamTelemetry(True, True, 3000, 8192, 60, 0),
                       16000, 10)
    decision = qos.admit(job, snap, now_ms=1000)
    assert decision.admitted
    permit = fence.arm(epoch=epoch, job=job, admission=decision, now_ms=1000)
    assert not fence.claim(permit, now_ms=1010, host_output_ready=False).eligible
    good = fence.claim(permit, now_ms=1020, host_output_ready=True)
    assert good.eligible and not good.authorizes_audio and not good.authorizes_broadcast
    assert fence.claim(permit, now_ms=1021, host_output_ready=True).reason == (
        "unknown_or_replayed_output")
    assert registry.is_current(epoch, now_ms=1022)


def test_restart_drops_delayed_reply(tmp_path):
    fence, registry, route, epoch, job, decision = setup(tmp_path)
    fence.enable(owner_approved=True)
    permit = fence.arm(epoch=epoch, job=job, admission=decision, now_ms=1010)
    newer = registry.observe("talk", HostWorkerObservation(
        42, 1001, 1100, route.runtime_sha256),
        now_ms=1100, owner_approved=True)
    assert newer is not epoch
    assert fence.claim(permit, now_ms=1110, host_output_ready=True).reason == (
        "worker_restarted_or_observation_stale")


def test_out_of_order_observation_cannot_resurrect_old_pid(tmp_path):
    _, registry, route, epoch, _, _ = setup(tmp_path)
    newer = registry.observe("talk", HostWorkerObservation(
        43, 1001, 1110, route.runtime_sha256),
        now_ms=1110, owner_approved=True)
    with pytest.raises(ValueError, match="reordered"):
        registry.observe("talk", HostWorkerObservation(
            42, 1000, 1100, route.runtime_sha256),
            now_ms=1111, owner_approved=True)
    with pytest.raises(ValueError, match="reordered"):
        registry.observe("talk", HostWorkerObservation(
            44, 1002, 1110, route.runtime_sha256),
            now_ms=1112, owner_approved=True)
    assert registry.is_current(newer, now_ms=1113)
    assert not registry.is_current(epoch, now_ms=1114)


def test_retire_keeps_replay_watermark(tmp_path):
    _, registry, route, epoch, _, _ = setup(tmp_path)
    assert registry.retire(epoch=epoch)
    with pytest.raises(ValueError, match="reordered"):
        registry.observe("talk", HostWorkerObservation(
            42, 1000, 1000, route.runtime_sha256),
            now_ms=1005, owner_approved=True)
    next_epoch = registry.observe("talk", HostWorkerObservation(
        43, 1002, 1010, route.runtime_sha256),
        now_ms=1010, owner_approved=True)
    assert registry.is_current(next_epoch, now_ms=1011)


def test_fresh_qos_deadline_but_stale_worker_observation_blocks(tmp_path):
    fence, _, _, epoch, job, decision = setup(tmp_path)
    fence.enable(owner_approved=True)
    permit = fence.arm(epoch=epoch, job=job, admission=decision, now_ms=1005)
    assert fence.claim(permit, now_ms=1251, host_output_ready=True).reason == (
        "worker_restarted_or_observation_stale")


def test_expired_deadline_drops_reply(tmp_path):
    fence, _, _, epoch, job, decision = setup(tmp_path)
    fence.enable(owner_approved=True)
    permit = fence.arm(epoch=epoch, job=job, admission=decision, now_ms=1005)
    assert fence.claim(permit, now_ms=1301, host_output_ready=True).reason == (
        "output_deadline_expired")
    assert fence.pending == 0


def test_duplicate_admission_ticket_and_queue_cap(tmp_path):
    _, registry, _, epoch, job, decision = setup(tmp_path)
    fence = HostWorkerReplyFence(registry, max_pending=1)
    fence.enable(owner_approved=True)
    permit = fence.arm(epoch=epoch, job=job, admission=decision, now_ms=1001)
    with pytest.raises(ValueError, match="replayed"):
        fence.arm(epoch=epoch, job=job, admission=decision, now_ms=1002)
    with pytest.raises(ValueError, match="full"):
        fence.arm(epoch=epoch, job=job, admission=replace(decision, ticket=2),
                  now_ms=1003)
    assert fence.claim(permit, now_ms=1004, host_output_ready=True).eligible
    assert fence.arm(epoch=epoch, job=job,
                     admission=replace(decision, ticket=2), now_ms=1005)


@pytest.mark.parametrize("change,pattern", [
    ({"job": {"route_profile": "spoof"}}, "bound"),
    ({"job": {"kind": "research"}}, "user-visible"),
    ({"decision": {"admitted": False}}, "admission"),
    ({"decision": {"ticket": True}}, "admission"),
    ({"decision": {"device": "gpu"}}, "admission"),
    ({"decision": {"expires_ms": 1600}}, "deadline"),
    ({"decision": {"expires_ms": 1000}}, "deadline"),
])
def test_untrusted_output_lease_claims_rejected(tmp_path, change, pattern):
    fence, _, _, epoch, job, decision = setup(tmp_path)
    fence.enable(owner_approved=True)
    if "job" in change:
        job = replace(job, **change["job"])
    if "decision" in change:
        decision = replace(decision, **change["decision"])
    with pytest.raises(ValueError, match=pattern):
        fence.arm(epoch=epoch, job=job, admission=decision, now_ms=1007)


def test_disable_clears_queued_utterances(tmp_path):
    fence, _, _, epoch, job, decision = setup(tmp_path)
    with pytest.raises(PermissionError):
        fence.arm(epoch=epoch, job=job, admission=decision, now_ms=1002)
    fence.enable(owner_approved=True)
    permit = fence.arm(epoch=epoch, job=job, admission=decision, now_ms=1003)
    fence.disable()
    assert fence.pending == 0
    assert fence.claim(permit, now_ms=1004, host_output_ready=True).reason == (
        "owner_opt_in_missing")


@pytest.mark.parametrize("invalid", [True, "1001", float("nan"), float("inf"), -1])
def test_invalid_clocks_rejected(tmp_path, invalid):
    fence, _, _, epoch, job, decision = setup(tmp_path)
    fence.enable(owner_approved=True)
    with pytest.raises(ValueError):
        fence.arm(epoch=epoch, job=job, admission=decision, now_ms=invalid)


def test_repeated_callback_and_clock_reversal(tmp_path):
    fence, _, _, epoch, job, decision = setup(tmp_path)
    fence.enable(owner_approved=True)
    permit = fence.arm(epoch=epoch, job=job, admission=decision, now_ms=1010)
    assert not fence.claim(permit, now_ms=1020, host_output_ready=False).eligible
    with pytest.raises(ValueError, match="reversed"):
        fence.claim(permit, now_ms=1019, host_output_ready=True)
    copied = HostReplyPermit(permit.serial, permit.kind,
                             permit.route_profile, permit.deadline_ms)
    assert not fence.claim(copied, now_ms=1021, host_output_ready=True).eligible
    assert fence.claim(permit, now_ms=1022, host_output_ready=True).eligible


def test_readiness_must_be_host_bool(tmp_path):
    fence, _, _, epoch, job, decision = setup(tmp_path)
    fence.enable(owner_approved=True)
    permit = fence.arm(epoch=epoch, job=job, admission=decision, now_ms=1010)
    with pytest.raises(ValueError, match="readiness"):
        fence.claim(permit, now_ms=1011, host_output_ready=1)  # type: ignore[arg-type]
    assert fence.pending == 1
