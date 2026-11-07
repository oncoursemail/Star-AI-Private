"""Offline protocol and game-admission tests; never launches OBS or sends input."""
from __future__ import annotations

import pytest

from star.game_action_gate import GameActionHint, GameFrame, GameScope
from star.game_deadline_router import GameDeadlineRouter
from star.game_realtime_loop import RealtimeGameLoop
from star.obs_stream_event_witness import (
    ObsEventWitnessError, ObsGameStreamEpochSource, ObsGameStreamSnapshot,
)
from star.stream_budget import StreamTelemetry

# Reuse the already-tested fake websocket wire implementation, not OBS itself.
from test_obs_stream_event_witness import FakeEventSocket


def rig(*, initially_live: bool = False):
    socket = FakeEventSocket()
    socket.active = initially_live
    process = {"id": (321, 12345.0)}
    source = ObsGameStreamEpochSource(
        socket_factory=lambda **_: socket,
        process_identity=lambda: process["id"],
    )
    source.connect(password="test-local-password", owner_approved=True)
    return source, socket, process


def transition(socket: FakeEventSocket, live: bool) -> None:
    socket.event(
        "StreamStateChanged", outputActive=live,
        outputState="OBS_WEBSOCKET_OUTPUT_STARTED" if live
        else "OBS_WEBSOCKET_OUTPUT_STOPPED",
    )
    socket.active = live


@pytest.mark.parametrize("live", [False, True])
def test_initial_observation_and_stability(live):
    source, socket, _ = rig(initially_live=live)
    assert source.snapshot() == ObsGameStreamSnapshot(0, live)
    assert source.snapshot() == ObsGameStreamSnapshot(0, live)
    assert all(msg["d"].get("requestType") == "GetStreamStatus"
               for msg in socket.sent if msg["op"] == 6)


@pytest.mark.parametrize("initially_live", [False, True])
def test_output_aba_increments_epoch_despite_unchanged_final_boolean(initially_live):
    source, socket, _ = rig(initially_live=initially_live)
    assert source.snapshot().epoch == 0
    transition(socket, not initially_live)
    transition(socket, initially_live)
    snapshot = source.snapshot()
    assert snapshot.stream_live is initially_live
    assert snapshot.epoch == 2
    assert source.snapshot().epoch == 2


def test_each_transition_event_counts_even_when_same_boolean():
    source, socket, _ = rig()
    source.snapshot()
    transition(socket, True)
    transition(socket, True)  # e.g. STARTING -> STARTED notifications
    assert source.snapshot() == ObsGameStreamSnapshot(2, True)
    transition(socket, False)
    assert source.snapshot() == ObsGameStreamSnapshot(3, False)


def test_status_changed_without_delivered_event_revokes_witness():
    source, socket, _ = rig()
    source.snapshot()
    socket.active = True
    with pytest.raises(ObsEventWitnessError):
        source.snapshot()
    assert not source.connected and socket.closed


@pytest.mark.parametrize("fault", [
    "reconnect", "missing_status", "bad_reply", "disconnect",
    "exit", "malformed", "event_flood",
])
def test_transport_and_protocol_faults_permanently_revoke(fault):
    source, socket, _ = rig()
    source.snapshot()
    if fault == "reconnect":
        socket.reconnecting = True
    elif fault == "missing_status":
        socket.invalid_reply = {"op": 7, "d": {"requestId": "wrong"}}
    elif fault == "bad_reply":
        socket.invalid_reply = {"op": 9, "d": {}}
    elif fault == "disconnect":
        socket.fail_next_receive = True
    elif fault == "exit":
        socket.event("ExitStarted")
    elif fault == "malformed":
        socket.inject.append({"op": 5, "d": {
            "eventType": "StreamStateChanged", "eventIntent": 64,
            "eventData": {"outputActive": "true", "outputState": "STARTED"},
        }})
    else:
        for _ in range(257):
            socket.event("RecordStateChanged", outputPath="PRIVATE-RECORD-PATH")
    with pytest.raises(ObsEventWitnessError) as error:
        source.snapshot()
    assert "PRIVATE" not in str(error.value)
    assert socket.closed
    with pytest.raises(ObsEventWitnessError):
        source.connect(password="test-local-password", owner_approved=True)


def test_event_and_status_disagreement_revokes():
    source, socket, _ = rig()
    source.snapshot()
    socket.event(
        "StreamStateChanged", outputActive=True,
        outputState="OBS_WEBSOCKET_OUTPUT_STARTED",
    )
    # The last output event disagrees with the verified status.
    socket.active = False
    with pytest.raises(ObsEventWitnessError):
        source.snapshot()
    assert socket.closed


def test_event_without_outputs_subscription_intent_revokes():
    source, socket, _ = rig()
    source.snapshot()
    socket.inject.append({"op": 5, "d": {
        "eventType": "StreamStateChanged", "eventIntent": 1,
        "eventData": {
            "outputActive": True, "outputState": "OBS_WEBSOCKET_OUTPUT_STARTED",
        },
    }})
    with pytest.raises(ObsEventWitnessError):
        source.snapshot()
    assert socket.closed


def test_restart_is_a_terminal_failure():
    source, socket, process = rig(initially_live=True)
    source.snapshot()
    process["id"] = (321, 12346.0)  # same PID, different process start time
    with pytest.raises(ObsEventWitnessError):
        source.snapshot()
    assert socket.closed


def test_connect_requires_owner_and_never_sends_stream_toggle():
    socket = FakeEventSocket()
    connections = []
    source = ObsGameStreamEpochSource(
        socket_factory=lambda **kw: (connections.append(kw) or socket),
        process_identity=lambda: (42, 1000.0),
    )
    with pytest.raises(PermissionError):
        source.connect(password="p", owner_approved=False)
    assert connections == []
    source.connect(password="p", owner_approved=True)
    source.snapshot()
    assert len(connections) == 1
    assert connections[0]["url"] == "ws://127.0.0.1:4455"
    assert {m["d"].get("requestType") for m in socket.sent if m["op"] == 6} == {
        "GetStreamStatus",
    }
    source.disconnect()
    with pytest.raises(ObsEventWitnessError):
        source.connect(password="p", owner_approved=True)


def test_concurrent_snapshot_revokes_ambiguous_event_consumption():
    source, socket, _ = rig()
    assert source._snapshot_lock.acquire(blocking=False)
    try:
        with pytest.raises(ObsEventWitnessError):
            source.snapshot()
    finally:
        source._snapshot_lock.release()
    assert socket.closed


def game(rigged_source: ObsGameStreamEpochSource):
    scope = GameScope("local_test_game", "1", "epoch_test")
    loop = RealtimeGameLoop(router=GameDeadlineRouter(
        minimum_samples=5, reactive_device="cpu",
    ))
    loop.start(scope, ("jump",), owner_approved=True)
    for n in range(1, 6):
        assert loop.record_reactive_latency(
            sample_id=n, duration_ms=50, sample_host_ms=n * 100,
            host_measured=True, stream_live=False,
        )
    before = rigged_source.snapshot()
    frame = GameFrame(scope, 1, 1000, "a" * 64, True, True, 0.95)
    lease = loop.offer(
        frame, now_ms=1100, host_verified=True, stream_live=before.stream_live,
        stream_epoch=before.epoch,
        telemetry=StreamTelemetry(False, True, 4096, 8192, 60, 0),
    )
    assert lease.route == "reactive"
    return loop, frame, lease


def test_authenticated_obs_aba_invalidates_completed_game_inference():
    source, socket, _ = rig()
    loop, frame, lease = game(source)
    transition(socket, True)
    transition(socket, False)
    after = source.snapshot()
    assert after.stream_live is False and after.epoch == 2
    permit = loop.finish(
        lease, frame, GameActionHint("jump", 1, "a" * 64, 1015, 70),
        now_ms=1200, host_verified=True,
        stream_live=after.stream_live, stream_epoch=after.epoch,
        telemetry=StreamTelemetry(False, True, 4096, 8192, 60, 0),
    )
    assert not permit.offered
    assert permit.reason == "stream_epoch_changed_during_inference"


def test_authenticated_obs_aba_at_claim_rejects_even_after_valid_inference():
    source, socket, _ = rig()
    loop, frame, lease = game(source)
    after = source.snapshot()
    permit = loop.finish(
        lease, frame, GameActionHint("jump", 1, "a" * 64, 1015, 70),
        now_ms=1200, host_verified=True,
        stream_live=after.stream_live, stream_epoch=after.epoch,
        telemetry=StreamTelemetry(False, True, 4096, 8192, 60, 0),
    )
    assert permit.offered
    transition(socket, True)
    transition(socket, False)
    current = source.snapshot()
    assert current.stream_live is False and current.epoch == 2
    assert not loop.claim(
        permit, now_ms=1205, host_focus_and_permission=True,
        stream_epoch=current.epoch,
    )
    assert not loop.claim(
        permit, now_ms=1206, host_focus_and_permission=True,
        stream_epoch=after.epoch,
    )


def test_stable_source_can_pass_final_claim_without_actuating_any_input():
    source, _, _ = rig()
    loop, frame, lease = game(source)
    before = source.snapshot()
    permit = loop.finish(
        lease, frame, GameActionHint("jump", 1, "a" * 64, 1015, 70),
        now_ms=1200, host_verified=True,
        stream_live=before.stream_live, stream_epoch=before.epoch,
        telemetry=StreamTelemetry(False, True, 4096, 8192, 60, 0),
    )
    assert permit.offered
    # This is only an advisory claim: no keyboard or game side effects occur.
    claim = source.snapshot()
    assert loop.claim(
        permit, now_ms=1205, host_focus_and_permission=True,
        stream_epoch=claim.epoch,
    )
    assert loop.release(
        permit, now_ms=1210, host_confirmed_released=True,
    )
