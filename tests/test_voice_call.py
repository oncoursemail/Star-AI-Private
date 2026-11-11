"""A whole voice call with fake engines: turns, speech starting on the first sentence, barge-in, cancellation."""
import time

from star.voice.call import CallConfig, CallSession
from star.voice.metrics import latency_table
from star.voice.turn import TurnConfig
from voice_fakes import Events, FakeASR, FakeBrain, FakeSpeaker, FakeTTS, FakeVAD, quiet, speech, wait_for

TEXTS = {1: "I finished my game today", 2: "wait stop", 3: "and it has a shop"}
END = quiet(40)          # 1.28 s of silence: enough to end a turn (256 ms pause + 640 ms)


def make(replies, *, brain_kwargs=None, tts_kwargs=None, asr_delay=0.0, config=None):
    events, speaker = Events(), FakeSpeaker()
    brain = FakeBrain(replies, **(brain_kwargs or {}))
    tts = FakeTTS(**(tts_kwargs or {}))
    session = CallSession(vad=FakeVAD(), asr=FakeASR(TEXTS, asr_delay), brain=brain, tts=tts, speaker=speaker,
                          config=config or CallConfig(turn=TurnConfig(), partial_transcripts=False), on_event=events)
    session.start()
    return session, events, brain, tts, speaker


def feed(session, frames, pace=0.0):
    for frame in frames:
        session.feed(frame)
        if pace:
            time.sleep(pace)


def test_one_turn_runs_every_stage_and_measures_them():
    session, events, brain, tts, speaker = make(["Oh, well done. I am so proud of you. What does it do?"])
    feed(session, speech(1, 20) + END)
    assert session.wait_idle(5)
    assert events.of("final_transcript")[0]["text"] == TEXTS[1]
    assert tts.spoken == ["Oh, well done.", "I am so proud of you.", "What does it do?"]     # sentence by sentence
    assert session.history == [
        {"role": "user", "content": TEXTS[1]},
        {"role": "assistant", "content": "Oh, well done. I am so proud of you. What does it do?"}]
    request = brain.requests[0]
    assert request[0]["role"] == "system" and "Star" in request[0]["content"]
    assert request[-1] == {"role": "user", "content": TEXTS[1]}
    assert events.states() == ["listening", "user_speaking", "thinking", "speaking", "listening"]
    metrics = session.turns[0]
    assert metrics.first_device_output_at is not None
    assert metrics.first_device_output_at >= metrics.first_audio_at
    stages = metrics.stages()
    assert all(stages[k] is not None for k in ("endpoint", "asr", "speech_end_to_transcript",
                                                "transcript_to_first_token", "first_token_to_first_audio",
                                                "total", "device_output_total", "perceived"))
    assert metrics.asr_speculative and metrics.tokens == 13 and not metrics.interrupted
    assert events.of("turn_metrics")[0]["stages"]["total"] is not None
    table = latency_table(session.turns)
    assert "TOTAL" in table and "early transcript" in table


def test_speech_starts_on_the_first_sentence_not_after_the_whole_reply():
    session, events, brain, tts, speaker = make(
        ["Okay, love. " + "Then we take one more small step together, nice and slowly. " * 3],
        brain_kwargs={"delay": 0.02})
    feed(session, speech(1, 20) + END)
    assert wait_for(lambda: session.turns or events.of("assistant_sentence"))
    assert session.wait_idle(10)
    metrics = session.turns[0]
    generation = metrics.done_at - metrics.first_token_at
    assert metrics.first_audio_at - metrics.first_token_at < 0.25 * generation


def test_barge_in_stops_speech_cancels_the_brain_and_keeps_only_what_was_heard():
    reply = "Oh, lovely. " + " ".join(f"word{i}" for i in range(1, 41)) + "."
    session, events, brain, tts, speaker = make(
        [reply, "Okay, I'm listening."], brain_kwargs={"delay": 0.01}, tts_kwargs={"seconds_per_word": 0.05})
    feed(session, speech(1, 20) + END)
    assert wait_for(lambda: session.state == "speaking" and speaker.played_seconds() > 0.3)
    feed(session, speech(2, 12), pace=0.002)                 # the user talks over Star
    assert wait_for(lambda: events.of("interrupted"))
    interrupted = events.of("interrupted")[0]
    assert interrupted["reason"] == "barge_in"
    assert speaker.stops == 1 and speaker.pending_seconds() == 0
    assert brain.streams[0].closed.is_set()
    stop_at = [t for kind, t in speaker.log if kind == "stop"][0]
    assert not [t for kind, t in speaker.log if kind == "play" and t > stop_at]      # nothing played afterwards
    caption = interrupted["heard_text"]
    assert caption.startswith("Oh, lovely.") and caption.endswith("…") and "word40" not in caption
    heard = caption.rstrip("…")                              # the history copy carries no trailing-off marker
    assert wait_for(lambda: session.history[-1:] == [{"role": "assistant", "content": heard}])

    feed(session, END)                                       # the user finishes: a normal second turn
    assert session.wait_idle(5) and wait_for(lambda: len(session.turns) == 2)
    assert brain.requests[1][-3:] == [
        {"role": "user", "content": TEXTS[1]},
        {"role": "assistant", "content": heard},             # the brain is told only what was actually said
        {"role": "user", "content": TEXTS[2]}]
    assert session.turns[0].interrupted and session.turns[0].heard_seconds > 0.3
    assert not session.turns[1].interrupted and session.history[-1]["content"] == "Okay, I'm listening."
    assert events.states()[-4:] == ["user_speaking", "thinking", "speaking", "listening"]


def test_user_who_keeps_talking_before_star_speaks_gets_one_merged_turn():
    session, events, brain, tts, speaker = make(["Never spoken.", "A shop, how lovely."],
                                                brain_kwargs={"first_delay": 0.6})
    feed(session, speech(1, 20) + END)                       # Star starts thinking...
    assert wait_for(lambda: session.state == "thinking" and len(brain.streams) == 1)
    feed(session, speech(3, 20) + END)                       # ...but the user was not finished
    assert session.wait_idle(5) and wait_for(lambda: len(session.turns) == 2)
    assert brain.streams[0].closed.is_set()
    assert tts.spoken == ["A shop, how lovely."]             # the abandoned reply never reached the speaker
    assert brain.requests[1][-1] == {"role": "user", "content": f"{TEXTS[1]} {TEXTS[3]}"}
    assert session.history == [
        {"role": "user", "content": f"{TEXTS[1]} {TEXTS[3]}"},
        {"role": "assistant", "content": "A shop, how lovely."}]
    assert session.turns[0].interrupt_reason == "user_kept_talking"


def test_short_noise_during_a_reply_does_not_interrupt_it():
    session, events, brain, tts, speaker = make(["Oh, lovely. " + "Keep going, you are doing so well. " * 4],
                                                tts_kwargs={"seconds_per_word": 0.04})
    feed(session, speech(1, 20) + END)
    assert wait_for(lambda: session.state == "speaking")
    feed(session, speech(2, 5) + quiet(10), pace=0.002)      # a 160 ms cough
    assert session.wait_idle(10)
    assert not events.of("interrupted") and speaker.stops == 0 and len(session.turns) == 1


def test_brain_failure_is_reported_and_the_call_keeps_listening():
    session, events, brain, tts, speaker = make(["Oh dear. This reply breaks half way through."],
                                                brain_kwargs={"fail_after": 3})
    feed(session, speech(1, 20) + END)
    assert session.wait_idle(5)
    assert "did not answer in time" in events.of("error")[0]["message"]
    assert session.state == "listening" and session.turns[0].error
    assert session.history[-1] == {"role": "assistant", "content": "Oh dear."}     # what was said before it broke


def test_voice_engine_failure_is_reported_and_stops_the_brain():
    session, events, brain, tts, speaker = make(["Oh dear. " * 50], brain_kwargs={"delay": 0.01},
                                                tts_kwargs={"fail": True})
    feed(session, speech(1, 20) + END)
    assert session.wait_idle(5)
    assert "voice engine crashed" in events.of("error")[0]["message"]
    assert brain.streams[0].closed.is_set() and brain.streams[0].sent < 100
    assert session.state == "listening"


def test_empty_transcript_mute_manual_interrupt_and_stop():
    session, events, brain, tts, speaker = make(["Hello."])
    session.asr.texts[1] = ""
    feed(session, speech(1, 20) + END)
    assert session.wait_idle(5) and brain.requests == [] and session.turns == []
    assert session.state == "listening"

    session.asr.texts[1] = TEXTS[1]
    session.set_muted(True)
    feed(session, speech(1, 20) + END)
    assert brain.requests == [] and events.of("muted")[-1]["muted"] is True
    session.set_muted(False)

    session.brain = FakeBrain(["Oh, hello. " + "This is a long reply. " * 20], delay=0.01)
    feed(session, speech(1, 20) + END)
    assert wait_for(lambda: session.state == "speaking")
    session.interrupt()                                       # the "stop talking" button
    assert session.wait_idle(5) and events.of("interrupted")[-1]["reason"] == "button"
    assert session.state == "listening"

    feed(session, speech(1, 20) + END)
    assert wait_for(lambda: session.busy())
    session.stop()
    assert not session.busy() and session.state == "ended" and speaker.pending_seconds() == 0
    before = len(events.items)
    feed(session, speech(1, 20) + END)                        # frames after the call ended are ignored
    assert len(events.items) == before


def test_history_is_trimmed_in_blocks_so_the_server_prompt_cache_keeps_working():
    config = CallConfig(turn=TurnConfig(), partial_transcripts=False, history_messages=8)
    session, events, brain, tts, speaker = make(["Okay."], config=config, tts_kwargs={"seconds_per_word": 0.01})
    for _ in range(9):
        feed(session, speech(1, 20) + END)
        assert session.wait_idle(5)
    sizes = [len(request) for request in brain.requests]
    # system + history + new user message: grows by one exchange per turn, then drops by half in one go
    assert sizes == [2, 4, 6, 8, 10, 6, 8, 10, 6]
    for earlier, later in zip(brain.requests, brain.requests[1:]):
        if len(later) > len(earlier):
            assert later[:len(earlier)] == earlier          # the prefix the server cached is unchanged


def test_live_transcript_and_level_events_reach_the_listener():
    config = CallConfig(turn=TurnConfig(), partial_transcripts=True, partial_interval=0.05, level_interval=0.0)
    session, events, brain, tts, speaker = make(["Lovely."], config=config)
    feed(session, speech(1, 40), pace=0.004)
    assert wait_for(lambda: events.of("partial_transcript"))
    assert events.of("partial_transcript")[0]["text"] == TEXTS[1]
    feed(session, END)
    assert session.wait_idle(5)
    levels = events.of("level")
    assert levels and all(0.0 <= e["mic"] <= 1.0 and 0.0 <= e["speaker"] <= 1.0 for e in levels)
    assert any(e["mic"] > 0 for e in levels)
