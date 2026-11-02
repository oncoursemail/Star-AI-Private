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


def _scenario(initially_live: bool, stream_epoch: int | None = None):
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
        stream_epoch=stream_epoch,
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


@pytest.mark.parametrize("initially_live", [False, True])
def test_observed_off_on_off_or_on_off_on_epoch_revokes_stale_action(initially_live):
    # OBS may change output twice while the model thinks, returning to the
    # original boolean before finish. State-only comparisons miss this ABA.
    loop, frame, hint, lease = _scenario(initially_live, stream_epoch=40)
    assert lease.stream_epoch_at_offer == 40
    permit = loop.finish(
        lease, frame, hint, now_ms=1200, host_verified=True,
        stream_live=initially_live, stream_epoch=42,
        telemetry=StreamTelemetry(initially_live, True, 4096, 8192, 60, 0),
    )
    assert not permit.offered
    assert permit.reason == "stream_epoch_changed_during_inference"
    assert not loop.metrics()["awaiting_release"]
    assert loop.finish(
        lease, frame, hint, now_ms=1201, host_verified=True,
        stream_live=initially_live, stream_epoch=42,
        telemetry=StreamTelemetry(initially_live, True, 4096, 8192, 60, 0),
    ).reason == "unknown_superseded_or_consumed_lease"


@pytest.mark.parametrize("initially_live", [False, True])
def test_stable_host_epoch_does_not_block_legitimate_actions(initially_live):
    loop, frame, hint, lease = _scenario(initially_live, stream_epoch=40)
    permit = loop.finish(
        lease, frame, hint, now_ms=1200, host_verified=True,
        stream_live=initially_live, stream_epoch=40,
        telemetry=StreamTelemetry(initially_live, True, 4096, 8192, 60, 0),
    )
    assert permit.offered, permit.reason
    assert loop.release(permit, now_ms=1210, host_confirmed_released=True)


def test_epoch_evidence_cannot_be_removed_or_added_during_inference():
    loop, frame, hint, lease = _scenario(False, stream_epoch=40)
    assert loop.finish(
        lease, frame, hint, now_ms=1200, host_verified=True,
        stream_live=False,
        telemetry=StreamTelemetry(False, True, 4096, 8192, 60, 0),
    ).reason == "stream_epoch_evidence_missing"

    loop2, frame2, hint2, lease2 = _scenario(False)
    assert loop2.finish(
        lease2, frame2, hint2, now_ms=1200, host_verified=True,
        stream_live=False, stream_epoch=40,
        telemetry=StreamTelemetry(False, True, 4096, 8192, 60, 0),
    ).reason == "stream_epoch_evidence_missing"


def test_epoch_downgrade_and_reverse_during_episode_refuse_new_offer():
    loop, frame, hint, lease = _scenario(False, stream_epoch=40)
    permit = loop.finish(
        lease, frame, hint, now_ms=1200, host_verified=True,
        stream_live=False, stream_epoch=40,
        telemetry=StreamTelemetry(False, True, 4096, 8192, 60, 0),
    )
    assert permit.offered
    assert loop.release(permit, now_ms=1210, host_confirmed_released=True)
    new_frame = GameFrame(frame.scope, 2, 1200, "b" * 64, True, True, 0.95)
    common = dict(
        frame=new_frame, now_ms=1250, host_verified=True, stream_live=False,
        telemetry=StreamTelemetry(False, True, 4096, 8192, 60, 0),
    )
    assert loop.offer(**common).reason == "stream_epoch_evidence_missing"
    assert loop.offer(**common, stream_epoch=39).reason == "stream_epoch_reversed"
    assert loop.offer(**common, stream_epoch=40).route == "reactive"


@pytest.mark.parametrize("invalid", [True, -1, 1.5, "1", 2**64])
def test_epoch_rejects_untrusted_number_types(invalid):
    loop, frame, hint, lease = _scenario(False)
    with pytest.raises(ValueError):
        loop.offer(
            frame, now_ms=1150, host_verified=True, stream_live=False,
            telemetry=StreamTelemetry(False, True, 4096, 8192, 60, 0),
            stream_epoch=invalid,
        )
    with pytest.raises(ValueError):
        loop.finish(
            lease, frame, hint, now_ms=1200, host_verified=True,
            stream_live=False,
            telemetry=StreamTelemetry(False, True, 4096, 8192, 60, 0),
            stream_epoch=invalid,
        )
    # A malformed current reading cannot consume the already issued lease.
    assert loop.finish(
        lease, frame, hint, now_ms=1200, host_verified=True,
        stream_live=False,
        telemetry=StreamTelemetry(False, True, 4096, 8192, 60, 0),
    ).offered


def test_epoch_fence_applies_again_at_final_key_claim():
    loop, frame, hint, lease = _scenario(False, stream_epoch=40)
    permit = loop.finish(
        lease, frame, hint, now_ms=1200, host_verified=True,
        stream_live=False, stream_epoch=40,
        telemetry=StreamTelemetry(False, True, 4096, 8192, 60, 0),
    )
    assert permit.offered
    # The host witnessed a full OBS transition AFTER finish but BEFORE input.
    assert not loop.claim(
        permit, now_ms=1210, host_focus_and_permission=True, stream_epoch=42,
    )
    # The old permit cannot be resurrected by reverting to the old epoch.
    assert not loop.claim(
        permit, now_ms=1211, host_focus_and_permission=True, stream_epoch=40,
    )
    assert loop.release(permit, now_ms=1212, host_confirmed_released=True)


def test_epoch_evidence_required_at_claim_if_it_was_used_at_offer():
    loop, frame, hint, lease = _scenario(False, stream_epoch=40)
    permit = loop.finish(
        lease, frame, hint, now_ms=1200, host_verified=True,
        stream_live=False, stream_epoch=40,
        telemetry=StreamTelemetry(False, True, 4096, 8192, 60, 0),
    )
    assert permit.offered
    assert not loop.claim(permit, now_ms=1205, host_focus_and_permission=True)
    assert loop.release(permit, now_ms=1210, host_confirmed_released=True)


def test_stable_epoch_allows_one_final_identity_claim():
    loop, frame, hint, lease = _scenario(False, stream_epoch=40)
    permit = loop.finish(
        lease, frame, hint, now_ms=1200, host_verified=True,
        stream_live=False, stream_epoch=40,
        telemetry=StreamTelemetry(False, True, 4096, 8192, 60, 0),
    )
    assert permit.offered
    assert loop.claim(
        permit, now_ms=1205, host_focus_and_permission=True, stream_epoch=40,
    )
    assert not loop.claim(
        permit, now_ms=1206, host_focus_and_permission=True, stream_epoch=40,
    )
    assert loop.release(permit, now_ms=1210, host_confirmed_released=True)
