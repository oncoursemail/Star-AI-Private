"""Acknowledgement clips (star/voice/acks.py) in a push-to-talk call with fake engines."""
from star.voice import acks
from star.voice.call import CallConfig, CallSession
from star.voice.settings import VoiceSettings
from star.voice.turn import TurnConfig
from voice_fakes import Events, FakeASR, FakeBrain, FakeSpeaker, FakeTTS, FakeVAD, quiet, speech, wait_for

TEXTS = {1: "can you help me build a door", 2: "thanks", 3: "can you make it red please"}


def session_for(replies, *, acknowledgements=True, brain_delay=0.3):
    events, speaker, tts = Events(), FakeSpeaker(), FakeTTS()
    config = CallConfig(turn=TurnConfig(), partial_transcripts=False, push_to_talk=True, ptt_tail_ms=64,
                        acknowledgements=acknowledgements)
    session = CallSession(vad=FakeVAD(), asr=FakeASR(TEXTS), brain=FakeBrain(replies, first_delay=brain_delay),
                          tts=tts, speaker=speaker, config=config, on_event=events)
    session.start()
    if session.acks is not None:
        assert session.acks.ready.wait(5)
    return session, events, tts


def turn(session, utterance):
    before = len(session.turns)
    session.push_to_talk(True)
    for frame in speech(utterance, 20):
        session.feed(frame)
    session.push_to_talk(False)
    for frame in quiet(3):
        session.feed(frame)
    assert session.wait_idle(5) and wait_for(lambda: len(session.turns) == before + 1)
    return session.turns[-1]


def test_kind_rules():
    assert acks.kind("thanks") is None and acks.kind("hi there") is None
    assert acks.kind("can you help me build a door") == "task"
    assert acks.kind("why is the sky blue today") == "question"
    assert acks.kind("I am so tired and stressed today") == "feeling"
    assert acks.kind("the dog ran across the yard") == "other"


def test_clip_plays_before_the_reply_and_counts_as_heard_audio():
    session, events, tts = session_for(["Sure. A door needs a hinge."])
    metrics = turn(session, 1)
    assert metrics.ack_text in acks.LINES["task"] and metrics.first_ack_at < metrics.first_audio_at
    stages = metrics.stages()
    assert stages["perceived"] < stages["total"] and stages["total"] >= 0.3        # the brain's delay is bridged
    assert events.of("acknowledgement")[0]["text"] == metrics.ack_text
    assert session.history[-1] == {"role": "assistant", "content": "Sure. A door needs a hinge."}   # clip not in history
    assert tts.spoken[:len(sum(acks.LINES.values(), ()))] == list(sum(acks.LINES.values(), ()))      # rendered once


def test_short_turns_get_no_clip_and_clips_rotate():
    session, _events, _tts = session_for(["Okay.", "You're welcome.", "Done."])
    first = turn(session, 1).ack_text
    assert turn(session, 2).ack_text == ""
    assert turn(session, 3).ack_text not in ("", first)


def test_a_reply_that_opens_with_the_clip_words_does_not_say_them_twice():
    session, _events, tts = session_for(["placeholder"])
    clip_texts = set(sum(acks.LINES.values(), ()))
    spoken_before = len(tts.spoken)
    session.brain.replies = [acks.LINES["task"][0] + " The door needs a hinge."]
    metrics = turn(session, 1)
    reply_spoken = tts.spoken[spoken_before:]
    assert metrics.ack_text == acks.LINES["task"][0] and not (set(reply_spoken) & clip_texts)


def test_off_by_config_and_on_in_the_app_settings():
    session, _events, _tts = session_for(["Sure."], acknowledgements=False)
    assert session.acks is None and turn(session, 1).ack_text == ""
    assert VoiceSettings().acknowledgements is True and VoiceSettings().call_config().acknowledgements is True
