"""Offline checks for host-scoped, public-consent-gated Star VTuber memories.

These never call an AI, livestream, read viewer chat, or claim independent
gameplay verification. The journal's host attestation is not a signature.
"""
from __future__ import annotations

import pytest

from star.stream_director import StreamSignal
from star.stream_episode_journal import GameMoment, StreamEpisodeJournal
from star.stream_stage import StarStage


def journal_with_moments() -> StreamEpisodeJournal:
    journal = StreamEpisodeJournal()
    journal.enable(owner_approved=True)
    assert journal.record(
        GameMoment("event_1", "obby_v1", "checkpoint", 100.0, "bridge_1"),
        now_s=100, host_observed=True,
    )
    assert journal.record(
        GameMoment("event_2", "arena_v1", "win", 100.0, "arena_3"),
        now_s=100, host_observed=True,
    )
    return journal


def stage_for(kind: str = "viewer_question") -> StarStage:
    stage = StarStage(clock=lambda: 100.0)
    stage.enable(owner_approved=True)
    signal = StreamSignal(
        signal_id="question_1", kind=kind, timestamp=100.0,
        detail="What happened on that bridge?",
        speaker_id="viewer_42" if kind.startswith("viewer") else "",
        evidence="unknown" if kind.startswith("viewer") else "observed",
        game_scope="obby_v1" if kind.startswith("game_") else "",
    )
    assert stage.offer(signal, now=100, moderated=True)
    return stage


def test_observed_memory_is_only_offered_on_approved_viewer_question():
    journal = journal_with_moments()
    stage = stage_for()
    without_consent = stage.prepare(
        now=100, journal=journal, current_game_scope="obby_v1",
    )
    assert without_consent is not None
    assert "reached a checkpoint" not in without_consent.context_record

    approved = stage_for().prepare(
        now=100, journal=journal, current_game_scope="obby_v1",
        episode_broadcast_approved=True,
    )
    assert approved is not None
    assert "reached a checkpoint" in approved.context_record
    assert "bridge_1" in approved.context_record
    assert "host-attested" in approved.context_record.lower()
    assert "not signed" in approved.context_record.lower()
    assert "[END STAR SESSION GAME MOMENTS]" in approved.context_record
    assert approved.kind == "viewer_question"
    # A memory record never commits a spoken outcome or starts playback.
    assert stage.metrics()["director"]["completed"] == 0


def test_recall_remains_scoped_to_host_selected_game():
    journal = journal_with_moments()
    plan = stage_for().prepare(
        now=100, journal=journal, current_game_scope="obby_v1",
        episode_broadcast_approved=True,
    )
    assert plan is not None
    assert "obby_v1" in plan.context_record
    assert "arena_v1" not in plan.context_record
    assert "arena_3" not in plan.context_record


def test_game_events_and_viewer_chatter_cannot_trigger_personal_stories():
    journal = journal_with_moments()
    for kind in ("game_success", "game_observation", "viewer_comment"):
        plan = stage_for(kind).prepare(
            now=100, journal=journal, current_game_scope="obby_v1",
            episode_broadcast_approved=True,
        )
        assert plan is not None
        assert "STAR SESSION GAME MOMENTS" not in plan.context_record
        assert "reached a checkpoint" not in plan.context_record


def test_disabled_journal_cannot_be_recalled_after_session_end():
    journal = journal_with_moments()
    journal.disable()
    plan = stage_for().prepare(
        now=100, journal=journal, current_game_scope="obby_v1",
        episode_broadcast_approved=True,
    )
    assert plan is not None
    assert "STAR SESSION GAME MOMENTS" not in plan.context_record


def test_invalid_scope_and_consent_types_fail_closed():
    journal = journal_with_moments()
    for scope in ("../../etc", "bad game", "x" * 65, None, 10):
        with pytest.raises(ValueError):
            stage_for().prepare(
                now=100, journal=journal, current_game_scope=scope,
                episode_broadcast_approved=True,
            )
    with pytest.raises(TypeError):
        stage_for().prepare(
            now=100, journal=journal, current_game_scope="obby_v1",
            episode_broadcast_approved=1,
        )
    with pytest.raises(TypeError):
        stage_for().prepare(
            now=100, journal=object(), current_game_scope="obby_v1",
            episode_broadcast_approved=True,
        )


def test_critical_gameplay_does_not_inject_memories_or_force_speech():
    journal = journal_with_moments()
    stage = stage_for()
    assert stage.prepare(
        now=100, journal=journal, current_game_scope="obby_v1",
        episode_broadcast_approved=True, gameplay_critical=True,
    ) is None


def test_no_gameplay_evidence_means_no_memory_even_with_public_consent():
    journal = StreamEpisodeJournal()
    journal.enable(owner_approved=True)
    # A chat-like claim is not a trusted game-state observation.
    assert not journal.record(
        GameMoment("claim_1", "obby_v1", "win", 100.0),
        now_s=100, host_observed=False,
    )
    plan = stage_for().prepare(
        now=100, journal=journal, current_game_scope="obby_v1",
        episode_broadcast_approved=True,
    )
    assert plan is not None
    assert "STAR SESSION GAME MOMENTS" not in plan.context_record
