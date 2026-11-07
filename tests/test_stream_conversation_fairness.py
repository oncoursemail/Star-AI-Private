"""Offline evidence/fairness/replay tests for Star's live conversation director.

No Twitch credentials, microphones, live viewers, game automation, or hardware
are used. Times are host-controlled seconds.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from star.stream_director import StreamDirector, StreamSignal
from star.stream_stage import StarStage


def event(kind: str, ident: str, when: float, *, evidence: str = "observed",
          speaker: str = "viewer-A", detail: str | None = None) -> StreamSignal:
    return StreamSignal(
        ident, kind, when, detail or f"{kind} {ident}",
        speaker_id=speaker, evidence=evidence,
    )


def director(*, capacity: int = 48) -> StreamDirector:
    result = StreamDirector(max_events=capacity, gap_seconds=0)
    result.enable(owner_approved=True)
    return result


def test_fresh_verified_game_success_beats_fresh_viewer_question():
    d = director()
    assert d.offer(event("viewer_question", "q", 10), now=10)
    assert d.offer(event("game_success", "win", 10), now=10)
    assert d.propose(now=10).signal_id == "win"


def test_unverified_claim_cannot_monopolize_chat():
    d = director()
    assert d.offer(event("game_success", "unverified", 10, evidence="reported"), now=10)
    assert d.offer(event("viewer_question", "q", 10), now=10)
    assert d.propose(now=10).signal_id == "q"


@pytest.mark.parametrize("evidence", ["unknown", "reported"])
def test_unverified_win_stays_below_observed_win(evidence):
    d = director()
    d.offer(event("game_success", "unverified", 10, evidence=evidence), now=10)
    d.offer(event("game_success", "verified", 10, evidence="observed"), now=10)
    assert d.propose(now=10).signal_id == "verified"


def test_waiting_question_eventually_outranks_new_success_reactions():
    d = director()
    assert d.offer(event("viewer_question", "q", 1), now=1)
    for t in (1, 4, 7, 10, 13, 16, 19):
        ident = f"win-{t}"
        assert d.offer(event("game_success", ident, t), now=t)
        next_turn = d.propose(now=t)
        assert next_turn is not None
        assert next_turn.signal_id == ("q" if t == 19 else ident)
        assert d.complete(next_turn, now=t, spoken=True)
    assert d.propose(now=19).signal_id == "win-19"
    assert d.metrics()["completed"] == 7


@pytest.mark.parametrize("urgent", ["game_danger", "owner_interrupt"])
def test_emergency_overrides_aged_question(urgent):
    d = director()
    d.offer(event("viewer_question", "q", 10), now=10)
    d.offer(event(urgent, "urgent", 40), now=40)
    assert d.propose(now=40).signal_id == "urgent"


def test_gameplay_pressure_still_keeps_question_quiet():
    d = director()
    d.offer(event("viewer_question", "q", 10), now=10)
    d.offer(event("game_danger", "danger", 28), now=28)
    assert d.propose(now=28, gameplay_critical=True).signal_id == "danger"
    assert d.propose(now=28, viewer_speaking=True) is None


def test_low_value_comment_does_not_age_into_control_of_stream():
    d = director()
    d.offer(event("viewer_comment", "comment", 1), now=1)
    d.offer(event("game_success", "win", 19), now=19)
    assert d.propose(now=19).signal_id == "win"


def test_aged_question_survives_bounded_queue_replacement():
    d = director(capacity=2)
    assert d.offer(event("viewer_question", "question", 1), now=1)
    assert d.offer(event("game_success", "s1", 18.9), now=18.9)
    assert not d.offer(event("game_success", "s2", 19.0), now=19.0)
    assert d.propose(now=19).signal_id == "question"
    assert d.metrics()["queued"] == 2


def test_danger_evicts_question_when_queue_is_full():
    d = director(capacity=1)
    d.offer(event("viewer_question", "question", 1), now=1)
    assert d.offer(event("game_danger", "danger", 19), now=19)
    assert d.propose(now=19).signal_id == "danger"
    assert d.metrics()["evicted"] == 1


def test_old_intent_cannot_complete_same_event_after_new_session():
    d = director()
    item = event("game_success", "shared", 10)
    assert d.offer(item, now=10)
    old = d.propose(now=10)
    d.disable()
    d.enable(owner_approved=True)
    assert d.offer(item, now=10)
    current = d.propose(now=10)
    assert old.session_epoch != current.session_epoch
    assert old.event_serial != current.event_serial
    assert not d.complete(old, now=10, spoken=True)
    assert d.complete(current, now=10, spoken=True)
    assert d.metrics()["completed"] == 1


def test_same_session_reoffer_cannot_be_completed_by_old_intent():
    d = director()
    item = event("game_success", "repeated", 10)
    assert d.offer(item, now=10)
    old = d.propose(now=10)
    assert d.complete(old, now=10, spoken=True)
    assert d.offer(item, now=10)
    current = d.propose(now=10)
    assert current.event_serial > old.event_serial
    assert not d.complete(old, now=10, spoken=False)
    assert d.complete(current, now=10, spoken=True)


def test_forged_serial_or_epoch_cannot_commit():
    d = director()
    assert d.offer(event("viewer_question", "q", 10), now=10)
    intent = d.propose(now=10)
    assert not d.complete(replace(intent, event_serial=0), now=10, spoken=True)
    assert not d.complete(replace(intent, session_epoch=0), now=10, spoken=True)
    assert not d.complete(replace(intent, context="fictional win"), now=10, spoken=True)
    assert d.complete(intent, now=10, spoken=True)


def test_expired_event_clears_serial_and_cannot_be_committed():
    d = director()
    d.offer(event("game_danger", "expired", 10), now=10)
    old = d.propose(now=10)
    assert not d.complete(old, now=13, spoken=True)
    d.offer(event("game_danger", "new", 13), now=13)
    assert d.propose(now=13).signal_id == "new"
    assert not d.complete(old, now=13, spoken=True)


def test_proposal_is_nonconsuming_and_can_be_used_later():
    d = director()
    d.offer(event("viewer_question", "q", 10), now=10)
    a = d.propose(now=10)
    b = d.propose(now=10)
    assert a == b
    assert d.complete(a, now=10, spoken=True)
    assert not d.complete(b, now=10, spoken=True)


def test_viewer_cooldown_still_isolates_one_viewer():
    d = director()
    d.offer(event("viewer_question", "a", 10, speaker="viewer-A"), now=10)
    assert d.complete(d.propose(now=10), now=10, spoken=True)
    d.offer(event("viewer_question", "b", 13, speaker="viewer-A"), now=13)
    d.offer(event("viewer_question", "c", 13, speaker="viewer-B"), now=13)
    assert d.propose(now=13).signal_id == "c"


def test_stage_prepares_aged_question_and_commits_only_after_real_audio():
    clock = lambda: 19.0
    stage = StarStage(clock=clock, director=StreamDirector(gap_seconds=0))
    stage.enable(owner_approved=True)
    assert stage.offer(event("viewer_question", "question", 1), now=1, moderated=True)
    assert stage.offer(event("game_success", "win", 19), now=19)
    plan = stage.prepare(now=19)
    assert plan and plan.kind == "viewer_question"
    assert stage.queue_audio(plan, now=19)
    assert stage.acknowledge_audible(plan, now=19)
    assert stage.finish(plan, now=19, played_to_end=True)
    assert stage.metrics()["director"]["completed"] == 1
    assert stage.metrics()["director"]["queued"] == 1


def test_stage_will_not_attach_verbal_success_claim_to_unverified_win():
    stage = StarStage(clock=lambda: 10)
    stage.enable(owner_approved=True)
    stage.offer(event("game_success", "win", 10, evidence="reported"), now=10)
    plan = stage.prepare(now=10)
    assert plan and plan.expression is None


def test_no_user_ids_or_chat_content_leak_in_metrics():
    d = director()
    d.offer(event("viewer_question", "viewer-secret", 10,
                  detail="private secret content 123"), now=10)
    metrics = str(d.metrics())
    assert "viewer-secret" not in metrics
    assert "private secret" not in metrics
    assert "viewer-A" not in metrics
