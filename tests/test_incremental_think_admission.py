from __future__ import annotations

import pytest

from star.stream_load_governor import GovernorPolicy, StreamLoadGovernor, StreamSample
from star.stream_workload_admission import (
    ResourceBudget,
    ResourceVector,
    WorkloadAdmissionController,
    WorkloadLane,
    WorkloadLease,
)
from star.stream_workload_runtime import StreamWorkloadRuntime
from star.voice.incremental_thinking import ThinkAction, ThinkDirective
from star.voice.incremental_think_admission import (
    IncrementalThinkAdmissionBridge,
)


def make_runtime(*, healthy: bool = True, reserve_cpu: int = 600) -> StreamWorkloadRuntime:
    admission = WorkloadAdmissionController(
        ResourceBudget(
            capacity=ResourceVector(1000, 4096, 1024),
            realtime_reserve=ResourceVector(reserve_cpu, 2048, 512),
        )
    )
    governor = StreamLoadGovernor(GovernorPolicy(recover_windows=1))
    runtime = StreamWorkloadRuntime(admission, governor)
    runtime.observe(
        StreamSample(
            seq=1,
            captured_ms=1000,
            streaming=True,
            gaming=True,
            game_fps_p10=60.0,
            voice_p95_ms=100.0,
            obs_dropped_pct=0.0,
            vram_free_mb=4096,
            audio_underruns=0 if healthy else 1,
        ),
        now_monotonic_ms=1000,
        trusted_host=True,
    )
    return runtime


def make_bridge(
    runtime: StreamWorkloadRuntime,
    *,
    resources: ResourceVector = ResourceVector(100, 256, 128),
    max_pending: int = 8,
) -> IncrementalThinkAdmissionBridge:
    return IncrementalThinkAdmissionBridge(
        runtime,
        resources=resources,
        max_pending=max_pending,
    )


def start_directive(
    utterance_id: str = "turn-1",
    revision: int = 0,
    *,
    cancel_previous: bool = False,
    cancel_utterance_id: str = "",
    cancel_revision: int = -1,
) -> ThinkDirective:
    return ThinkDirective(
        action=ThinkAction.START,
        utterance_id=utterance_id,
        revision=revision,
        stable_prefix="I want to build a small Roblox game",
        reason="stable_semantic_prefix",
        cancel_previous=cancel_previous,
        cancel_utterance_id=cancel_utterance_id,
        cancel_revision=cancel_revision,
    )


def cancel_directive(utterance_id: str = "turn-1", revision: int = 0) -> ThinkDirective:
    return ThinkDirective(
        action=ThinkAction.CANCEL,
        utterance_id=utterance_id,
        revision=revision,
        reason="barge_in",
        cancel_previous=True,
        cancel_utterance_id=utterance_id,
        cancel_revision=revision,
    )


def test_start_queues_nonprotected_voice_prep_and_waits_for_scheduler_lease() -> None:
    runtime = make_runtime()
    bridge = make_bridge(runtime)
    result = bridge.apply(start_directive(), now_ms=1100)
    assert result.status == "queued"
    assert result.request_id is not None

    leases = runtime.schedule(1100)
    assert len(leases) == 1
    assert leases[0].lane is WorkloadLane.VOICE_PREP
    launch = bridge.accept_lease(leases[0], now_ms=1100)
    assert launch is not None
    assert launch.directive.stable_prefix == "I want to build a small Roblox game"
    assert bridge.confirm_started(leases[0].lease_id, now_ms=1110, started=True) is True


def test_voice_prep_runs_during_healthy_stream_and_game_only_from_unreserved_capacity() -> None:
    runtime = make_runtime(reserve_cpu=900)
    bridge = make_bridge(runtime, resources=ResourceVector(101, 256, 128))
    bridge.apply(start_directive(), now_ms=1100)
    # Capacity outside the hard realtime reserve is only 100 CPU millicores.
    assert runtime.schedule(1100) == ()
    snapshot = runtime.snapshot(1100)
    assert snapshot.queued == 1
    assert snapshot.realtime_reserve_remaining.cpu_millicores == 900


def test_voice_prep_is_blocked_when_host_health_is_degraded() -> None:
    runtime = make_runtime(healthy=False)
    bridge = make_bridge(runtime)
    bridge.apply(start_directive(), now_ms=1100)
    assert runtime.schedule(1100) == ()
    snapshot = runtime.snapshot(1100)
    assert snapshot.queued == 1
    assert snapshot.deferred_for_health == 1


def test_missing_host_health_fails_closed_for_voice_prep() -> None:
    admission = WorkloadAdmissionController(
        ResourceBudget(ResourceVector(1000, 4096, 1024), ResourceVector(500, 2048, 512))
    )
    runtime = StreamWorkloadRuntime(admission, StreamLoadGovernor(GovernorPolicy(recover_windows=1)))
    bridge = make_bridge(runtime)
    bridge.apply(start_directive(), now_ms=1000)
    assert runtime.schedule(1000) == ()


def test_update_replaces_only_the_ephemeral_prefix_for_the_same_worker() -> None:
    runtime = make_runtime()
    bridge = make_bridge(runtime)
    bridge.apply(start_directive(), now_ms=1100)
    lease = runtime.schedule(1100)[0]
    bridge.accept_lease(lease, now_ms=1100)
    bridge.confirm_started(lease.lease_id, now_ms=1110, started=True)

    updated = ThinkDirective(
        action=ThinkAction.UPDATE,
        utterance_id="turn-1",
        revision=0,
        stable_prefix="I want to build a small Roblox game with friends",
        reason="stable_prefix_extended",
    )
    assert bridge.apply(updated, now_ms=1200).status == "updated"
    assert bridge.current_directive(lease.lease_id) == updated
    assert runtime.snapshot(1200).active == 1


def test_cancel_removes_a_request_that_is_still_queued() -> None:
    runtime = make_runtime()
    bridge = make_bridge(runtime)
    bridge.apply(start_directive(), now_ms=1100)
    result = bridge.apply(cancel_directive(), now_ms=1150)
    assert result.status == "cancelled"
    assert runtime.schedule(1200) == ()
    assert runtime.snapshot(1200).queued == 0


def test_cancel_racing_scheduler_grant_releases_lease_without_starting_worker() -> None:
    runtime = make_runtime()
    bridge = make_bridge(runtime)
    bridge.apply(start_directive(), now_ms=1100)
    lease = runtime.schedule(1100)[0]

    result = bridge.apply(cancel_directive(), now_ms=1110)
    assert result.status == "cancel_pending"
    assert bridge.accept_lease(lease, now_ms=1120) is None
    assert runtime.snapshot(1120).active == 0


def test_active_worker_requires_exact_stop_request_and_host_confirmation() -> None:
    runtime = make_runtime()
    bridge = make_bridge(runtime)
    bridge.apply(start_directive(), now_ms=1100)
    lease = runtime.schedule(1100)[0]
    bridge.accept_lease(lease, now_ms=1100)
    bridge.confirm_started(lease.lease_id, now_ms=1110, started=True)

    stop = bridge.stop_request("turn-1", 0, now_ms=1200, reason="asr_revision_replaced")
    assert stop is not None
    assert stop.lease == lease
    assert bridge.confirm_stopped(
        lease.lease_id, now_ms=1210, host_confirmed_stopped=False
    ) is False
    assert runtime.snapshot(1210).active == 1
    assert bridge.confirm_stopped(
        lease.lease_id, now_ms=1220, host_confirmed_stopped=True
    ) is True
    assert runtime.snapshot(1220).active == 0


def test_new_revision_waits_until_previous_worker_is_confirmed_stopped() -> None:
    runtime = make_runtime()
    bridge = make_bridge(runtime)
    bridge.apply(start_directive(), now_ms=1100)
    lease = runtime.schedule(1100)[0]
    bridge.accept_lease(lease, now_ms=1100)
    bridge.confirm_started(lease.lease_id, now_ms=1110, started=True)

    replacement = start_directive(
        revision=1,
        cancel_previous=True,
        cancel_utterance_id="turn-1",
        cancel_revision=0,
    )
    assert bridge.apply(replacement, now_ms=1200).status == "blocked_previous"
    stop = bridge.stop_request("turn-1", 0, now_ms=1201, reason="asr_revision_replaced")
    assert stop is not None
    bridge.confirm_stopped(lease.lease_id, now_ms=1210, host_confirmed_stopped=True)
    assert bridge.apply(replacement, now_ms=1220).status == "queued"


def test_uncertain_startup_keeps_resource_lease_fenced_until_reconciled() -> None:
    runtime = make_runtime()
    bridge = make_bridge(runtime)
    bridge.apply(start_directive(), now_ms=1100)
    lease = runtime.schedule(1100)[0]
    bridge.accept_lease(lease, now_ms=1100)
    assert bridge.confirm_started(
        lease.lease_id, now_ms=1110, started=False, host_confirmed_stopped=False
    ) is False
    assert runtime.snapshot(1110).active == 1
    stop = bridge.stop_request("turn-1", 0, now_ms=1120, reason="startup_uncertain")
    assert stop is not None
    assert bridge.confirm_stopped(
        lease.lease_id, now_ms=1130, host_confirmed_stopped=True
    ) is True
    assert runtime.snapshot(1130).active == 0


def test_failed_start_releases_only_with_explicit_no_worker_receipt() -> None:
    runtime = make_runtime()
    bridge = make_bridge(runtime)
    bridge.apply(start_directive(), now_ms=1100)
    lease = runtime.schedule(1100)[0]
    bridge.accept_lease(lease, now_ms=1100)
    assert bridge.confirm_started(
        lease.lease_id, now_ms=1110, started=False, host_confirmed_stopped=True
    ) is False
    assert runtime.snapshot(1110).active == 0


def test_finalize_cancels_the_exact_speculative_generation() -> None:
    runtime = make_runtime()
    bridge = make_bridge(runtime)
    bridge.apply(start_directive(), now_ms=1100)
    finalize = ThinkDirective(
        action=ThinkAction.FINALIZE,
        utterance_id="turn-1",
        revision=0,
        final_text="I want to build a small Roblox game.",
        commit_final=True,
    )
    assert bridge.apply(finalize, now_ms=1150).status == "cancelled"
    assert runtime.schedule(1200) == ()


def test_start_replay_is_idempotent_while_pending_and_rejected_after_cancel() -> None:
    runtime = make_runtime()
    bridge = make_bridge(runtime)
    first = bridge.apply(start_directive(), now_ms=1100)
    second = bridge.apply(start_directive(), now_ms=1110)
    assert first.status == "queued"
    assert second.status == "already_pending"
    bridge.apply(cancel_directive(), now_ms=1120)
    replay = bridge.apply(start_directive(), now_ms=1130)
    assert replay.status == "rejected"


def test_pending_capacity_is_bounded() -> None:
    runtime = make_runtime()
    bridge = make_bridge(runtime, max_pending=1)
    assert bridge.apply(start_directive("turn-1"), now_ms=1100).status == "queued"
    assert bridge.apply(start_directive("turn-2"), now_ms=1110).status == "rejected"


def test_startup_receipt_cannot_claim_started_and_stopped() -> None:
    runtime = make_runtime()
    bridge = make_bridge(runtime)
    bridge.apply(start_directive(), now_ms=1100)
    lease = runtime.schedule(1100)[0]
    bridge.accept_lease(lease, now_ms=1100)
    with pytest.raises(ValueError, match="simultaneously"):
        bridge.confirm_started(
            lease.lease_id, now_ms=1110, started=True, host_confirmed_stopped=True
        )


def test_wrong_lane_is_not_consumed_by_the_thinker_bridge() -> None:
    runtime = make_runtime()
    bridge = make_bridge(runtime)
    unrelated = WorkloadLease(
        lease_id="a" * 32,
        request_id="another-subsystem",
        lane=WorkloadLane.CHAT,
        resources=ResourceVector(),
        granted_monotonic_ms=1000,
        expires_monotonic_ms=61000,
    )
    assert bridge.accept_lease(unrelated, now_ms=1100) is None


def test_metrics_are_aggregate_and_do_not_expose_utterance_or_prefix() -> None:
    runtime = make_runtime()
    bridge = make_bridge(runtime)
    bridge.apply(start_directive(), now_ms=1100)
    metrics = bridge.metrics()
    assert metrics["queued"] == 1
    assert "turn-1" not in repr(metrics)
    assert "Roblox" not in repr(metrics)
