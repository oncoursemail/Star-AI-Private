"""Offline worker-lifecycle tests; never start processes, models or OBS."""
from dataclasses import replace
from hashlib import sha256

import pytest

from star.stream_host_artifact_preflight import HostArtifactPaths, verify_host_artifacts
from star.stream_host_model_catalog import HostModelRoute
from star.stream_host_worker_epochs import (
    HostWorkerEpoch, HostWorkerEpochRegistry, HostWorkerObservation,
)
from star.stream_qos import AdaptiveQoS, InferenceJob, QoSSnapshot
from star.stream_budget import StreamTelemetry


def sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def registry(tmp_path, *, max_workers=16):
    (tmp_path / "weights.gguf").write_bytes(b"model 123")
    (tmp_path / "worker.bin").write_bytes(b"server 456")
    route = HostModelRoute(
        "talk", "speech", "cpu", "pocket-tts", sha(b"model 123"),
        sha(b"server 456"), 256, 0,
    )
    manifest = HostArtifactPaths(("weights.gguf",), "worker.bin")
    verified = verify_host_artifacts(tmp_path, (route,), {"talk": manifest})
    return HostWorkerEpochRegistry(verified, (route,), max_workers=max_workers), route, verified


def witness(route, *, pid=42, born=1000.0, observed=1000.0, digest=None):
    return HostWorkerObservation(
        pid, born, observed, route.runtime_sha256 if digest is None else digest,
    )


def job(name, now=1000, *, profile=""):
    return InferenceJob(name, "speech", now, now + 1500, 1, 1,
                        "auto", route_profile=profile)


def attach(reg, route, *, pid=42, born=1000.0, observed=1000.0, now=1000.0):
    return reg.observe("talk", witness(route, pid=pid, born=born, observed=observed),
                       now_ms=now, owner_approved=True)


def test_preflight_verified_worker_epoch_bind_preserves_host_memory(tmp_path):
    reg, route, _ = registry(tmp_path)
    epoch = attach(reg, route)
    bound = reg.bind(job("one"), epoch=epoch, now_ms=1010)
    assert bound.device == "cpu"
    assert bound.ram_mib == 256 and bound.vram_mib == 0
    assert bound.route_profile == epoch.route_profile
    assert bound.route_profile != route.route_profile
    assert len(bound.route_profile) <= 80
    assert reg.active_workers == 1
    assert "_pid" not in repr(epoch) and "_born_unix_s" not in repr(epoch)


def test_worker_same_identity_refresh_does_not_rotate_epoch(tmp_path):
    reg, route, _ = registry(tmp_path)
    initial = attach(reg, route)
    same = attach(reg, route, observed=1100, now=1100)
    assert same is initial
    assert reg.bind(job("two", now=1100), epoch=same, now_ms=1200)
    with pytest.raises(ValueError, match="replayed"):
        attach(reg, route, observed=1100, now=1201)


def test_pid_reuse_with_different_birth_rotates_calibration(tmp_path):
    reg, route, _ = registry(tmp_path)
    first = attach(reg, route)
    replacement = attach(reg, route, pid=42, born=1001, observed=1200, now=1200)
    assert replacement.route_profile != first.route_profile
    assert replacement.generation > first.generation
    with pytest.raises(ValueError, match="restarted"):
        reg.bind(job("old", now=1200), epoch=first, now_ms=1201)
    assert not reg.retire(epoch=first)
    assert reg.bind(job("new", now=1200), epoch=replacement, now_ms=1201)


def test_process_restart_even_same_executable_changes_latency_identity(tmp_path):
    reg, route, _ = registry(tmp_path)
    first = attach(reg, route)
    refreshed = attach(reg, route, pid=50, born=2000, observed=1200, now=1200)
    assert first.route_profile != refreshed.route_profile

    qos = AdaptiveQoS(require_route_profiles=True)
    qos.enable(owner_approved=True)
    stream = StreamTelemetry(True, True, 2500, 8192, 60, 0)
    # Train synthetic completion history for the old process. This test
    # verifies identity isolation, not actual model performance or speed.
    for idx in range(5):
        at = 1300 + 300 * idx
        # The job is bound as it would have been during the old epoch, whose
        # history can still exist in a long-running QoS instance.
        candidate = replace(job(f"old{idx}", at), route_profile=first.route_profile,
                            ram_mib=256, vram_mib=0, device="cpu")
        decision = qos.admit(
            candidate, QoSSnapshot(at, stream, 16000, 10),
            now_ms=at,
        )
        assert decision.admitted
        assert qos.finish(decision.ticket, now_ms=at + 50, succeeded=True)
    at = 3100
    old_probe = replace(job("oldprobe", at), route_profile=first.route_profile,
                        ram_mib=256, vram_mib=0, device="cpu")
    new_probe = replace(job("newprobe", at), route_profile=refreshed.route_profile,
                        ram_mib=256, vram_mib=0, device="cpu")
    prev = qos.admit(old_probe, QoSSnapshot(at, stream, 16000, 10), now_ms=at)
    changed = qos.admit(new_probe, QoSSnapshot(at, stream, 16000, 10), now_ms=at)
    assert prev.admitted and prev.predicted_p95_ms == 50
    assert changed.admitted and changed.predicted_p95_ms is None


def test_expired_worker_fails_before_inference_dispatch(tmp_path):
    reg, route, _ = registry(tmp_path)
    epoch = attach(reg, route)
    with pytest.raises(ValueError, match="expired"):
        reg.bind(job("late", now=1251), epoch=epoch, now_ms=1251)
    with pytest.raises(ValueError, match="stale"):
        attach(reg, route, observed=1000, now=1300)
    assert reg.retire(epoch=epoch)
    with pytest.raises(ValueError, match="restarted"):
        reg.bind(job("retired"), epoch=epoch, now_ms=1301)


def test_host_rejects_untrusted_artifact_and_forged_route(tmp_path):
    reg, route, verified = registry(tmp_path)
    with pytest.raises(PermissionError):
        reg.observe("talk", witness(route), now_ms=1000)
    with pytest.raises(ValueError, match="digest"):
        reg.observe("talk", witness(route, digest="0" * 64),
                    now_ms=1000, owner_approved=True)
    with pytest.raises(ValueError, match="unknown"):
        reg.observe("foreign", witness(route), now_ms=1000, owner_approved=True)
    with pytest.raises(ValueError, match="routes differ"):
        HostWorkerEpochRegistry(verified, (replace(route, ram_mib=500),))
    with pytest.raises(ValueError, match="routes"):
        HostWorkerEpochRegistry(verified, ())
    assert reg.active_workers == 0


def test_bound_job_cannot_spoof_profile_or_incompatible_device(tmp_path):
    reg, route, _ = registry(tmp_path)
    epoch = attach(reg, route)
    with pytest.raises(ValueError, match="pre-bind"):
        reg.bind(job("spoof", profile="epoch-" + "a" * 32),
                 epoch=epoch, now_ms=1000)
    with pytest.raises(ValueError, match="device"):
        reg.bind(replace(job("gpu"), device="gpu"),
                 epoch=epoch, now_ms=1000)
    with pytest.raises(ValueError, match="kind"):
        reg.bind(replace(job("render"), kind="render", device="auto"),
                 epoch=epoch, now_ms=1000)


@pytest.mark.parametrize("invalid", [
    dict(pid=True), dict(pid=-1), dict(pid=2**31),
    dict(process_birth_unix_s=0), dict(process_birth_unix_s=float("nan")),
    dict(observed_monotonic_ms=float("inf")), dict(runtime_sha256="X" * 64),
    dict(runtime_sha256="short"),
])
def test_invalid_worker_evidence_is_rejected(invalid):
    args = dict(pid=42, process_birth_unix_s=10.0,
                observed_monotonic_ms=1000.0, runtime_sha256="a" * 64)
    args.update(invalid)
    with pytest.raises(ValueError):
        HostWorkerObservation(**args)


def test_clock_and_worker_observation_replay_rejected(tmp_path):
    reg, route, _ = registry(tmp_path)
    with pytest.raises(ValueError, match="future"):
        attach(reg, route, observed=1200, now=1000)
    epoch = attach(reg, route, observed=1010, now=1010)
    with pytest.raises(ValueError, match="reversed"):
        reg.bind(job("rev"), epoch=epoch, now_ms=1009)
    with pytest.raises(ValueError, match="replayed"):
        attach(reg, route, observed=900, now=1020)


def test_bounded_workers_require_exact_retirement(tmp_path):
    _, route, _ = registry(tmp_path, max_workers=1)
    other = replace(route, alias="other")
    path = HostArtifactPaths(("weights.gguf",), "worker.bin")
    verified = verify_host_artifacts(tmp_path, (route, other),
                                     {"talk": path, "other": path})
    reg = HostWorkerEpochRegistry(verified, (route, other), max_workers=1)
    epoch = attach(reg, route)
    with pytest.raises(ValueError, match="capacity"):
        reg.observe("other", witness(other), now_ms=1000, owner_approved=True)
    # A stale or foreign epoch must never revoke an active worker.
    old = HostWorkerEpoch(epoch.alias, epoch.route_profile, epoch.generation,
                          epoch._pid, epoch._born_unix_s)
    assert not reg.retire(epoch=old)
    assert reg.active_workers == 1
    assert reg.retire(epoch=epoch)
    assert reg.active_workers == 0


def test_restarting_registry_does_not_reuse_route_profiles(tmp_path):
    reg, route, verified = registry(tmp_path)
    first = attach(reg, route)
    different = HostWorkerEpochRegistry(verified, (route,))
    second = attach(different, route)
    assert first.route_profile != second.route_profile
    assert not reg.retire(epoch=second)
