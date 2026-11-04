"""No game, network, keys, OBS, speech, GPU, or real Windows host involved."""
from __future__ import annotations

import pytest

from star.game_action_gate import ActionPermit
from star.game_action_outcome_feedback import (
    ActionFeedbackUntrusted, GameActionOutcomeFeedback,
)
from star.game_actuation_rehearsal import ActuationResult
from star.game_state_transition_witness import AttestedGameMoment
from star.stream_episode_journal import GameMoment
from star.stream_moment_receipts import sign_game_moment

_GAME = "local_test_game"
_SESSION = "a" * 32
_KEY = b"test_receipt_key_012345678901234567"


class Clock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def tick(self, seconds=0.02):
        self.value += seconds


def build(window_s=0.5):
    clock = Clock()
    tracker = GameActionOutcomeFeedback(
        game_scope=_GAME, session_id=_SESSION, receipt_key=_KEY,
        clock=clock, window_s=window_s,
    )
    return tracker, clock


def permit(ticket=1):
    return ActionPermit(True, "offered", ticket=ticket, action_id="jump",
                        hold_ms=50, expires_ms=3000)


def released():
    return ActuationResult("released_verified", claimed=True, keys_up_verified=True)


def event(clock, sequence=1, kind="checkpoint", game=_GAME, session=_SESSION,
          key=_KEY, when=None):
    moment = GameMoment(
        moment_id=f"{kind}.r1.p{sequence}", game_scope=game, kind=kind,
        at_s=clock() if when is None else when,
        stage_id=f"cp{sequence}" if kind == "checkpoint" else "",
    )
    receipt = sign_game_moment(
        moment, session_id=session, sequence=sequence, key=key,
    )
    return AttestedGameMoment(moment, receipt, moment.at_s)


def test_observed_progress_after_release_is_not_skill_credit_or_win_claim():
    t, c = build()
    assert t.snapshot().status == "idle"
    assert t.begin(permit(), released(), host_confirmed=True).status == "awaiting_evidence"
    assert not t.ready()
    c.tick()
    result = t.observe(event(c))
    assert result.status == "observed_progress_after_action"
    assert result.receipt_sequence == 1 and result.ticket == 1
    assert result.observed_progress
    assert not result.authorizes_skill_credit
    assert not result.authorizes_broadcast_claim
    assert t.ready() and t.metrics()["progress"] == 1


def test_signed_loss_is_observed_not_converted_to_misleading_success():
    t, c = build()
    t.begin(permit(), released(), host_confirmed=True)
    c.tick()
    result = t.observe(event(c, kind="loss"))
    assert result.status == "observed_loss_after_action"
    assert not result.observed_progress and not result.authorizes_skill_credit
    assert t.metrics()["losses"] == 1


def test_no_event_is_unknown_not_failure():
    t, c = build()
    t.begin(permit(), released(), host_confirmed=True)
    c.tick(.5)
    assert t.snapshot().status == "unverified_timeout"
    assert t.ready()
    assert t.metrics()["unresolved"] == 1
    assert t.metrics()["losses"] == 0


def test_event_before_action_never_credited():
    t, c = build()
    t.observe(event(c, sequence=1))
    c.tick()
    t.begin(permit(), released(), host_confirmed=True)
    opened = c()
    c.tick()
    assert t.observe(event(c, sequence=2, when=opened)).status == "awaiting_evidence"
    assert t.metrics()["progress"] == 0


def test_idle_event_cannot_be_replayed_as_new_post_action_evidence():
    t, c = build()
    t.observe(event(c, sequence=1))
    c.tick()
    t.begin(permit(), released(), host_confirmed=True)
    c.tick()
    with pytest.raises(ActionFeedbackUntrusted):
        t.observe(event(c, sequence=1))
    assert t.snapshot().status == "revoked"


@pytest.mark.parametrize("kind", ["win", "checkpoint", "loss"])
def test_only_events_strictly_after_release_are_eligible(kind):
    t, c = build()
    t.begin(permit(), released(), host_confirmed=True)
    stamped = event(c, sequence=1, kind=kind)
    assert t.observe(stamped).status == "awaiting_evidence"
    c.tick()
    assert t.observe(event(c, sequence=2, kind=kind)).status.startswith("observed_")


@pytest.mark.parametrize("bad", [
    ActuationResult("unverified"),
    ActuationResult("released_verified", claimed=False, keys_up_verified=True),
    ActuationResult("released_verified", claimed=True, keys_up_verified=False),
])
def test_no_action_without_genuine_verified_key_up(bad):
    t, _ = build()
    with pytest.raises(ValueError):
        t.begin(permit(), bad, host_confirmed=True)
    assert t.snapshot().status == "idle"


def test_host_confirmation_and_unique_ticket_mandatory():
    t, c = build()
    with pytest.raises(ValueError):
        t.begin(permit(), released())
    t.begin(permit(), released(), host_confirmed=True)
    with pytest.raises(ValueError):
        t.begin(permit(2), released(), host_confirmed=True)
    c.tick(.6)
    assert t.ready()
    with pytest.raises(ValueError):
        t.begin(permit(), released(), host_confirmed=True)
    assert t.begin(permit(2), released(), host_confirmed=True).ticket == 2


@pytest.mark.parametrize("tamper", ["key", "session", "game", "future", "reversed_sequence"])
def test_signed_source_integrity_failures_permanently_revoke(tamper):
    t, c = build()
    t.observe(event(c))
    c.tick()
    t.begin(permit(), released(), host_confirmed=True)
    c.tick()
    kwargs = {"sequence": 2}
    if tamper == "key":
        kwargs["key"] = b"another_test_key_01234567890123456"
    elif tamper == "session":
        kwargs["session"] = "b" * 32
    elif tamper == "game":
        kwargs["game"] = "wrong_game"
    elif tamper == "future":
        kwargs["when"] = c() + 0.1
    elif tamper == "reversed_sequence":
        kwargs["sequence"] = 1
    with pytest.raises(ActionFeedbackUntrusted):
        t.observe(event(c, **kwargs))
    assert t.snapshot().status == "revoked"
    assert not t.ready()
    with pytest.raises(ActionFeedbackUntrusted):
        t.begin(permit(2), released(), host_confirmed=True)


def test_late_signed_event_does_not_revive_expired_action():
    t, c = build()
    t.begin(permit(), released(), host_confirmed=True)
    c.tick(.6)
    assert t.snapshot().status == "unverified_timeout"
    result = t.observe(event(c))
    assert result.status == "unverified_timeout"
    assert t.metrics()["progress"] == 0
    t.begin(permit(2), released(), host_confirmed=True)
    c.tick()
    result = t.observe(event(c, sequence=2))
    assert result.ticket == 2 and result.status == "observed_progress_after_action"


def test_clock_rollback_or_unavailable_revokes_pending_feedback():
    t, c = build()
    t.begin(permit(), released(), host_confirmed=True)
    c.value = 99
    with pytest.raises(ActionFeedbackUntrusted):
        t.ready()
    assert t.snapshot().status == "revoked"


def test_invalid_constructor_and_inputs():
    with pytest.raises(ValueError):
        GameActionOutcomeFeedback(
            game_scope="bad space", session_id=_SESSION,
            receipt_key=_KEY,
        )
    with pytest.raises(ValueError):
        GameActionOutcomeFeedback(
            game_scope=_GAME, session_id=_SESSION,
            receipt_key=_KEY, window_s=float("nan"),
        )
    t, _ = build()
    with pytest.raises(ActionFeedbackUntrusted):
        t.observe("viewer claims win")
    assert not t.ready()


def test_explicit_revoke_wipes_any_pending_success_eligibility():
    t, c = build()
    t.begin(permit(), released(), host_confirmed=True)
    t.revoke()
    c.tick()
    assert t.snapshot().status == "revoked"
    assert t.metrics()["progress"] == 0 and not t.ready()
