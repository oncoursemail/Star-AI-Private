"""Offline STAR Creator Studio contracts: fake data is not an authenticated stream."""
import pytest

from star.streamer_creator import (
    BroadcastPlan, ChatAttention, ChatCandidate, PlatformScene, StoryFact,
    validate_scenes, CHAT_RESPONSE_COOLDOWN_MS, MAX_CHAT_QUEUE,
)


def message(n, platform="twitch", text="Can you show that level again?", now=2000,
            moderated=True):
    return ChatCandidate(platform, f"message-{n}", now, text, moderated)


def test_chat_keeps_focus_on_game_even_with_moderated_questions():
    c = ChatAttention()
    assert c.ingest(message(1), now_ms=2000)
    assert c.select(now_ms=2001, mode="focus") is None
    assert c.select(now_ms=2001, mode="chat", game_urgency=0.8) is None
    answer = c.select(now_ms=2002, mode="chat", game_urgency=0.1)
    assert answer.question.endswith("?")
    assert answer.platform == "twitch"


def test_unmoderated_duplicate_stale_and_unknown_chat_rejected():
    c = ChatAttention()
    assert not c.ingest(message(1, moderated=False), now_ms=2000)
    assert not c.ingest(message(2, platform="example"), now_ms=2000)
    assert not c.ingest(message(3, now=0), now_ms=100000)
    assert c.ingest(message(4), now_ms=2000)
    assert not c.ingest(message(4), now_ms=2000)
    assert c.queued() == 1


def test_chat_scheduler_fairness_questions_first_then_another_platform():
    c = ChatAttention()
    c.ingest(message(1, text="hello"), now_ms=2000)
    c.ingest(message(2, text="First question?"), now_ms=2000)
    c.ingest(message(3, platform="youtube", text="Second question?"), now_ms=2000)
    result = c.select(now_ms=2001, mode="chat")
    assert result.message_id == "message-2"
    assert c.select(now_ms=2002, mode="chat") is None
    assert c.select(now_ms=2001 + CHAT_RESPONSE_COOLDOWN_MS, mode="chat").platform == "youtube"


def test_chat_queue_is_bounded_no_identifying_information():
    c = ChatAttention()
    for i in range(MAX_CHAT_QUEUE + 9):
        assert c.ingest(message(i), now_ms=2000)
    assert c.queued() == MAX_CHAT_QUEUE
    result = c.select(now_ms=2000, mode="chat")
    assert result.message_id == "message-9"
    assert not hasattr(result, "user_id")
    assert not hasattr(result, "authorization")


def test_chat_expiry_and_reset():
    c = ChatAttention()
    assert c.ingest(message(1), now_ms=2000)
    assert c.select(now_ms=92001, mode="chat") is None
    c.reset()
    assert c.queued() == 0
    assert c.ingest(message(1), now_ms=2000)


def test_chat_validates_clock_urgency_mode_text_length():
    c = ChatAttention()
    with pytest.raises(ValueError):
        c.ingest(message(1), now_ms=-1)
    with pytest.raises(ValueError):
        c.select(now_ms=0, mode="not-a-mode")
    with pytest.raises(ValueError):
        c.select(now_ms=0, mode="chat", game_urgency=2)
    assert not c.ingest(message(2, text="x" * 301), now_ms=2000)


def test_twitch_scene_rejects_chat_from_other_platforms():
    with pytest.raises(ValueError, match="other platforms"):
        validate_scenes((PlatformScene("twitch", ("twitch", "youtube")),))
    with pytest.raises(ValueError, match="redirect"):
        validate_scenes((PlatformScene("twitch", ("twitch",), True),))
    validate_scenes((PlatformScene("twitch", ("twitch",)), PlatformScene("youtube", ("youtube",))))


def test_duplicate_or_invalid_output_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        validate_scenes((PlatformScene("youtube"), PlatformScene("youtube")))
    with pytest.raises(ValueError):
        validate_scenes((PlatformScene("unknown"),))
    with pytest.raises(ValueError):
        validate_scenes(())


def test_public_broadcast_never_autostarts_and_requires_real_owner_preflight():
    broadcast = BroadcastPlan()
    assert broadcast.state == "offline"
    with pytest.raises(PermissionError):
        broadcast.preview((PlatformScene("twitch"),), owner_confirmed=False)
    broadcast.preview((PlatformScene("twitch"),), owner_confirmed=True)
    assert broadcast.state == "preview"
    with pytest.raises(PermissionError):
        broadcast.authorize_live_intent(owner_confirmed=True)
    with pytest.raises(PermissionError):
        broadcast.mark_preflight(host_verified=False, owner_confirmed=True)
    broadcast.mark_preflight(host_verified=True, owner_confirmed=True)
    with pytest.raises(PermissionError):
        broadcast.authorize_live_intent(owner_confirmed=False)
    broadcast.authorize_live_intent(owner_confirmed=True)
    assert broadcast.state == "live_intent"  # NOT an OBS go-live
    broadcast.stop()
    assert broadcast.state == "offline" and broadcast.scenes == ()
    assert BroadcastPlan().state == "offline"  # reboot recovery remains offline


def test_lore_remains_explicitly_fictional_or_evidenced():
    fiction = StoryFact("Star found her Observatory in a fictional forest", "fiction", True)
    assert fiction.labeled().startswith("Fictional")
    real = StoryFact("Star passed the test level", "observed", True, "verified-game-7")
    assert real.labeled().startswith("Previously verified")
    with pytest.raises(ValueError, match="verified evidence"):
        StoryFact("I beat a boss yesterday", "observed", True)
    with pytest.raises(ValueError, match="approved"):
        StoryFact("Original universe", "fiction", False)
    with pytest.raises(ValueError, match="Fiction"):
        StoryFact("My origin lore", "fiction", True, "fake-evidence")
