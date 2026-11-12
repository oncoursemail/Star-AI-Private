"""Offline integration tests for STAR's stream workload policy composition."""
import pytest

from star.stream_load_governor import GovernorPolicy, StreamLoadGovernor, StreamSample
from star.stream_workload_admission import (
    ResourceBudget,
    ResourceVector,
    WorkloadAdmissionController,
    WorkloadLane,
    WorkloadRequest,
)
from star.stream_workload_runtime import StreamWorkloadRuntime


def make_runtime(*, stale_after_ms=1_000, health_max_age_ms=5_000):
    budget = ResourceBudget(
        ResourceVector(cpu_millicores=2_000, ram_mb=8_192, vram_mb=7_000),
        ResourceVector(cpu_millicores=500, ram_mb=1_024, vram_mb=1_024),
    )
    controller = WorkloadAdmissionController(
        budget,
        health_max_age_ms=health_max_age_ms,
    )
    governor = StreamLoadGovernor(
        GovernorPolicy(
            stale_after_ms=stale_after_ms,
            recover_windows=2,
        )
    )
    return StreamWorkloadRuntime(controller, governor)


def sample(
    seq,
    captured_ms,
    *,
    streaming=False,
    gaming=False,
    fps=60,
    voice=100,
    dropped=0,
    vram=6_000,
    underruns=0,
):
    return StreamSample(
        seq,
        captured_ms,
        streaming,
        gaming,
        fps,
        voice,
        dropped,
        vram,
        underruns,
    )


def request(name, lane, *, cpu=100, ram=100, vram=100, at=1_000):
    return WorkloadRequest(
        name,
        lane,
        ResourceVector(cpu, ram, vram),
        at,
    )


def recover(runtime, *, streaming=False, gaming=False, start=1_000):
    first = runtime.observe(
        sample(1, start, streaming=streaming, gaming=gaming),
        now_monotonic_ms=start,
        trusted_host=True,
    )
    second = runtime.observe(
        sample(2, start + 100, streaming=streaming, gaming=gaming),
        now_monotonic_ms=start + 100,
        trusted_host=True,
    )
    assert first == "pressure"
    assert second == "normal"


def test_runtime_requires_trusted_host_and_fresh_nonfuture_samples():
    runtime = make_runtime()
    current = sample(1, 1_000)
    with pytest.raises(PermissionError):
        runtime.observe(current, now_monotonic_ms=1_000)
    with pytest.raises(ValueError, match="future"):
        runtime.observe(
            sample(1, 1_100),
            now_monotonic_ms=1_000,
            trusted_host=True,
        )
    with pytest.raises(ValueError, match="stale"):
        runtime.observe(
            current,
            now_monotonic_ms=3_000,
            trusted_host=True,
        )


def test_missing_telemetry_allows_only_protected_reservations():
    runtime = make_runtime()
    runtime.submit(request("audio", WorkloadLane.AUDIO))
    runtime.submit(request("chat", WorkloadLane.CHAT))
    runtime.submit(request("research", WorkloadLane.RESEARCH))
    leases = runtime.schedule(1_000)
    assert [lease.request_id for lease in leases] == ["audio", "chat"]
    snapshot = runtime.snapshot(1_000)
    assert snapshot.health_fresh is False
    assert snapshot.realtime_degraded is True
    assert snapshot.streaming is None
    assert snapshot.gaming is None
    assert snapshot.deferred_for_health == 1


def test_healthy_live_stream_keeps_chat_and_realtime_lanes_but_defers_tools():
    runtime = make_runtime()
    recover(runtime, streaming=True, gaming=True)
    lanes = (
        WorkloadLane.AUDIO,
        WorkloadLane.GAME_CONTROL,
        WorkloadLane.VOICE,
        WorkloadLane.AVATAR,
        WorkloadLane.CHAT,
        WorkloadLane.INTERACTIVE,
        WorkloadLane.RESEARCH,
        WorkloadLane.LEARNING,
        WorkloadLane.ASSET_GENERATION,
    )
    for index, lane in enumerate(lanes):
        runtime.submit(request(f"lane-{index}", lane, at=1_100))
    leases = runtime.schedule(1_100, max_admissions=16)
    assert [lease.lane for lease in leases] == [
        WorkloadLane.AUDIO,
        WorkloadLane.GAME_CONTROL,
        WorkloadLane.VOICE,
        WorkloadLane.AVATAR,
        WorkloadLane.CHAT,
    ]
    snapshot = runtime.snapshot(1_100)
    assert snapshot.streaming is True
    assert snapshot.gaming is True
    assert snapshot.realtime_degraded is False
    assert snapshot.deferred_for_health == 0
    assert snapshot.deferred_for_active_session == 4


def test_idle_recovery_allows_background_work_after_hysteresis():
    runtime = make_runtime()
    recover(runtime, streaming=False, gaming=False)
    runtime.submit(request("research", WorkloadLane.RESEARCH, at=1_100))
    runtime.submit(request("learning", WorkloadLane.LEARNING, at=1_100))
    leases = runtime.schedule(1_100, max_admissions=4)
    assert {lease.lane for lease in leases} == {
        WorkloadLane.RESEARCH,
        WorkloadLane.LEARNING,
    }
    snapshot = runtime.snapshot(1_100)
    assert snapshot.streaming is False
    assert snapshot.gaming is False
    assert snapshot.deferred_for_active_session == 0


def test_degraded_stream_preserves_chat_but_defers_tools_and_background():
    runtime = make_runtime()
    runtime.observe(
        sample(1, 1_000, streaming=True, gaming=True, fps=20),
        now_monotonic_ms=1_000,
        trusted_host=True,
    )
    runtime.submit(request("chat", WorkloadLane.CHAT))
    runtime.submit(request("tool", WorkloadLane.INTERACTIVE))
    runtime.submit(request("research", WorkloadLane.RESEARCH))
    leases = runtime.schedule(1_000, max_admissions=8)
    assert [lease.lane for lease in leases] == [WorkloadLane.CHAT]
    snapshot = runtime.snapshot(1_000)
    assert snapshot.realtime_degraded is True
    assert snapshot.deferred_for_health == 2
    assert snapshot.deferred_for_active_session == 2


def test_governor_freshness_is_stricter_than_controller_health_window():
    runtime = make_runtime(stale_after_ms=500, health_max_age_ms=5_000)
    recover(runtime, streaming=False, gaming=False)
    runtime.submit(request("research", WorkloadLane.RESEARCH, at=1_100))
    # The controller would consider the 600 ms sample fresh, but the governor
    # freshness contract is stricter and therefore blocks background work.
    assert runtime.schedule(1_700) == ()
    snapshot = runtime.snapshot(1_700)
    assert snapshot.health_fresh is True
    assert snapshot.realtime_degraded is True
    assert snapshot.deferred_for_health == 1


def test_future_or_replayed_samples_cannot_rearm_the_runtime():
    runtime = make_runtime()
    runtime.observe(
        sample(1, 1_000),
        now_monotonic_ms=1_000,
        trusted_host=True,
    )
    with pytest.raises(ValueError, match="Replay"):
        runtime.observe(
            sample(1, 1_100),
            now_monotonic_ms=1_100,
            trusted_host=True,
        )
    runtime.schedule(1_000)
    with pytest.raises(ValueError, match="clock"):
        runtime.schedule(999)


def test_active_lease_requires_host_stop_confirmation():
    runtime = make_runtime()
    runtime.submit(request("voice", WorkloadLane.VOICE))
    lease = runtime.schedule(1_000)[0]
    with pytest.raises(PermissionError, match="confirm"):
        runtime.release(
            lease.lease_id,
            1_001,
            host_confirmed_stopped=False,
        )
    assert runtime.snapshot(1_001).active == 1
    assert runtime.release(
        lease.lease_id,
        1_002,
        host_confirmed_stopped=True,
    ) is True


def test_chat_is_protected_but_cannot_spend_the_hard_realtime_reserve():
    budget = ResourceBudget(
        ResourceVector(cpu_millicores=100, ram_mb=0, vram_mb=0),
        ResourceVector(cpu_millicores=30, ram_mb=0, vram_mb=0),
    )
    controller = WorkloadAdmissionController(budget)
    runtime = StreamWorkloadRuntime(
        controller,
        StreamLoadGovernor(GovernorPolicy(recover_windows=2)),
    )
    recover(runtime, streaming=False, gaming=False)
    runtime.submit(
        WorkloadRequest(
            "chat-too-large",
            WorkloadLane.CHAT,
            ResourceVector(cpu_millicores=71),
            1_100,
        )
    )
    assert runtime.schedule(1_100) == ()
    assert runtime.cancel_queued("chat-too-large") is True
    runtime.submit(
        WorkloadRequest(
            "chat-fits",
            WorkloadLane.CHAT,
            ResourceVector(cpu_millicores=70),
            1_100,
        )
    )
    chat = runtime.schedule(1_100)
    assert [lease.lane for lease in chat] == [WorkloadLane.CHAT]
    runtime.submit(
        WorkloadRequest(
            "voice",
            WorkloadLane.VOICE,
            ResourceVector(cpu_millicores=30),
            1_101,
        )
    )
    voice = runtime.schedule(1_101)
    assert [lease.lane for lease in voice] == [WorkloadLane.VOICE]


def test_chat_is_protected_and_precedes_tool_and_research_lanes():
    runtime = make_runtime()
    recover(runtime, streaming=False, gaming=False)
    for name, lane in (
        ("research", WorkloadLane.RESEARCH),
        ("tool", WorkloadLane.INTERACTIVE),
        ("chat", WorkloadLane.CHAT),
        ("voice", WorkloadLane.VOICE),
    ):
        runtime.submit(request(name, lane, at=1_100))
    leases = runtime.schedule(1_100, max_admissions=8)
    assert [lease.lane for lease in leases] == [
        WorkloadLane.VOICE,
        WorkloadLane.CHAT,
        WorkloadLane.INTERACTIVE,
        WorkloadLane.RESEARCH,
    ]
