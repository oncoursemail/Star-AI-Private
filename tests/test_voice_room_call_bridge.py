"""Bridge classified multiparty room cues to exact CallSession playback generations."""

import time

import pytest

from star.voice.call import CallConfig, CallSession
from star.voice.room import CueIntent, CueSource, RoomAction, RoomCue, RoomTurnDirector
from star.voice.room_queue import RoomCueQueue, RoomQueueConfig
from star.voice.turn import TurnConfig
from voice_fakes import Events, FakeASR, FakeBrain, FakeSpeaker, FakeTTS, FakeVAD, quiet, speech, wait_for

TEXTS = {
    1: "The first viewer asks a question",
    2: "A second viewer asks a follow up",
}
END = quiet(40)


def make(replies, *, room_director=True, room_queue=None, tts_seconds_per_word=0.2, brain_first_delay=0.0):
    events, speaker = Events(), FakeSpeaker()
    director = RoomTurnDirector() if room_director else None
    session = CallSession(
        vad=FakeVAD(),
        asr=FakeASR(TEXTS),
        brain=FakeBrain(replies, first_delay=brain_first_delay, delay=0.01),
        tts=FakeTTS(seconds_per_word=tts_seconds_per_word),
        speaker=speaker,
        config=CallConfig(turn=TurnConfig(), partial_transcripts=False),
        on_event=events,
        room_director=director,
        room_queue=room_queue,
    )
    session.start()
    return session, events, speaker


def cue(event_id, *, intent=CueIntent.DIRECT_QUESTION, source=CueSource.AUDIO,
        addressed=True, overlap_ms=0):
    now = time.monotonic()
    return RoomCue(
        event_id=event_id,
        speaker_id="speaker-opaque-1",
        source=source,
        intent=intent,
        addressed_to_star=addressed,
        confidence=0.99,
        started_at=now - 0.4,
        ended_at=now,
        overlap_ms=overlap_ms,
    )


def test_room_cue_can_request_a_response_when_call_is_idle():
    session, _, _ = make(["Hello."])
    try:
        decision = session.handle_room_cue(cue("idle-question"))
        assert decision.action is RoomAction.RESPOND
        assert decision.reason == "directed_to_star"
        assert not session.busy()  # host adapter still owns response creation
    finally:
        session.stop()


def test_backchannel_during_playback_does_not_cancel_the_reply():
    reply = "I am explaining the plan. " + "We can take the next step together. " * 12
    session, _, speaker = make([reply])
    try:
        session.feed(speech(1, 20)[0])
        for frame in speech(1, 19) + END:
            session.feed(frame)
        assert wait_for(lambda: session.state == "speaking" and speaker.played_seconds() > 0.04)
        decision = session.handle_room_cue(
            cue("backchannel", intent=CueIntent.BACKCHANNEL, addressed=False)
        )
        assert decision.action is RoomAction.CONTINUE
        assert speaker.stops == 0
        assert session.busy()
    finally:
        session.interrupt()
        session.wait_idle(5)
        session.stop()


def test_direct_question_is_queued_while_star_is_still_preparing_a_reply():
    reply = "I am preparing the answer. " + "Here is the explanation. " * 10
    session, _, speaker = make([reply], brain_first_delay=0.4)
    try:
        for frame in speech(1, 20) + END:
            session.feed(frame)
        assert wait_for(lambda: session.state == "thinking")
        queued_cue = cue("question-during-thinking")
        decision = session.handle_room_cue(queued_cue)
        assert decision.action is RoomAction.QUEUE
        assert decision.reason == "assistant_reply_in_progress"
        assert session.pop_queued_room_cue() == queued_cue
        assert speaker.stops == 0
    finally:
        session.interrupt()
        session.wait_idle(5)
        session.stop()


def test_direct_barge_in_cancels_the_exact_active_playback_generation():
    reply = "One moment. " + "This is a long explanation for the current viewer. " * 20
    session, events, speaker = make([reply])
    try:
        for frame in speech(1, 20) + END:
            session.feed(frame)
        assert wait_for(lambda: session.state == "speaking" and speaker.played_seconds() > 0.04)
        decision = session.handle_room_cue(cue("direct-barge-in", overlap_ms=320))
        assert decision.action is RoomAction.INTERRUPT
        assert decision.reason == "high_confidence_direct_audio_barge_in"
        assert session.wait_idle(5)
        assert speaker.stops == 1
        assert events.of("interrupted")[-1]["reason"] == "room_barge_in"
    finally:
        session.stop()


def test_stale_response_id_cannot_cancel_a_newer_reply():
    long_reply = "First sentence. " + "This response keeps going for a while. " * 18
    session, _, speaker = make([long_reply, long_reply])
    try:
        for frame in speech(1, 20) + END:
            session.feed(frame)
        assert wait_for(lambda: session.state == "speaking" and speaker.played_seconds() > 0.04)
        old_id = session._reply.response_id
        session.interrupt()
        assert session.wait_idle(5)

        for frame in speech(2, 20) + END:
            session.feed(frame)
        assert wait_for(lambda: session.state == "speaking" and speaker.played_seconds() > 0.04)
        new_id = session._reply.response_id
        assert new_id != old_id
        assert session.interrupt_response(old_id) is False
        assert session.busy()
        assert session._reply.response_id == new_id
    finally:
        session.interrupt()
        session.wait_idle(5)
        session.stop()


def test_room_bridge_requires_explicit_director_and_valid_response_ids():
    session, _, _ = make(["Hello."], room_director=False)
    try:
        with pytest.raises(RuntimeError, match="not configured"):
            session.handle_room_cue(cue("no-director"))
        with pytest.raises(ValueError, match="response_id"):
            session.interrupt_response("")
    finally:
        session.stop()


def test_full_call_room_queue_returns_wait_instead_of_dropping_a_cue():
    queue = RoomCueQueue(RoomQueueConfig(max_items=1))
    reply = "I am preparing the answer. " + "Here is the explanation. " * 10
    session, _, _ = make([reply], room_queue=queue, brain_first_delay=0.4)
    try:
        for frame in speech(1, 20) + END:
            session.feed(frame)
        assert wait_for(lambda: session.state == "thinking")
        first = cue("first-queued-question")
        second = cue("second-queued-question")
        assert session.handle_room_cue(first).action is RoomAction.QUEUE
        full = session.handle_room_cue(second)
        assert full.action is RoomAction.WAIT
        assert full.reason == "room_queue_full"
        assert session.pop_queued_room_cue() == first
    finally:
        session.interrupt()
        session.wait_idle(5)
        session.stop()


def test_stopping_a_call_clears_queued_room_cues_and_session_dedupe():
    queue = RoomCueQueue()
    reply = "I am preparing the answer. " + "Here is the explanation. " * 10
    session, _, _ = make([reply], room_queue=queue, brain_first_delay=0.4)
    for frame in speech(1, 20) + END:
        session.feed(frame)
    assert wait_for(lambda: session.state == "thinking")
    item = cue("clear-on-stop")
    assert session.handle_room_cue(item).action is RoomAction.QUEUE
    session.stop()
    assert session.pop_queued_room_cue() is None
    assert queue.stats.accepted == 0
