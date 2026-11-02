"""Offline cross-game handoff tests: no device input, audio, or broadcast."""
import pytest

from star.gameplay_skill_bank import GameplaySkillBank
from star.stream_director import StreamDirector, StreamSignal
from star.stream_episode import StreamEpisode
from star.stream_stage import StarStage


def stage() -> StarStage:
    result = StarStage(director=StreamDirector(gap_seconds=0), clock=lambda: 100)
    result.enable(owner_approved=True)
    return result


def game_event(ident: str, scope: str, at: float = 100) -> StreamSignal:
    return StreamSignal(ident, "game_success", at, "Checkpoint reached",
                        evidence="observed", game_scope=scope)


def test_current_host_game_prevents_old_game_reaction_without_handoff() -> None:
    s = stage()
    assert s.offer(game_event("old", "gameA"), now=100)
    # Prior behavior produced a joyous speech plan about game A even though
    # the trusted host explicitly reported game B was on screen.
    assert s.prepare(now=100, current_game_scope="gameB") is None
    assert s.metrics()["off_game_context"] == 1
    assert s.metrics()["director"]["queued"] == 0


def test_scene_handoff_purges_game_events_preserves_chat() -> None:
    s = stage()
    s.transition_game(game_scope="sceneA", owner_approved=True, now=100)
    assert s.offer(game_event("one", "sceneA"), now=100)
    assert s.offer(StreamSignal("chat", "viewer_question", 100, "How do I move?",
                                speaker_id="viewer-1"), now=100, moderated=True)
    s.transition_game(game_scope="sceneB", owner_approved=True, now=100.1)
    assert not s.offer(game_event("late", "sceneA", at=100), now=100.1)
    assert not s.offer(game_event("empty", "", at=100), now=100.1)
    assert s.offer(game_event("new", "sceneB", at=100), now=100.1)
    plan = s.prepare(now=100.1, current_game_scope="sceneB")
    assert plan is not None and plan.signal_id == "new"
    metrics = s.metrics()["director"]
    assert metrics["scene_dropped"] == 1
    assert metrics["off_scope_rejected"] == 2
    # The viewer's question survives even though gameplay context changes.
    assert metrics["queued"] == 2


def test_game_change_invalidates_prepared_speech_and_rig_token() -> None:
    s = stage()
    s.transition_game(game_scope="sceneA", owner_approved=True)
    assert s.offer(game_event("first", "sceneA"), now=100)
    first = s.prepare(now=100, current_game_scope="sceneA")
    assert first is not None
    s.transition_game(game_scope="sceneB", owner_approved=True, now=100.1)
    assert not s.prepared(first)
    assert not s.queue_audio(first, now=100.1)
    assert not s.finish(first, now=100.1)
    assert s.metrics()["director"]["queued"] == 0
    assert s.metrics()["abandoned"] == 1


def test_queued_audio_cannot_change_scene_without_physical_stop() -> None:
    s = stage()
    s.transition_game(game_scope="sceneA", owner_approved=True)
    assert s.offer(game_event("first", "sceneA"), now=100)
    first = s.prepare(now=100, current_game_scope="sceneA")
    assert first is not None and s.queue_audio(first, now=100)
    with pytest.raises(RuntimeError, match="stop and flush physical audio"):
        s.transition_game(game_scope="sceneB", owner_approved=True, now=100.1)
    assert s.metrics()["phase"] == "queued"
    s.transition_game(game_scope="sceneB", owner_approved=True,
                      audio_stopped_and_flushed=True, now=100.1)
    assert not s.acknowledge_audible(first, now=100.1)
    assert s.metrics()["phase"] == "idle"
    assert s.metrics()["director"]["completed"] == 0


def test_audible_audio_scene_change_requires_flush_and_does_not_claim_spoken() -> None:
    s = stage()
    s.transition_game(game_scope="sceneA", owner_approved=True)
    assert s.offer(game_event("first", "sceneA"), now=100)
    first = s.prepare(now=100, current_game_scope="sceneA")
    assert first is not None and s.queue_audio(first, now=100)
    assert s.acknowledge_audible(first, now=100)
    with pytest.raises(RuntimeError, match="stop and flush physical audio"):
        s.transition_game(game_scope="sceneB", owner_approved=True, now=100)
    s.transition_game(game_scope="sceneB", owner_approved=True,
                      audio_stopped_and_flushed=True, now=100.1)
    assert not s.current(first)
    assert not s.finish(first, now=100.2, played_to_end=True)
    assert s.metrics()["director"]["completed"] == 0


def test_no_game_scope_explicitly_blocks_game_reactions_and_rebind_resets_dedupe() -> None:
    s = stage()
    s.transition_game(game_scope="sceneA", owner_approved=True)
    assert s.offer(game_event("first", "sceneA"), now=100)
    first = s.prepare(now=100, current_game_scope="sceneA")
    assert first is not None and s.queue_audio(first, now=100)
    assert s.acknowledge_audible(first, now=100)
    assert s.finish(first, now=100, played_to_end=True)
    s.transition_game(game_scope="", owner_approved=True, now=100.1)
    assert not s.offer(game_event("blocked", "sceneA"), now=100.1)
    s.transition_game(game_scope="sceneA", owner_approved=True, now=100.2)
    # New game/round has new host attestation; duplicate story can be spoken.
    assert s.offer(game_event("newround", "sceneA"), now=100.2)


def test_handoff_requires_explicit_approved_host_and_valid_scope() -> None:
    s = stage()
    with pytest.raises(PermissionError):
        s.transition_game(game_scope="sceneA")
    with pytest.raises(ValueError):
        s.transition_game(game_scope="bad/path", owner_approved=True)
    with pytest.raises(TypeError):
        s.transition_game(game_scope="sceneA", owner_approved=True,
                          audio_stopped_and_flushed=1)
    s.disable()
    with pytest.raises(RuntimeError, match="disabled"):
        s.transition_game(game_scope="sceneA", owner_approved=True)


def test_episode_scope_is_bound_to_all_four_signed_fields() -> None:
    with GameplaySkillBank(practice_key=b"a" * 32, validation_key=b"b" * 32) as bank:
        def episode(version: str, situation: str) -> StreamEpisode:
            return StreamEpisode(bank, game_id="Arena", game_version=version,
                                 objective_id="win", situation_id=situation)
        a, b, c = episode("v1", "map1"), episode("v2", "map1"), episode("v1", "map2")
        assert a.game_scope == episode("v1", "map1").game_scope
        assert len({a.game_scope, b.game_scope, c.game_scope}) == 3
        assert len(a.game_scope) < 64
        assert a.game_scope.startswith("episode.")
