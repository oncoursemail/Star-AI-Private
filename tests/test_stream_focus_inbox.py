"""Offline checks for consent-gated, bounded post-game chat follow-ups."""
import pytest

from star.stream_director import StreamDirector, StreamSignal
from star.stream_focus_inbox import StreamFocusInbox


def question(ident="q1", speaker="viewerA", at=100.0, text="How did that jump work?"):
    return StreamSignal(
        signal_id=ident, kind="viewer_question", timestamp=at,
        detail=text, speaker_id=speaker, evidence="reported",
    )


def ready(inbox=None):
    inbox = inbox or StreamFocusInbox()
    inbox.enable(owner_approved=True, moderated_chat_retention_approved=True)
    inbox.update_focus(gameplay_critical=True, now=100)
    return inbox


def director(*, max_events=48):
    result = StreamDirector(max_events=max_events)
    result.enable(owner_approved=True)
    return result


def test_off_by_default_and_both_chat_retention_permissions_are_required():
    inbox = StreamFocusInbox()
    assert inbox.metrics()["enabled"] is False
    assert not inbox.update_focus(gameplay_critical=True, now=100)
    assert not inbox.capture(question(), now=100, moderated=True)
    for kwargs in ({}, {"owner_approved": True},
                   {"moderated_chat_retention_approved": True}):
        with pytest.raises(PermissionError):
            inbox.enable(**kwargs)
    inbox.enable(owner_approved=True, moderated_chat_retention_approved=True)
    with pytest.raises(RuntimeError):
        inbox.enable(owner_approved=True, moderated_chat_retention_approved=True)


def test_question_survives_directors_short_ttl_then_is_offered_as_old_chat():
    inbox = StreamFocusInbox(max_age_seconds=120)
    inbox = ready(inbox)
    stage = director()
    assert inbox.capture(question(), now=100, moderated=True)
    assert not inbox.release_one(stage, now=140)
    assert inbox.update_focus(gameplay_critical=False, now=165) is False
    assert inbox.release_one(stage, now=165)
    proposed = stage.propose(now=165)
    assert proposed is not None
    assert proposed.untrusted_context is True
    assert proposed.kind == "viewer_question"
    assert proposed.evidence == "reported"
    assert "asked 65s ago during gameplay" in proposed.context
    assert "How did that jump work?" in proposed.context
    assert proposed.deadline_at == 200
    # A queued signal isn't evidence that speech played.
    assert stage.metrics()["completed"] == 0
    assert stage.complete(proposed, now=165.1, spoken=True)
    assert inbox.metrics()["released"] == 1
    assert inbox.metrics()["queued"] == 0


def test_gameplay_critical_is_checked_again_at_release():
    inbox = ready()
    stage = director()
    assert inbox.capture(question(), now=100, moderated=True)
    inbox.update_focus(gameplay_critical=False, now=102)
    assert not inbox.release_one(stage, now=102, gameplay_critical=True)
    assert inbox.metrics()["queued"] == 1
    assert inbox.release_one(stage, now=102, gameplay_critical=False)


def test_stale_question_is_expired_not_revived_by_new_offer_timestamp():
    inbox = ready(StreamFocusInbox(max_age_seconds=30))
    stage = director()
    assert inbox.capture(question(), now=100, moderated=True)
    inbox.update_focus(gameplay_critical=False, now=130.01)
    assert not inbox.release_one(stage, now=130.01)
    assert inbox.metrics()["expired"] == 1
    assert stage.metrics()["queued"] == 0


def test_queue_is_tiny_fifo_and_prevents_one_speaker_monopolizing_it():
    inbox = ready(StreamFocusInbox(max_questions=2))
    stage = director()
    assert inbox.capture(question("first", "A"), now=100, moderated=True)
    assert not inbox.capture(question("second", "A", text="Another question?"),
                             now=100, moderated=True)
    assert not inbox.capture(question("again", "B"), now=100, moderated=True)
    # The same text from a different speaker is still a duplicate.
    assert inbox.capture(question("q2", "B", text="Which key was that?"),
                         now=100, moderated=True)
    assert not inbox.capture(question("q3", "C", text="Do you remember that?"),
                             now=100, moderated=True)
    inbox.update_focus(gameplay_critical=False, now=103)
    assert inbox.release_one(stage, now=103)
    one = stage.propose(now=103)
    assert one is not None and "How did that jump work?" in one.context
    assert one.untrusted_context
    assert one.signal_id.startswith("focus_")
    assert stage.complete(one, now=103, spoken=True)
    assert inbox.release_one(stage, now=104)
    two = stage.propose(now=106)
    assert two is not None and "Which key was that?" in two.context
    assert one.signal_id != two.signal_id
    assert two.context != one.context
    assert inbox.metrics()["queued"] == 0


def test_busy_director_preserves_question_until_it_can_accept():
    inbox = ready()
    stage = director(max_events=1)
    assert inbox.capture(question(), now=100, moderated=True)
    inbox.update_focus(gameplay_critical=False, now=101)
    assert stage.offer(StreamSignal(
        "urgent", "game_danger", 101, "Observed wall", evidence="observed"
    ), now=101)
    assert not inbox.release_one(stage, now=101)
    assert inbox.metrics()["queued"] == 1
    urgent = stage.propose(now=101)
    assert urgent is not None and urgent.kind == "game_danger"
    assert stage.complete(urgent, now=101.5, spoken=True)
    assert inbox.release_one(stage, now=102)
    assert inbox.metrics()["released"] == 1


def test_existing_speaking_and_viewer_turn_gates_still_apply():
    inbox = ready()
    stage = director()
    assert inbox.capture(question(), now=100, moderated=True)
    inbox.update_focus(gameplay_critical=False, now=101)
    assert inbox.release_one(stage, now=101)
    assert stage.propose(now=101, voice_speaking=True) is None
    assert stage.propose(now=101, viewer_speaking=True) is None
    assert stage.propose(now=101, gameplay_critical=True) is None
    assert stage.propose(now=101) is not None


def test_replay_and_reset_do_not_revive_stale_questions_or_identifiers():
    inbox = ready()
    stage = director()
    assert inbox.capture(question(), now=100, moderated=True)
    inbox.update_focus(gameplay_critical=False, now=101)
    assert inbox.release_one(stage, now=101)
    inbox.update_focus(gameplay_critical=True, now=101.1)
    assert not inbox.capture(question(), now=101.1, moderated=True)
    inbox.disable()
    assert not inbox.release_one(stage, now=101.2)
    assert inbox.metrics()["queued"] == 0
    inbox.enable(owner_approved=True, moderated_chat_retention_approved=True)
    inbox.update_focus(gameplay_critical=True, now=200)
    assert inbox.capture(question("q1", at=200), now=200, moderated=True)
    inbox.update_focus(gameplay_critical=False, now=201)
    assert inbox.release_one(stage, now=201)
    fresh = stage.propose(now=201)
    assert fresh is not None
    assert fresh.signal_id != "focus_1_1"


def test_invalid_or_unverified_source_never_queued():
    inbox = ready()
    assert not inbox.capture(question(), now=100)
    assert not inbox.capture(question(at=94), now=100, moderated=True)
    assert not inbox.capture(question(at=100.5), now=100, moderated=True)
    assert not inbox.capture(StreamSignal(
        "danger", "game_danger", 100, "Danger", evidence="observed"
    ), now=100, moderated=True)
    assert not inbox.capture(StreamSignal(
        "q2", "viewer_question", 100, "Question?", evidence="unknown"
    ), now=100, moderated=True)
    assert not inbox.capture(question(text="X" * 351), now=100, moderated=True)
    assert inbox.metrics()["queued"] == 0


@pytest.mark.parametrize("bad", [True, False, float("nan"), float("inf"), -1.0, "0"])
def test_reject_invalid_clock(bad):
    inbox = ready()
    with pytest.raises(ValueError):
        inbox.update_focus(gameplay_critical=False, now=bad)


def test_backward_monotonic_time_is_not_accepted():
    inbox = ready()
    inbox.update_focus(gameplay_critical=True, now=105)
    with pytest.raises(ValueError, match="backwards"):
        inbox.capture(question(at=100), now=104, moderated=True)


def test_bad_configuration_and_trust_types_fail():
    for kwargs in ({"max_questions": True}, {"max_questions": 9},
                   {"max_questions": 0}, {"max_age_seconds": 10},
                   {"max_age_seconds": float("nan")}):
        with pytest.raises(ValueError):
            StreamFocusInbox(**kwargs)
    inbox = ready()
    with pytest.raises(TypeError):
        inbox.capture(object(), now=100, moderated=True)
    with pytest.raises(TypeError):
        inbox.capture(question(), now=100, moderated=1)
    with pytest.raises(TypeError):
        inbox.update_focus(gameplay_critical=1, now=100)
    with pytest.raises(TypeError):
        inbox.release_one(object(), now=100)
    with pytest.raises(TypeError):
        inbox.release_one(director(), now=100, gameplay_critical=1)


def test_metrics_never_expose_chat_viewer_identity_or_question_text():
    inbox = ready()
    assert inbox.capture(question(speaker="private_viewer_name",
                                  text="my sensitive question 123"),
                         now=100, moderated=True)
    metrics = repr(inbox.metrics())
    assert "private_viewer_name" not in metrics
    assert "sensitive question" not in metrics
    stage = director()
    inbox.update_focus(gameplay_critical=False, now=101)
    assert inbox.release_one(stage, now=101)
    event = stage.propose(now=101)
    assert event is not None
    assert event.untrusted_context is True
    assert "private_viewer_name" not in event.context
    assert "private_viewer_name" not in event.signal_id
    assert "sensitive question" in event.context


def test_missing_stable_viewer_identity_cannot_bypass_one_speaker_limit():
    """Unique event IDs are not a replacement for a stable, moderated speaker."""
    inbox = ready()
    assert not inbox.capture(question("anon-1", speaker="", text="First?"),
                             now=100, moderated=True)
    assert not inbox.capture(question("anon-2", speaker="", text="Second?"),
                             now=100, moderated=True)
    assert not inbox.capture(question("blank", speaker="  \t", text="Third?"),
                             now=100, moderated=True)
    assert inbox.metrics()["queued"] == 0
    assert inbox.metrics()["declined"] == 3

    # The trusted chat host supplies a stable ID (not a display nickname).
    assert inbox.capture(question("stable-1", speaker="platform-user-17",
                                  text="First valid question?"),
                         now=100, moderated=True)
    assert not inbox.capture(question("stable-2", speaker="platform-user-17",
                                      text="Another unique question?"),
                             now=100, moderated=True)
    assert inbox.metrics()["queued"] == 1
    stage = director()
    inbox.update_focus(gameplay_critical=False, now=101)
    assert inbox.release_one(stage, now=101)
    proposal = stage.propose(now=101)
    assert proposal is not None
    assert "First valid question?" in proposal.context
    assert "platform-user-17" not in proposal.context
    assert "platform-user-17" not in proposal.signal_id


def test_noncanonical_viewer_ids_cannot_multiply_deferred_question_slots():
    inbox = ready()
    assert not inbox.capture(question("space-leading", speaker=" viewerA", text="First?"),
                             now=100, moderated=True)
    assert not inbox.capture(question("space-trailing", speaker="viewerA ", text="Second?"),
                             now=100, moderated=True)
    assert not inbox.capture(question("unicode", speaker="viewеrA", text="Third?"),
                             now=100, moderated=True)
    assert not inbox.capture(question("control", speaker="viewerA\x00", text="Fourth?"),
                             now=100, moderated=True)
    assert inbox.metrics()["queued"] == 0
    assert inbox.capture(question("canonical", speaker="viewerA", text="Accepted?"),
                         now=100, moderated=True)
    assert not inbox.capture(question("duplicate", speaker="viewerA", text="More?"),
                             now=100, moderated=True)
    assert inbox.metrics()["queued"] == 1
