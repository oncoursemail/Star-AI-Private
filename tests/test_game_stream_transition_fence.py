"""Prevent cross-broadcast-state game inference from becoming a live action.

A fast-model lease admitted before a broadcast starts/stops is stale even if
its game frame is current and the final OBS state is independently verified.
No game, OBS, models, microphone, or physical input are used.
"""
import pytest

from star.game_action_gate import GameActionHint, GameFrame, GameScope
from star.game_deadline_router import GameDeadlineRouter
from star.game_realtime_loop import RealtimeGameLoop
from star.stream_budget import StreamTelemetry


def _scenario(initially_live: bool):
    scope = GameScope("sample_game", "v1", "episode")
    router = GameDeadlineRouter(minimum_samples=5, reactive_device="cpu")
    loop = RealtimeGameLoop(router=router)
    loop.start(scope, ("jump",), owner_approved=True)
    for index in range(1, 6):
        assert loop.record_reactive_latency(
            sample_id=index, duration_ms=50, sample_host_ms=index * 100,
            host_measured=True, stream_live=initially_live,
        )
    frame = GameFrame(scope, 1, 1000, "a" * 64, True, True, 0.95)
    lease = loop.offer(
        frame, now_ms=1100, host_verified=True, stream_live=initially_live,
        telemetry=StreamTelemetry(initially_live, True, 4096, 8192, 60, 0),
    )
    assert lease.route == "reactive"
    hint = GameActionHint("jump", 1, "a" * 64, 1015, 70)
    return loop, frame, hint, lease


@pytest.mark.parametrize("initially_live", [False, True])
def test_lease_cannot_cross_broadcast_start_or_stop(initially_live):
    loop, frame, hint, lease = _scenario(initially_live)
    current_state = not initially_live
    permit = loop.finish(
        lease, frame, hint, now_ms=1200, host_verified=True,
        stream_live=current_state,
        telemetry=StreamTelemetry(current_state, True, 4096, 8192, 60, 0),
    )
    assert not permit.offered
    assert permit.reason == "stream_state_changed_during_inference"
    assert loop.metrics()["awaiting_release"] is False
    assert loop.finish(
        lease, frame, hint, now_ms=1201, host_verified=True,
        stream_live=current_state,
        telemetry=StreamTelemetry(current_state, True, 4096, 8192, 60, 0),
    ).reason == "unknown_superseded_or_consumed_lease"


@pytest.mark.parametrize("initially_live", [False, True])
def test_unchanged_broadcast_state_remains_eligible(initially_live):
    loop, frame, hint, lease = _scenario(initially_live)
    permit = loop.finish(
        lease, frame, hint, now_ms=1200, host_verified=True,
        stream_live=initially_live,
        telemetry=StreamTelemetry(initially_live, True, 4096, 8192, 60, 0),
    )
    assert permit.offered, permit.reason
    assert not permit.authorized_to_press_keys
    assert loop.release(
        permit, now_ms=1210, host_confirmed_released=True,
    )
