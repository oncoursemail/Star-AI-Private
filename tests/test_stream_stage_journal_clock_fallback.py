"""Offline checks that optional game memories cannot break live speech scheduling.

Host-attested facts are not cryptographic evidence of gameplay. These tests do
not synthesize voice, control a game, or connect to OBS.
"""
from __future__ import annotations

from star.stream_director import StreamSignal
from star.stream_episode_journal import GameMoment, StreamEpisodeJournal
from star.stream_stage import StarStage


def stage_at(now: float) -> StarStage:
    stage = StarStage(clock=lambda: now)
    stage.enable(owner_approved=True)
    assert stage.offer(
        StreamSignal(
            signal_id="question_1", kind="viewer_question", timestamp=now,
            detail="Did you reach the checkpoint?", speaker_id="viewer_1",
        ),
        now=now, moderated=True,
    )
    return stage


def journal_at(now: float) -> StreamEpisodeJournal:
    journal = StreamEpisodeJournal()
    journal.enable(owner_approved=True)
    assert journal.record(
        GameMoment("moment_1", "obby_v1", "checkpoint", now, "bridge_1"),
        now_s=now, host_observed=True,
    )
    return journal


def test_clock_mismatch_skips_optional_memory_without_losing_viewer_turn():
    journal = journal_at(200.0)
    stage = stage_at(100.0)
    plan = stage.prepare(
        now=100.0, journal=journal, current_game_scope="obby_v1",
        episode_broadcast_approved=True,
    )
    assert plan is not None
    assert plan.kind == "viewer_question"
    assert "STAR SESSION GAME MOMENTS" not in plan.context_record
    assert stage.metrics()["journal_recall_skipped"] == 1
    assert stage.queue_audio(plan, now=100.1)
    assert stage.acknowledge_audible(plan, now=100.2)
    assert stage.finish(plan, now=100.3, played_to_end=True)
    assert stage.metrics()["director"]["completed"] == 1
    # A failed optional read must not erase the independently stored fact.
    assert journal.recall(now_s=200.0, game_scope="obby_v1")


def test_recall_works_normally_when_host_clock_catches_up():
    journal = journal_at(200.0)
    stage = stage_at(201.0)
    plan = stage.prepare(
        now=201.0, journal=journal, current_game_scope="obby_v1",
        episode_broadcast_approved=True,
    )
    assert plan is not None
    assert "reached a checkpoint" in plan.context_record
    assert stage.metrics()["journal_recall_skipped"] == 0


def test_no_memories_are_injected_without_public_speaking_approval():
    journal = journal_at(200.0)
    stage = stage_at(100.0)
    plan = stage.prepare(
        now=100.0, journal=journal, current_game_scope="obby_v1",
        episode_broadcast_approved=False,
    )
    assert plan is not None
    assert "STAR SESSION GAME MOMENTS" not in plan.context_record
    assert stage.metrics()["journal_recall_skipped"] == 0
