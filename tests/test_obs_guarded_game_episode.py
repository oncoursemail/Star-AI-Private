"""Offline tests of opt-in, one-episode OBS-to-game trusted host bridge."""
from __future__ import annotations

import pytest

from star.game_action_gate import GameActionHint, GameFrame, GameScope
from star.game_deadline_router import GameDeadlineRouter
from star.game_realtime_loop import RealtimeGameLoop
from star.obs_guarded_game_episode import (
    ObsGuardedGameEpisode, ObsGuardedGameError,
)
from star.stream_budget import StreamTelemetry

from test_obs_game_stream_epoch_source import transition


class Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


def setup(*, initially_live: bool = False):
    # Create a fresh, unconnected fake: the bridge must own the OBS handshake.
    from star.obs_stream_event_witness import ObsGameStreamEpochSource
    from test_obs_stream_event_witness import FakeEventSocket

    socket = FakeEventSocket()
    socket.active = initially_live
    process = {"identity": (143, 3000.0)}
    source = ObsGameStreamEpochSource(
        socket_factory=lambda **_: socket,
        process_identity=lambda: process["identity"],
    )
    state = {"focus": True, "permission": True, "keyups": 0, "cancel": 0}
    clock = Clock()
    loop = RealtimeGameLoop(router=GameDeadlineRouter(
        minimum_samples=5, reactive_device="cpu",
    ))
    episode = ObsGuardedGameEpisode(
        witness=source, loop=loop,
        focus_probe=lambda: state["focus"],
        permission_probe=lambda: state["permission"],
        release_keys=lambda: state.__setitem__("keyups", state["keyups"] + 1),
        cancel_inference=lambda: state.__setitem__("cancel", state["cancel"] + 1),
        clock_ms=clock,
    )
    return episode, loop, source, socket, process, state, clock


def prepared(*, initially_live: bool = False):
    episode, loop, source, socket, process, state, clock = setup(
        initially_live=initially_live,
    )
    scope = GameScope("local_test_game", "1", "guarded_01")
    episode.start(scope, ("jump",), password="fake-test-password",
                  owner_approved=True)
    for n in range(1, 6):
        clock.value = 100 + n * 100
        assert episode.record_reactive_latency(
            sample_id=n, duration_ms=50, host_measured=True,
        )
    clock.value = 1100
    telemetry = StreamTelemetry(initially_live, True, 4096, 8192, 60, 0)
    frame = GameFrame(scope, 1, 1000, "a" * 64, True, True, 0.95)
    lease = episode.offer(frame, telemetry=telemetry, host_verified=True)
    assert lease.route == "reactive", lease.reason
    return episode, loop, source, socket, process, state, clock, telemetry, frame, lease


def hint():
    return GameActionHint("jump", 1, "a" * 64, 1015, 70)


def test_disabled_by_default_and_owner_approval():
    episode, loop, source, socket, process, state, clock = setup()
    scope = GameScope("local_test_game", "1", "guarded_01")
    with pytest.raises(ObsGuardedGameError):
        episode.offer(GameFrame(scope, 1, 100, "a" * 64, True, True, 0.95),
                      telemetry=None)
    with pytest.raises(PermissionError):
        episode.start(scope, ("jump",), password="p")
    assert not socket.sent
    assert state["keyups"] == 0
    episode.start(scope, ("jump",), password="p", owner_approved=True)
    assert episode.active
    episode.stop()
    assert episode.revoked
    assert state["keyups"] == 1 and state["cancel"] == 1
    with pytest.raises(ObsGuardedGameError):
        episode.start(scope, ("jump",), password="p", owner_approved=True)


def test_stable_session_claims_once_and_releases_without_sending_input():
    episode, loop, source, socket, process, state, clock, telemetry, frame, lease = prepared()
    clock.value = 1200
    permit = episode.finish(lease, frame, hint(), telemetry=telemetry,
                            host_verified=True)
    assert permit.offered
    clock.value = 1205
    assert episode.claim(permit)
    assert not permit.authorized_to_press_keys
    assert episode.release(permit, host_confirmed_released=True)
    assert state["keyups"] == 0  # No physical key path exists in the bridge.
    episode.stop()
    assert state["keyups"] == 1
    assert all(m["d"].get("requestType") == "GetStreamStatus"
               for m in socket.sent if m["op"] == 6)


def test_aba_during_inference_blocks_permit_without_fabricating_epoch():
    episode, loop, source, socket, process, state, clock, telemetry, frame, lease = prepared()
    transition(socket, True)
    transition(socket, False)
    clock.value = 1200
    permit = episode.finish(lease, frame, hint(), telemetry=telemetry,
                            host_verified=True)
    assert not permit.offered
    assert permit.reason == "stream_epoch_changed_during_inference"
    assert lease.stream_epoch_at_offer == 0


def test_aba_before_final_claim_revokes_and_requests_key_release():
    episode, loop, source, socket, process, state, clock, telemetry, frame, lease = prepared()
    clock.value = 1200
    permit = episode.finish(lease, frame, hint(), telemetry=telemetry,
                            host_verified=True)
    assert permit.offered
    transition(socket, True)
    transition(socket, False)
    clock.value = 1205
    assert not episode.claim(permit)
    assert episode.revoked and not episode.active
    assert state["keyups"] == 1 and state["cancel"] == 1
    with pytest.raises(ObsGuardedGameError):
        episode.claim(permit)


@pytest.mark.parametrize("which", ["focus", "permission"])
def test_final_independent_focus_and_permission_probes(which):
    episode, loop, source, socket, process, state, clock, telemetry, frame, lease = prepared()
    clock.value = 1200
    permit = episode.finish(lease, frame, hint(), telemetry=telemetry,
                            host_verified=True)
    state[which] = False
    clock.value = 1205
    assert not episode.claim(permit)
    assert episode.revoked and state["keyups"] == 1


def test_transport_failure_requests_cancel_and_release_and_cannot_rearm():
    episode, loop, source, socket, process, state, clock, telemetry, frame, lease = prepared()
    socket.fail_next_receive = True
    clock.value = 1200
    with pytest.raises(ObsGuardedGameError) as err:
        episode.finish(lease, frame, hint(), telemetry=telemetry,
                       host_verified=True)
    assert "fake-test-password" not in str(err.value)
    assert episode.revoked and state["keyups"] == 1 and state["cancel"] == 1
    assert not source.connected
    with pytest.raises(ObsGuardedGameError):
        episode.offer(frame, telemetry=telemetry, host_verified=True)


def test_process_restart_during_snapshot_revokes_without_stale_claim():
    episode, loop, source, socket, process, state, clock, telemetry, frame, lease = prepared()
    process["identity"] = (143, 3001.0)
    clock.value = 1200
    with pytest.raises(ObsGuardedGameError):
        episode.finish(lease, frame, hint(), telemetry=telemetry,
                       host_verified=True)
    assert episode.revoked and state["keyups"] == 1


def test_failed_cleanup_callback_cannot_rearm():
    episode, loop, source, socket, process, state, clock = setup()
    def broken_keys():
        state["keyups"] += 1
        raise RuntimeError("private callback detail")
    episode._release_keys = broken_keys
    scope = GameScope("local_test_game", "1", "guarded_01")
    episode.start(scope, ("jump",), password="p", owner_approved=True)
    episode.stop()
    assert episode.revoked and not episode.active
    assert state["cancel"] == 1 and state["keyups"] == 1
    with pytest.raises(ObsGuardedGameError):
        episode.start(scope, ("jump",), password="p", owner_approved=True)


def test_malformed_host_telemetry_fails_closed_not_relaxed():
    episode, loop, source, socket, process, state, clock, telemetry, frame, lease = prepared()
    clock.value = 1200
    with pytest.raises(ObsGuardedGameError):
        episode.finish(lease, frame, hint(), telemetry="model-supplied",
                       host_verified=True)
    assert episode.revoked and state["keyups"] == 1


def test_invalid_owner_credentials_does_not_leave_half_enabled():
    episode, loop, source, socket, process, state, clock = setup()
    scope = GameScope("local_test_game", "1", "guarded_01")
    with pytest.raises(ObsGuardedGameError):
        episode.start(scope, ("jump",), password="", owner_approved=True)
    assert episode.revoked and state["keyups"] == 1

def test_host_stop_during_blocked_obs_sample_requests_immediate_keyup():
    """A blocked WebSocket cannot delay the trusted host's emergency key-up."""
    from threading import Event, Thread

    episode, loop, source, socket, process, state, clock, telemetry, frame, lease = prepared()
    clock.value = 1200
    entered, resume, stop_returned = Event(), Event(), Event()
    original_snapshot = source.snapshot
    failures = []
    permits = []

    def slow_snapshot():
        entered.set()
        if not resume.wait(3):
            raise TimeoutError("simulated OBS request timeout")
        return original_snapshot()

    source.snapshot = slow_snapshot

    def inference_thread():
        try:
            permits.append(episode.finish(
                lease, frame, hint(), telemetry=telemetry, host_verified=True,
            ))
        except Exception as exc:
            failures.append(exc)

    worker = Thread(target=inference_thread, daemon=True)
    worker.start()
    assert entered.wait(2), "OBS sample must actually block before stop"
    stopper = Thread(target=lambda: (episode.stop(), stop_returned.set()), daemon=True)
    stopper.start()
    try:
        assert stop_returned.wait(0.4), "host stop must not wait for OBS socket"
        assert state["keyups"] == 1 and state["cancel"] == 1
        assert not episode.active
    finally:
        resume.set()
        worker.join(3)
        stopper.join(3)
    assert not worker.is_alive() and not stopper.is_alive()
    assert not permits, "in-flight permit must not survive an emergency stop"
    assert len(failures) == 1 and isinstance(failures[0], ObsGuardedGameError)
    episode.stop()
    assert state["keyups"] == 1 and state["cancel"] == 1


def test_host_stop_while_final_claim_waits_for_obs_rejects_stale_claim():
    """No positive advisory claim may emerge after shutdown mid-fence."""
    from threading import Event, Thread

    episode, loop, source, socket, process, state, clock, telemetry, frame, lease = prepared()
    clock.value = 1200
    permit = episode.finish(lease, frame, hint(), telemetry=telemetry,
                            host_verified=True)
    assert permit.offered
    clock.value = 1205
    entered, resume, shutdown = Event(), Event(), Event()
    original = source.snapshot
    results = []

    def blocked_snapshot():
        entered.set()
        if not resume.wait(3):
            raise TimeoutError("OBS simulated timeout")
        return original()

    source.snapshot = blocked_snapshot

    def pending_claim():
        try:
            results.append(episode.claim(permit))
        except Exception as exc:
            results.append(exc)

    worker = Thread(target=pending_claim, daemon=True)
    worker.start()
    assert entered.wait(2)
    stopper = Thread(target=lambda: (episode.stop(), shutdown.set()), daemon=True)
    stopper.start()
    try:
        assert shutdown.wait(0.4)
        assert episode.revoked
        assert state["keyups"] == 1 and state["cancel"] == 1
    finally:
        resume.set()
        worker.join(3)
        stopper.join(3)
    assert len(results) == 1 and results[0] is not True
    assert not worker.is_alive() and not stopper.is_alive()
    episode.stop()
    assert state["keyups"] == 1 and state["cancel"] == 1
