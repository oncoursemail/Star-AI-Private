"""Offline tests only. Synthetic events are NOT gameplay or streamer performance evidence."""
import pytest
from star.streamer_director import StreamEvent, StreamerDirector, MAX_QUEUE


def ev(n, kind="game_win", ms=1000, source="verified_game", evidence_id=None, moderated=False):
    return StreamEvent(f"event-{n}", kind, source, ms, evidence_id or f"proof-{n}", moderated)


def active():
    d = StreamerDirector()
    d.set_enabled(True, owner_confirmed=True)
    return d


def test_off_by_default_requires_human_confirmation():
    d = StreamerDirector()
    assert d.enabled is False
    with pytest.raises(PermissionError):
        d.set_enabled(True)
    assert not d.ingest(ev(1), now_ms=1000)
    assert d.next_cue(now_ms=1000) is None


def test_verified_win_yields_intent_not_unfounded_spoken_dialogue():
    d = active()
    assert d.ingest(ev(1), now_ms=1000)
    c = d.next_cue(now_ms=1000)
    assert (c.intent, c.animation, c.expression, c.should_speak) == (
        "celebrate_verified_win", "cheer", "happy", True)
    assert "won" not in str(c) and "viewer" not in str(c)
    assert d.next_cue(now_ms=1000) is None


def test_ignores_duplicates_wrong_source_missing_evidence_and_old_events():
    d = active()
    assert d.ingest(ev(1), now_ms=1000)
    assert not d.ingest(ev(1), now_ms=1000)
    assert not d.ingest(ev(2, source="owner_ui"), now_ms=1000)
    assert not d.ingest(ev(3, evidence_id="!!"), now_ms=1000)
    assert not d.ingest(ev(4, ms=1000), now_ms=20000)
    assert not d.ingest(ev(5, ms=3000), now_ms=1000)
    assert d.stats()["rejected"] == 5


def test_chat_must_be_moderated_and_never_contains_untrusted_text():
    d = active()
    assert not d.ingest(ev(1, "chat_question", source="moderated_chat"), now_ms=1000)
    assert d.ingest(ev(2, "chat_question", source="moderated_chat", moderated=True), now_ms=1000)
    cue = d.next_cue(now_ms=1000)
    assert cue.intent == "consider_moderated_viewer_question"
    assert not hasattr(cue, "text")
    assert not hasattr(StreamEvent, "command")


def test_game_hazard_is_visual_reaction_when_voice_busy():
    d = active()
    assert d.ingest(ev(1, "game_hazard"), now_ms=1000)
    cue = d.next_cue(now_ms=1000, voice_busy=True, intense_gameplay=True)
    assert cue.expression == "surprised" and cue.should_speak is False


def test_speech_defers_during_gameplay_and_voice_busy():
    d = active()
    d.ingest(ev(1), now_ms=1000)
    assert d.next_cue(now_ms=1000, intense_gameplay=True) is None
    assert d.next_cue(now_ms=1100, voice_busy=True) is None
    assert d.next_cue(now_ms=1200).intent == "celebrate_verified_win"


def test_anti_spam_global_and_per_kind_cooldowns():
    d = active()
    assert d.ingest(ev(1), now_ms=1000)
    assert d.next_cue(now_ms=1000) is not None
    d.ingest(ev(2, "game_loss", ms=1100), now_ms=1100)
    d.ingest(ev(3, ms=1100), now_ms=1100)
    assert d.next_cue(now_ms=1500) is None
    assert d.next_cue(now_ms=6000).intent == "reflect_on_verified_loss"
    assert d.next_cue(now_ms=7000) is None
    assert d.next_cue(now_ms=11000).intent == "celebrate_verified_win"


def test_queue_bounded_and_high_priority_replaces_low():
    d = active()
    for i in range(MAX_QUEUE):
        assert d.ingest(ev(i, "chat_cheer", source="moderated_chat", moderated=True), now_ms=1000)
    assert len(d._queue) == MAX_QUEUE
    assert d.ingest(ev(100, "game_win"), now_ms=1000)
    assert len(d._queue) == MAX_QUEUE and d.dropped == 1
    assert d.next_cue(now_ms=1000).intent == "celebrate_verified_win"
    assert d.ingest(ev(101, "chat_cheer", source="moderated_chat", moderated=True), now_ms=1000)


def test_old_items_expire_silently():
    d = active()
    d.ingest(ev(1, ms=1000), now_ms=1000)
    assert d.next_cue(now_ms=14000) is None
    assert d.stats()["dropped"] == 1


def test_emergency_stop_preempts_and_clears_queue_without_actions():
    d = active()
    d.ingest(ev(1), now_ms=1000)
    assert d.ingest(ev(2, "owner_stop", source="owner_ui"), now_ms=1000)
    cue = d.next_cue(now_ms=1000)
    assert cue.kind == "stop" and cue.should_speak is False and d.enabled is False
    assert d.stats()["queued"] == 0
    assert d.next_cue(now_ms=1001) is None


def test_disabling_is_silent_and_reenable_requires_new_confirmation():
    d = active()
    d.ingest(ev(1), now_ms=1000)
    d.set_enabled(False)
    assert d.next_cue(now_ms=1000) is None
    with pytest.raises(PermissionError):
        d.set_enabled(True)
    d.set_enabled(True, owner_confirmed=True)
    assert d.next_cue(now_ms=1000) is None


def test_invalid_times_and_types_rejected():
    d = active()
    with pytest.raises(ValueError):
        d.ingest(ev(1), now_ms=-1)
    with pytest.raises(ValueError):
        d.next_cue(now_ms=-1)
    with pytest.raises(ValueError):
        d.set_enabled(1, owner_confirmed=True)
    assert not d.ingest(StreamEvent("bad", "game_win", "verified_game", True, "proof"), now_ms=1000)
