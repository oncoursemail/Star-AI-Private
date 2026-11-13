import pytest

from star.voice.room import (
    CueIntent,
    CueSource,
    RoomAction,
    RoomCue,
    RoomPolicyConfig,
    RoomTurnDirector,
)


def cue(event_id="e1", *, source=CueSource.AUDIO, intent=CueIntent.DIRECT_QUESTION,
        addressed=True, confidence=0.98, started=9.0, ended=9.5, overlap=0,
        urgency=0.0, final=True):
    return RoomCue(event_id, "speaker-1", source, intent, addressed, confidence,
                   started, ended, overlap, urgency, final)


def test_direct_question_is_answered_when_idle():
    d = RoomTurnDirector()
    result = d.decide(cue(), now=10.0)
    assert result.action is RoomAction.RESPOND
    assert result.reason == "directed_to_star"


def test_backchannel_does_not_interrupt_active_speech():
    d = RoomTurnDirector()
    d.set_assistant_playback(True, "response-7")
    result = d.decide(cue(intent=CueIntent.BACKCHANNEL), now=10.0)
    assert result.action is RoomAction.CONTINUE
    assert result.cancel_response_id is None


def test_side_conversation_is_ignored_when_idle():
    result = RoomTurnDirector().decide(cue(intent=CueIntent.SIDE_CONVERSATION), now=10.0)
    assert result.action is RoomAction.IGNORE


def test_direct_question_is_queued_during_speech_without_strong_barge_in():
    d = RoomTurnDirector()
    d.set_assistant_playback(True, "response-8")
    result = d.decide(cue(overlap=100), now=10.0)
    assert result.action is RoomAction.QUEUE
    assert result.cancel_response_id is None


def test_high_confidence_audio_barge_in_cancels_only_current_response_id():
    d = RoomTurnDirector()
    d.set_assistant_playback(True, "response-9")
    result = d.decide(cue(overlap=320), now=10.0)
    assert result.action is RoomAction.INTERRUPT
    assert result.cancel_response_id == "response-9"


def test_chat_mention_queues_but_never_uses_audio_barge_in():
    d = RoomTurnDirector()
    d.set_assistant_playback(True, "response-10")
    result = d.decide(cue(source=CueSource.CHAT, overlap=500), now=10.0)
    assert result.action is RoomAction.QUEUE
    assert result.cancel_response_id is None


def test_correction_can_interrupt_when_directed_and_confident():
    d = RoomTurnDirector()
    d.set_assistant_playback(True, "response-11")
    result = d.decide(cue(intent=CueIntent.CORRECTION, overlap=300), now=10.0)
    assert result.action is RoomAction.INTERRUPT
    assert result.priority == 100


def test_partial_cue_waits_without_consuming_event_id():
    d = RoomTurnDirector()
    partial = cue(final=False)
    assert d.decide(partial, now=10.0).action is RoomAction.WAIT
    final = cue(final=True)
    assert d.decide(final, now=10.0).action is RoomAction.RESPOND


def test_duplicate_final_cue_is_ignored():
    d = RoomTurnDirector()
    assert d.decide(cue(), now=10.0).action is RoomAction.RESPOND
    duplicate = d.decide(cue(), now=10.0)
    assert duplicate.action is RoomAction.IGNORE
    assert duplicate.reason == "duplicate_event"


def test_low_confidence_cue_waits_and_is_deduplicated():
    d = RoomTurnDirector()
    low = cue(confidence=0.2)
    assert d.decide(low, now=10.0).reason == "low_classification_confidence"
    assert d.decide(low, now=10.0).reason == "duplicate_event"


def test_stale_and_future_cues_fail_closed():
    d = RoomTurnDirector(RoomPolicyConfig(max_event_age_seconds=8.0))
    assert d.decide(cue(ended=1.0, started=0.5), now=10.0).reason == "stale_event"
    assert d.decide(cue("future", ended=20.0, started=19.0), now=10.0).reason == "future_timestamp"


def test_unaddressed_direct_question_does_not_steal_the_floor():
    d = RoomTurnDirector()
    d.set_assistant_playback(True, "response-12")
    result = d.decide(cue(addressed=False, overlap=600), now=10.0)
    assert result.action is RoomAction.CONTINUE


def test_unknown_intent_waits_when_idle():
    result = RoomTurnDirector().decide(cue(intent=CueIntent.UNKNOWN), now=10.0)
    assert result.action is RoomAction.WAIT


def test_low_urgency_game_event_is_not_spoken():
    result = RoomTurnDirector().decide(
        cue(source=CueSource.GAME, intent=CueIntent.GAME_EVENT, addressed=False, urgency=0.4), now=10.0
    )
    assert result.action is RoomAction.IGNORE


def test_high_urgency_game_event_is_spoken_or_queued():
    d = RoomTurnDirector()
    high = cue(source=CueSource.GAME, intent=CueIntent.GAME_EVENT, addressed=False, urgency=0.95)
    assert d.decide(high, now=10.0).action is RoomAction.RESPOND
    d.set_assistant_playback(True, "response-13")
    queued = d.decide(cue("game-2", source=CueSource.GAME, intent=CueIntent.GAME_EVENT,
                          addressed=False, urgency=0.95), now=10.0)
    assert queued.action is RoomAction.QUEUE


def test_game_event_from_non_game_source_is_ignored():
    result = RoomTurnDirector().decide(
        cue(intent=CueIntent.GAME_EVENT, source=CueSource.AUDIO, urgency=0.99), now=10.0
    )
    assert result.reason == "game_event_below_reaction_threshold"


def test_dedupe_memory_is_bounded_and_old_ids_expire():
    d = RoomTurnDirector(RoomPolicyConfig(dedupe_capacity=2))
    for event_id in ("a", "b", "c"):
        d.decide(cue(event_id), now=10.0)
    assert d.decide(cue("a"), now=10.0).action is RoomAction.RESPOND


def test_session_reset_clears_playback_and_dedupe():
    d = RoomTurnDirector()
    d.set_assistant_playback(True, "response-14")
    d.decide(cue(), now=10.0)
    d.reset_session()
    assert not d.assistant_speaking
    assert d.decide(cue(), now=10.0).action is RoomAction.RESPOND


def test_playback_start_requires_a_response_generation_id():
    d = RoomTurnDirector()
    with pytest.raises(ValueError):
        d.set_assistant_playback(True)
    d.set_assistant_playback(True, "response-15")
    d.set_assistant_playback(False)
    assert not d.assistant_speaking


@pytest.mark.parametrize("kwargs", [
    {"confidence": float("nan")},
    {"confidence": 10**10000},
    {"urgency": 1.1},
    {"overlap": -1},
    {"ended": 8.0, "started": 9.0},
])
def test_invalid_cue_metadata_is_rejected(kwargs):
    with pytest.raises(ValueError):
        RoomTurnDirector().decide(cue(**kwargs), now=10.0)


def test_director_rejects_an_untyped_configuration():
    with pytest.raises(TypeError):
        RoomTurnDirector({})


def test_config_rejects_invalid_thresholds_and_unbounded_dedupe():
    with pytest.raises(ValueError):
        RoomPolicyConfig(min_confidence=1.5)
    with pytest.raises(ValueError):
        RoomPolicyConfig(dedupe_capacity=100_000)

def test_default_director_accepts_a_queued_question_after_a_long_reply():
    director = RoomTurnDirector()
    result = director.decide(cue(ended=10.0, started=9.8), now=30.0)
    assert result.action is RoomAction.RESPOND
