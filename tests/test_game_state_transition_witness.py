"""Offline adversarial tests for the isolated game-state transition witness."""
from __future__ import annotations

from dataclasses import replace

import pytest

from star.game_state_transition_witness import (
    GameStateSample, GameTelemetryError, VerifiedGameStateObserver,
)
from star.stream_episode_journal import StreamEpisodeJournal
from star.stream_moment_receipts import verify_game_moment

KEY = b"S" * 32


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def tick(self, amount=0.1):
        self.t += amount


def state(frame, round_id=1, phase="playing", checkpoint=0):
    return GameStateSample(frame, round_id, phase, checkpoint)


def host(clock=None, journal=None, scope="offline_test"):
    clock = clock or Clock()
    journal = journal or StreamEpisodeJournal(receipt_key=KEY)
    journal.enable(owner_approved=True)
    observer = VerifiedGameStateObserver(
        game_scope=scope, session_id=journal.session_id,
        receipt_key=KEY, clock=clock, max_gap_s=0.5,
    )
    observer.enable(owner_approved=True)
    return observer, journal, clock


def take(observer, clock, sample, dt=0.1):
    clock.tick(dt)
    return observer.ingest(sample)


def assert_attested(receipt, journal, *, kind):
    assert receipt is not None
    assert receipt.moment.kind == kind
    assert receipt.moment.game_scope == "offline_test"
    assert "mac=" not in repr(receipt.receipt)
    assert journal.record(
        receipt.moment, now_s=receipt.now_s, host_observed=True,
        receipt=receipt.receipt,
    )


def test_confirmed_checkpoint_is_signed_and_journal_recalls_only_fact():
    observer, journal, clock = host()
    assert observer.ingest(state(1)) is None
    assert take(observer, clock, state(2, checkpoint=1)) is None
    result = take(observer, clock, state(3, checkpoint=1))
    assert_attested(result, journal, kind="checkpoint")
    assert result.moment.moment_id == "checkpoint.r1.p1"
    assert result.moment.stage_id == "cp1"
    assert journal.recall(now_s=clock.t, game_scope="offline_test")[0].context == (
        "Earlier in offline_test, Star reached a checkpoint on stage cp1."
    )
    assert take(observer, clock, state(4, checkpoint=1)) is None
    assert journal.metrics()["recorded"] == 1


def test_win_requires_existing_play_state_and_two_observations():
    observer, journal, clock = host()
    assert observer.ingest(state(1)) is None
    assert take(observer, clock, state(2, phase="won")) is None
    assert journal.metrics()["recorded"] == 0
    result = take(observer, clock, state(3, phase="won"))
    assert_attested(result, journal, kind="win")
    assert result.moment.moment_id == "win.r1"
    assert take(observer, clock, state(4, phase="won")) is None


def test_loss_is_distinct_and_new_round_must_be_explicit():
    observer, journal, clock = host()
    observer.ingest(state(1))
    take(observer, clock, state(2, phase="lost"))
    result = take(observer, clock, state(3, phase="lost"))
    assert_attested(result, journal, kind="loss")
    assert take(observer, clock, state(4, round_id=2)) is None
    assert take(observer, clock, state(5, round_id=2, phase="won")) is None
    assert_attested(take(observer, clock, state(6, round_id=2, phase="won")), journal, kind="win")
    assert journal.metrics()["recorded"] == 2


def test_one_sample_checkpoint_and_round_jump_do_not_claim_win():
    observer, journal, clock = host()
    observer.ingest(state(1))
    assert take(observer, clock, state(2, checkpoint=1)) is None
    # The first checkpoint was not corroborated. Starting a new round
    # cancels the pending claim, and may not create a success on its own.
    assert take(observer, clock, state(3, round_id=2)) is None
    assert take(observer, clock, state(4, round_id=2)) is None
    assert journal.metrics()["recorded"] == 0


def test_independent_authoritative_samples_provide_distinct_checkpoint_ids():
    observer, journal, clock = host()
    observer.ingest(state(1))
    for idx, cp in [(2, 1), (3, 1), (4, 2), (5, 2)]:
        result = take(observer, clock, state(idx, checkpoint=cp))
        if idx in (3, 5):
            assert_attested(result, journal, kind="checkpoint")
        else:
            assert result is None
    assert journal.metrics()["recorded"] == 2


def test_receipt_must_match_session_scope_and_observation_time():
    observer, journal, clock = host()
    observer.ingest(state(1))
    take(observer, clock, state(2, checkpoint=1))
    result = take(observer, clock, state(3, checkpoint=1))
    assert result is not None
    assert not verify_game_moment(
        result.moment, result.receipt, session_id="0" * 32, key=KEY
    )
    assert not journal.record(
        replace(result.moment, kind="win"), now_s=result.now_s,
        host_observed=True, receipt=result.receipt,
    )
    assert not journal.record(
        replace(result.moment, at_s=result.now_s + 1), now_s=result.now_s,
        host_observed=True, receipt=result.receipt,
    )
    assert_attested(result, journal, kind="checkpoint")
    assert not journal.record(
        result.moment, now_s=result.now_s, host_observed=True,
        receipt=result.receipt,
    )


@pytest.mark.parametrize("kwargs", [
    dict(frame=True, round_id=1, phase="playing", checkpoint=0),
    dict(frame=-1, round_id=1, phase="playing", checkpoint=0),
    dict(frame=1, round_id=0, phase="playing", checkpoint=0),
    dict(frame=1, round_id=True, phase="playing", checkpoint=0),
    dict(frame=1, round_id=1, phase="WIN", checkpoint=0),
    dict(frame=1, round_id=1, phase="playing", checkpoint=-1),
    dict(frame=1, round_id=1, phase="playing", checkpoint=1.0),
    dict(frame=1, round_id=1, phase="playing", checkpoint=10**15),
])
def test_rejects_malformed_state(kwargs):
    with pytest.raises(ValueError):
        GameStateSample(**kwargs)


def test_disabled_by_default_and_owner_gated():
    clock = Clock()
    journal = StreamEpisodeJournal(receipt_key=KEY)
    journal.enable(owner_approved=True)
    observer = VerifiedGameStateObserver(
        game_scope="offline_test", session_id=journal.session_id,
        receipt_key=KEY, clock=clock,
    )
    with pytest.raises(GameTelemetryError):
        observer.ingest(state(1))
    with pytest.raises(PermissionError):
        observer.enable()
    observer.enable(owner_approved=True)
    observer.ingest(state(1))
    observer.disable()
    with pytest.raises(GameTelemetryError):
        observer.ingest(state(2, phase="won"))
    with pytest.raises(RuntimeError):
        observer.enable(owner_approved=True)


@pytest.mark.parametrize("sample,dt", [
    (state(1), 0.1),  # repeated game frame
    (state(0), 0.1),  # reversed game frame
    (state(1000), 0.1),  # impossible game-frame jump
    (state(2), 0),  # stalled trusted clock
    (state(2), 0.6),  # missing sample window
    (state(2, round_id=3), 0.1),  # skipped round
    (state(2, checkpoint=1), -0.1),  # rewound host clock
])
def test_continuity_fault_revokes_permanently(sample, dt):
    observer, journal, clock = host()
    observer.ingest(state(1))
    with pytest.raises(GameTelemetryError):
        take(observer, clock, sample, dt)
    assert not observer.active
    with pytest.raises(GameTelemetryError):
        observer.ingest(state(5))
    assert journal.metrics()["recorded"] == 0


def test_round_and_checkpoint_regression_fail_closed():
    observer, _, clock = host()
    observer.ingest(state(1, checkpoint=2))
    with pytest.raises(GameTelemetryError):
        take(observer, clock, state(2, checkpoint=1))
    assert not observer.active


def test_terminal_to_playing_same_round_is_rejected():
    observer, _, clock = host()
    observer.ingest(state(1))
    take(observer, clock, state(2, phase="won"))
    with pytest.raises(GameTelemetryError):
        take(observer, clock, state(3, phase="playing"))
    assert not observer.active


def test_new_round_must_start_in_playing_phase():
    observer, _, clock = host()
    observer.ingest(state(1))
    with pytest.raises(GameTelemetryError):
        take(observer, clock, state(2, round_id=2, phase="won"))


def test_initial_untested_win_fails_closed():
    observer, _, _ = host()
    with pytest.raises(GameTelemetryError):
        observer.ingest(state(1, phase="won"))
    assert not observer.active


def test_invalid_source_record_revokes():
    observer, _, _ = host()
    with pytest.raises(GameTelemetryError):
        observer.ingest({"frame": 1})
    assert not observer.active


def test_unreliable_source_clock_revokes_without_signing():
    clock = Clock()
    observer, journal, _ = host(clock=clock)
    observer.ingest(state(1))
    clock.t = float("nan")
    with pytest.raises(GameTelemetryError):
        observer.ingest(state(2, phase="won"))
    assert journal.metrics()["recorded"] == 0


def test_new_journal_session_is_not_replayable():
    observer, journal, clock = host()
    observer.ingest(state(1))
    take(observer, clock, state(2, phase="won"))
    event = take(observer, clock, state(3, phase="won"))
    assert event is not None
    journal.disable()
    journal.enable(owner_approved=True)
    assert not journal.record(
        event.moment, now_s=event.now_s, host_observed=True,
        receipt=event.receipt,
    )
    assert journal.metrics()["recorded"] == 0


@pytest.mark.parametrize("scope", ["../../x", "a b", "", "x" * 70])
def test_rejects_invalid_game_scope(scope):
    with pytest.raises(ValueError):
        VerifiedGameStateObserver(
            game_scope=scope, session_id="a" * 32, receipt_key=KEY,
        )


def test_isolated_engine_source_not_exposed_as_model_verification():
    observer, journal, clock = host()
    observer.ingest(state(1))
    assert take(observer, clock, state(2, phase="won")) is None
    # A model-generated "win" still has no route to a signing receipt.
    from star.stream_episode_journal import GameMoment
    forged = GameMoment("win.r1", "offline_test", "win", clock.t)
    assert not journal.record(forged, now_s=clock.t, host_observed=True)
    assert journal.metrics()["recorded"] == 0
