"""Offline integration tests for real-GPU/worker host control; no OS processes started."""

from subprocess import CompletedProcess, Popen

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
from star.stream_windows_gpu_control_loop import WindowsGPUWorkerControlLoop
from star.stream_windows_gpu_probe import (
    WindowsGPUHealthObserver,
    WindowsNVIDIAMemoryProbe,
)

UUID = "GPU-3fa85f64-5717-4562-b3fc-2c963f66afa6"


class FakePopen(Popen):
    def __init__(self):
        self.pid = 6543
        self.code = None
        self.terminated = 0

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated += 1


class Witness:
    def __init__(self, proc):
        self.proc = proc
        self.birth = 1740000000.0
        self.uncertain = False

    @property
    def pid(self):
        return self.proc.pid

    def is_running(self):
        if self.uncertain:
            raise OSError("untrusted witness")
        return self.proc.code is None

    def create_time(self):
        if self.uncertain:
            raise OSError("untrusted birth time")
        return self.birth


def health(ms, *, verified=True):
    return StreamHealthSample(
        ms,
        StreamTelemetry(
            live=False,
            game_active=False,
            total_vram_mib=8192,
            free_vram_mib=7900,
            game_fps=60,
            speech_backlog_ms=0,
        ),
        0,
        0,
        verified,
    )


def rig(tmp_path, *, now=1000.0, vram=6500, timeout=False):
    state = {"now": now, "vram": vram, "fail": False, "slow": 0.0}
    binary = tmp_path / "nvidia-smi.exe"
    binary.write_bytes(b"fake probe: never run")
    worker_binary = tmp_path / "research.exe"
    worker_binary.write_bytes(b"fake worker: never run")
    spawned = []
    proc = FakePopen()
    witness = Witness(proc)

    def run(argv, **kw):
        if state["fail"]:
            raise OSError("NVIDIA command unavailable")
        state["now"] += state["slow"]
        return CompletedProcess(
            argv,
            0,
            f"{UUID}, 8192, {state['vram']}\n",
            "",
        )

    leases = RealtimeGPUWorkLeases()
    leases.enable(owner_approved=True)
    probe = WindowsNVIDIAMemoryProbe(
        binary,
        UUID,
        system_name=lambda: "Windows",
        run=run,
        monotonic_ms=lambda: state["now"],
    )
    observer = WindowsGPUHealthObserver(probe, leases)
    bridge = HostGPUWorkerLeaseBridge(
        leases,
        process_factory=lambda _pid: witness,
    )
    workers = HostOwnedOptionalGPUWorkers(
        leases,
        bridge,
        system_name=lambda: "Windows",
    )
    plan = HostOptionalWorkerPlan(
        "research-trial",
        "research",
        500,
        worker_binary,
        (),
        tmp_path,
    )

    def spawn(argv, cwd):
        spawned.append((argv, cwd))
        return proc

    supervisor = HostOptionalGPUWorkerLaunchSupervisor(
        leases,
        workers,
        (plan,),
        system_name=lambda: "Windows",
        spawn=spawn,
    )
    supervisor.enable(owner_approved=True)
    loop = WindowsGPUWorkerControlLoop(
        observer,
        supervisor,
        leases,
        clock_ms=lambda: state["now"],
        maximum_probe_ms=500 if timeout else 2500,
    )
    return loop, plan, leases, proc, state, spawned


def test_fresh_live_gpu_and_verified_host_support_optional_launch(tmp_path):
    loop, plan, leases, proc, _, spawned = rig(tmp_path)
    sample = loop.tick(health(1000))
    assert sample.healthy
    assert sample.reason == "live_gpu_host_control_healthy"
    assert not sample.authorizes_execution
    assert not sample.authorizes_gameplay
    assert not sample.authorizes_broadcast
    result = loop.launch(plan, owner_approved=True)
    assert result.outcome == "started"
    assert len(spawned) == 1
    assert leases.metrics()["outstanding_claims"] == 1
    assert proc.terminated == 0


def test_disabled_by_default_requires_actual_gpu_poll_and_owner(tmp_path):
    loop, plan, leases, _, _, spawned = rig(tmp_path)
    assert loop.launch(plan, owner_approved=True).outcome == "deferred"
    with pytest.raises(PermissionError):
        loop.launch(plan)
    assert not spawned
    assert leases.metrics()["outstanding_claims"] == 0


def test_actual_low_vram_overrules_high_host_guess(tmp_path):
    loop, plan, leases, _, _, spawned = rig(tmp_path, vram=350)
    assert loop.tick(health(1000)).healthy
    res = loop.launch(plan, owner_approved=True)
    assert res.outcome == "deferred"
    assert not spawned
    assert leases.metrics()["outstanding_claims"] == 0


def test_failed_probe_revokes_process_but_keeps_claim_until_exit(tmp_path):
    loop, plan, leases, proc, state, spawned = rig(tmp_path)
    assert loop.tick(health(1000)).healthy
    assert loop.launch(plan, owner_approved=True).outcome == "started"
    state["now"] = 1100
    state["fail"] = True
    tick = loop.tick(health(1100))
    assert not tick.healthy
    assert tick.stop_requests_sent == 1
    assert proc.terminated == 1
    assert tick.outstanding_reservations == 1
    assert not leases.metrics()["enabled"]
    assert loop.launch(plan, owner_approved=True).outcome == "deferred"
    assert len(spawned) == 1
    proc.code = -1
    state["now"] = 1150
    tick2 = loop.tick(health(1150))
    assert not tick2.healthy
    assert tick2.exits_confirmed == 1
    assert tick2.outstanding_reservations == 0


def test_stale_health_fails_closed_before_touching_gpu(tmp_path):
    loop, plan, leases, _, state, spawned = rig(tmp_path)
    state["now"] = 2000
    res = loop.tick(health(1000))
    assert res.reason == "host_health_not_fresh_or_verified"
    assert not res.healthy
    assert not leases.metrics()["enabled"]
    assert loop.launch(plan, owner_approved=True).outcome == "deferred"
    assert not spawned


def test_unverified_health_fails_closed(tmp_path):
    loop, plan, leases, _, _, _ = rig(tmp_path)
    tick = loop.tick(health(1000, verified=False))
    assert not tick.healthy
    assert not leases.metrics()["enabled"]
    assert loop.launch(plan, owner_approved=True).outcome == "deferred"


def test_stale_after_good_read_revokes_without_unsafe_launch(tmp_path):
    loop, plan, leases, _, state, spawned = rig(tmp_path)
    assert loop.tick(health(1000)).healthy
    state["now"] = 1600
    res = loop.launch(plan, owner_approved=True)
    assert res.reason == "trusted_gpu_control_observation_stale"
    assert not leases.metrics()["enabled"]
    assert not spawned


def test_slow_gpu_probe_fails_closed(tmp_path):
    loop, plan, leases, _, state, spawned = rig(tmp_path, timeout=True)
    state["slow"] = 900
    tick = loop.tick(health(1000))
    assert tick.reason == "gpu_probe_too_slow_or_clock_invalid"
    assert not tick.healthy
    assert not leases.metrics()["enabled"]
    assert not spawned


def test_explicit_disable_stops_existing_owned_worker(tmp_path):
    loop, plan, leases, proc, state, _ = rig(tmp_path)
    assert loop.tick(health(1000)).healthy
    assert loop.launch(plan, owner_approved=True).outcome == "started"
    loop.disable()
    state["now"] = 1050
    tick = loop.tick(health(1050))
    assert not tick.healthy
    assert tick.stop_requests_sent == 1
    assert proc.terminated == 1
    assert leases.metrics()["outstanding_claims"] == 1


def test_wrong_session_and_invalid_policies_rejected(tmp_path):
    loop, plan, leases, proc, state, spawned = rig(tmp_path)
    with pytest.raises(ValueError):
        WindowsGPUWorkerControlLoop(
            loop._observer,
            loop._supervisor,
            RealtimeGPUWorkLeases(),
        )
    with pytest.raises(ValueError):
        WindowsGPUWorkerControlLoop(
            loop._observer,
            loop._supervisor,
            leases,
            maximum_fresh_ms=0,
        )
    with pytest.raises(ValueError):
        WindowsGPUWorkerControlLoop(
            loop._observer,
            loop._supervisor,
            leases,
            maximum_probe_ms=5000,
        )


def test_overlapping_host_poll_latches_worker_supervisor_off(tmp_path, monkeypatch):
    loop, plan, leases, _, _, spawned = rig(tmp_path)
    original = loop._observer.observe
    collisions = []

    def observe_with_collision(local):
        collisions.append(loop.tick(local))
        return original(local)

    monkeypatch.setattr(loop._observer, "observe", observe_with_collision)
    result = loop.tick(health(1000))
    assert collisions and collisions[0].reason == "host_supervisor_poll_overlap"
    assert not result.healthy
    assert not leases.metrics()["enabled"]
    assert not loop._supervisor.metrics()["enabled"]
    assert loop._faulted
    assert loop.launch(plan, owner_approved=True).outcome == "deferred"
    assert not spawned


def test_optional_launch_adapter_exception_faults_host(tmp_path, monkeypatch):
    loop, plan, leases, _, _, spawned = rig(tmp_path)
    assert loop.tick(health(1000)).healthy

    def ambiguous_launch(*args, **kwargs):
        raise OSError("sensitive native failure")

    monkeypatch.setattr(loop._supervisor, "launch", ambiguous_launch)
    result = loop.launch(plan, owner_approved=True)
    assert (result.outcome, result.reason) == (
        "deferred",
        "trusted_optional_launch_failed",
    )
    assert "sensitive" not in result.reason
    assert loop._faulted
    assert not leases.metrics()["enabled"]
    assert not loop._supervisor.metrics()["enabled"]
    assert not spawned


@pytest.mark.parametrize("outcome", ("fault", "quarantined"))
def test_uncertain_native_launch_poisoned_host(tmp_path, monkeypatch, outcome):
    from star.stream_optional_gpu_launch_supervisor import OptionalWorkerLaunchResult

    loop, plan, leases, _, _, _ = rig(tmp_path)
    assert loop.tick(health(1000)).healthy
    monkeypatch.setattr(
        loop._supervisor,
        "launch",
        lambda *args, **kwargs: OptionalWorkerLaunchResult(
            outcome,
            "worker_enrollment_uncertain",
            1,
        ),
    )
    result = loop.launch(plan, owner_approved=True)
    assert result.outcome == outcome
    assert loop._faulted
    assert not leases.metrics()["enabled"]
    assert not loop._supervisor.metrics()["enabled"]
    assert loop.launch(plan, owner_approved=True).reason == "trusted_gpu_control_not_healthy"
