"""Offline integration proving signed game-source loss cancels the input adapter.

No Windows device, network, game, microphone, OBS broadcast or model is used.
The fake actuation port checks the same host cancellation path as the real
bounded Windows adapter but does NOT establish that Win32 released physical keys.
"""
from __future__ import annotations

from threading import Event, Thread
import time

import pytest

from star.authoritative_game_telemetry_source import AuthoritativeGameTelemetrySource
from star.game_state_transition_witness import GameStateSample, VerifiedGameStateObserver
from star.game_action_outcome_feedback import GameActionOutcomeFeedback
from star.game_telemetry_liveness_guard import GameTelemetryLivenessGuard, GameTelemetryLivenessLost
from star.game_telemetry_source_bridge import AuthenticatedGameTelemetryBridge
from star.game_telemetry_actuation_interlock import TelemetryActuationInterlock
from star.stream_episode_journal import StreamEpisodeJournal

from test_game_actuation_rehearsal import ready
from test_game_telemetry_tick_supervisor import Clock, Engine

_GAME = "local_test_game"
_KEY_SOURCE = b"source_test_key_0000000000000000"
_KEY_MOMENT = b"moment_test_key_0000000000000000"


def prepared_interlock(*, armed: bool = True, outcome_enabled: bool = False):
    adapter, permit, port, episode, _ = ready()
    clock = Clock()
    engine = Engine(clock)
    journal = StreamEpisodeJournal(receipt_key=_KEY_MOMENT)
    journal.enable(owner_approved=True)
    session = journal.session_id
    assert session is not None
    observer = VerifiedGameStateObserver(
        game_scope=_GAME, session_id=session,
        receipt_key=_KEY_MOMENT, clock=clock,
    )
    observer.enable(owner_approved=True)
    bridge = AuthenticatedGameTelemetryBridge(
        source_id="local_engine", session_id=session,
        source_key=_KEY_SOURCE, observer=observer, journal=journal,
    )
    bridge.enable(owner_approved=True)
    source = AuthoritativeGameTelemetrySource(
        source_id="local_engine", session_id=session, source_key=_KEY_SOURCE,
        trusted_reader=engine.read, clock=clock,
    )
    source.enable(owner_approved=True)
    guard = GameTelemetryLivenessGuard(bridge, clock=clock, max_silence_s=0.15)
    if armed:
        guard.arm(owner_approved=True)
    outcomes = GameActionOutcomeFeedback(
        game_scope=_GAME, session_id=session, receipt_key=_KEY_MOMENT,
        clock=clock, window_s=0.5,
    ) if outcome_enabled else None
    interlock = TelemetryActuationInterlock(
        guard=guard, actuation=adapter, expected_game_scope=_GAME,
        tick_interval_s=0.01, outcome_feedback=outcomes,
    )
    return interlock, adapter, permit, port, episode, clock, engine, journal, bridge, source


def test_off_by_default_no_input_without_owner_and_first_signed_frame():
    lock, _, permit, port, _, _, _, _, _, source = prepared_interlock()
    assert lock.run(permit).status == "telemetry_unavailable"
    with pytest.raises(PermissionError):
        lock.start()
    assert port["pressed"] == 0
    lock.start(owner_approved=True)
    try:
        assert lock.run(permit).status == "telemetry_not_established"
        assert port["pressed"] == 0
        lock.accept(source.poll())
        result = lock.run(permit)
        assert result.status == "released_verified"
        assert result.keys_up_verified and result.claimed
        assert port["pressed"] == 1 and not port["held"]
        assert lock.status().frames == 1 and lock.status().active
        assert not lock.status().authorizes_gameplay
        assert not lock.status().authorizes_broadcast
    finally:
        lock.stop()
    assert lock.status().revoked and not lock.status().active


def test_cannot_bind_telemetry_to_different_obs_game_or_claim_as_victory():
    lock, adapter, _, port, _, _, _, _, _, _ = prepared_interlock()
    with pytest.raises(ValueError):
        TelemetryActuationInterlock(
            guard=lock._supervisor._guard, actuation=adapter,
            expected_game_scope="unrelated_game",
        )
    assert not port["pressed"]
    lock.stop()


def test_signed_checkpoint_reaches_private_journal_without_authorizing_speech():
    lock, _, permit, port, _, clock, engine, journal, _, source = prepared_interlock()
    lock.start(owner_approved=True)
    try:
        assert lock.accept(source.poll()) is None
        engine.checkpoint = 1
        assert lock.accept(source.poll()) is None
        event = lock.accept(source.poll())
        assert event is not None and event.moment.kind == "checkpoint"
        assert lock.status().moments == 1
        recalls = journal.recall(now_s=clock(), game_scope=_GAME)
        assert len(recalls) == 1
        assert all(not recall.authorized_to_speak for recall in recalls)
        assert lock.run(permit).status == "released_verified"
        assert port["pressed"] == 1
    finally:
        lock.stop()
    assert journal.session_id is None


def test_corrupted_packet_revokes_journal_and_prevents_input():
    lock, adapter, permit, port, _, _, _, journal, bridge, source = prepared_interlock()
    lock.start(owner_approved=True)
    lock.accept(source.poll())
    with pytest.raises(GameTelemetryLivenessLost):
        lock.accept(b"viewer fabricated win packet")
    assert adapter.stopped and lock.status().revoked
    assert journal.session_id is None and not bridge.active
    assert lock.run(permit).status == "telemetry_unavailable"
    assert port["pressed"] == 0 and port["up_requests"] >= 1


def test_replay_revokes_after_real_checkpoint_not_accepted_as_new_event():
    lock, _, permit, port, _, _, engine, journal, _, source = prepared_interlock()
    lock.start(owner_approved=True)
    packet = source.poll()
    lock.accept(packet)
    engine.checkpoint = 1
    lock.accept(source.poll())
    lock.accept(source.poll())
    assert lock.status().moments == 1
    with pytest.raises(GameTelemetryLivenessLost):
        lock.accept(packet)
    assert lock.status().revoked and journal.session_id is None
    assert port["pressed"] == 0
    assert lock.run(permit).status == "telemetry_unavailable"


def test_background_source_silence_stops_actuation_without_next_packet():
    lock, adapter, permit, port, episode, clock, _, journal, _, source = prepared_interlock()
    lock.start(owner_approved=True)
    lock.accept(source.poll())
    clock.advance(0.30)
    for _ in range(100):
        if lock.status().revoked:
            break
        time.sleep(.01)
    assert lock.status().revoked
    assert adapter.stopped and episode.revoked and journal.session_id is None
    assert port["up_requests"] >= 1
    assert lock.run(permit).status == "telemetry_unavailable"
    assert port["pressed"] == 0


def test_source_expires_while_input_in_flight_and_never_claims_success():
    lock, adapter, permit, port, _, clock, _, journal, _, source = prepared_interlock()
    lock.start(owner_approved=True)
    lock.accept(source.poll())
    entered, finish = Event(), Event()
    results = []
    def blocked_send(action, hold_ms, cancelled):
        entered.set()
        assert finish.wait(2)
        return not cancelled.is_set()
    adapter._send_action = blocked_send
    thread = Thread(target=lambda: results.append(lock.run(permit)), daemon=True)
    thread.start()
    assert entered.wait(1)
    clock.advance(.30)
    for _ in range(100):
        if lock.status().revoked:
            break
        time.sleep(.01)
    assert lock.status().revoked and adapter.stopped
    finish.set()
    thread.join(2)
    assert len(results) == 1 and results[0].status != "released_verified"
    assert journal.session_id is None and not port["pressed"]


def test_postflight_expired_telemetry_cannot_count_released_key_as_success():
    lock, adapter, permit, port, _, clock, _, _, _, source = prepared_interlock()
    lock.start(owner_approved=True)
    lock.accept(source.poll())
    old_send = adapter._send_action
    def signed_source_expires(action, hold_ms, cancelled):
        result = old_send(action, hold_ms, cancelled)
        clock.advance(.30)
        return result
    adapter._send_action = signed_source_expires
    result = lock.run(permit)
    assert result.status == "telemetry_lost_during_action"
    assert port["pressed"] == 1 and not port["held"]
    assert lock.status().revoked


def test_faulted_actuation_also_revokes_authentication_and_journal():
    lock, adapter, permit, port, _, _, _, journal, bridge, source = prepared_interlock()
    lock.start(owner_approved=True)
    lock.accept(source.poll())
    adapter._send_action = lambda *_: False
    assert lock.run(permit).status == "dispatch_failed"
    assert lock.status().revoked and journal.session_id is None and not bridge.active
    assert lock.run(permit).status == "telemetry_unavailable"
    assert port["pressed"] == 0


def test_unarmed_receiver_failure_is_terminal_and_no_restarts():
    lock, adapter, permit, port, _, _, _, journal, bridge, _ = prepared_interlock(armed=False)
    with pytest.raises(GameTelemetryLivenessLost):
        lock.start(owner_approved=True)
    assert adapter.stopped and journal.session_id is None and not bridge.active
    assert lock.status().revoked and port["pressed"] == 0
    lock.stop()
    lock.stop()
    with pytest.raises(RuntimeError):
        lock.start(owner_approved=True)
    assert lock.run(permit).status == "telemetry_unavailable"


@pytest.mark.parametrize("scope", ["", "wrong game", "x"*65, 123, None])
def test_bad_expected_scope_rejected(scope):
    lock, adapter, *_ = prepared_interlock()
    with pytest.raises(ValueError):
        TelemetryActuationInterlock(
            guard=lock._supervisor._guard, actuation=adapter, expected_game_scope=scope,
        )
    lock.stop()


def test_wrong_components_rejected():
    lock, adapter, *_ = prepared_interlock()
    with pytest.raises(TypeError):
        TelemetryActuationInterlock(
            guard=object(), actuation=adapter, expected_game_scope=_GAME,
        )
    with pytest.raises(TypeError):
        TelemetryActuationInterlock(
            guard=lock._supervisor._guard, actuation=object(), expected_game_scope=_GAME,
        )
    lock.stop()


def test_verified_action_feedback_only_after_actual_post_release_engine_progress():
    lock, _, permit, port, _, _, engine, _, _, source = prepared_interlock(
        outcome_enabled=True,
    )
    assert lock.outcome_feedback().status == "idle"
    lock.start(owner_approved=True)
    try:
        lock.accept(source.poll())  # Signed baseline, no outcome yet.
        released = lock.run(permit)
        assert released.status == "released_verified" and released.keys_up_verified
        assert lock.outcome_feedback().status == "awaiting_evidence"
        # No second input while the first has unverified follow-up evidence.
        assert lock.run(permit).status == "previous_outcome_pending"
        assert port["pressed"] == 1
        engine.checkpoint = 1
        assert lock.accept(source.poll()) is None  # One frame is insufficient.
        assert lock.outcome_feedback().status == "awaiting_evidence"
        receipt = lock.accept(source.poll())
        assert receipt is not None and receipt.moment.kind == "checkpoint"
        observed = lock.outcome_feedback()
        assert observed.status == "observed_progress_after_action"
        assert observed.observed_progress and observed.ticket == permit.ticket
        assert not observed.authorizes_skill_credit
        assert not observed.authorizes_broadcast_claim
    finally:
        lock.stop()
    assert lock.outcome_feedback().status == "revoked"


def test_verified_action_feedback_records_loss_without_claiming_play_skill():
    lock, _, permit, _, _, clock, engine, _, _, source = prepared_interlock(
        outcome_enabled=True,
    )
    lock.start(owner_approved=True)
    try:
        lock.accept(source.poll())
        assert lock.run(permit).status == "released_verified"
        def terminal_sample():
            clock.advance()
            engine.frame += 1
            return GameStateSample(engine.frame, 1, "lost", engine.checkpoint)
        # The owned test engine now authoritatively reports a lost round.
        source._reader = terminal_sample
        lock.accept(source.poll())
        receipt = lock.accept(source.poll())
        assert receipt is not None and receipt.moment.kind == "loss"
        outcome = lock.outcome_feedback()
        assert outcome.status == "observed_loss_after_action"
        assert not outcome.observed_progress and not outcome.authorizes_skill_credit
    finally:
        lock.stop()


def test_corrupted_signed_packet_clears_pending_action_feedback():
    lock, _, permit, port, _, _, _, _, _, source = prepared_interlock(
        outcome_enabled=True,
    )
    lock.start(owner_approved=True)
    lock.accept(source.poll())
    assert lock.run(permit).status == "released_verified"
    assert lock.outcome_feedback().status == "awaiting_evidence"
    with pytest.raises(GameTelemetryLivenessLost):
        lock.accept(b"viewer-generated progress")
    assert lock.outcome_feedback().status == "revoked"
    assert not port["held"] and lock.status().revoked


def test_cross_game_feedback_cannot_attach_to_input_interlock():
    lock, adapter, _, _, _, clock, _, journal, _, _ = prepared_interlock()
    bad = GameActionOutcomeFeedback(
        game_scope="other_game", session_id=journal.session_id,
        receipt_key=_KEY_MOMENT, clock=clock,
    )
    with pytest.raises(ValueError):
        TelemetryActuationInterlock(
            guard=lock._supervisor._guard, actuation=adapter,
            expected_game_scope=_GAME, outcome_feedback=bad,
        )
    lock.stop()
