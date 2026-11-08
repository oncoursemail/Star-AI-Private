"""Regression tests: STAR must never remember text that was not played.

Fake output devices model callback accounting, not a real human listener.
These tests do not capture voices, use a microphone or contact a model.
"""
from __future__ import annotations

import time

import pytest

from star.voice.call import CallConfig, CallSession
from star.voice.turn import TurnConfig
from voice_fakes import Events, FakeASR, FakeBrain, FakeSpeaker, FakeTTS, FakeVAD, quiet, speech


MESSAGE = "Please tell me how to win this level."


def run_call(text: str, *, speaker=None, tts=None, stall_seconds=2.0):
    events = Events()
    device = speaker if speaker is not None else FakeSpeaker()
    session = CallSession(
        vad=FakeVAD(),
        asr=FakeASR({1: MESSAGE}),
        brain=FakeBrain([text]),
        tts=tts if tts is not None else FakeTTS(seconds_per_word=0.01),
        speaker=device,
        config=CallConfig(
            turn=TurnConfig(), partial_transcripts=False,
            playback_stall_seconds=stall_seconds,
        ),
        on_event=events,
    )
    session.start()
    for frame in speech(1, 20) + quiet(40):
        session.feed(frame)
    assert session.wait_idle(5)
    assert len(session.turns) == 1
    return session, events, device


class DroppedSpeaker(FakeSpeaker):
    """Accept PCM but discard it before any callback reports playback."""

    def play(self, pcm: bytes, sample_rate: int) -> None:
        self.log.append(("discard", time.monotonic()))


class PartialSpeaker(FakeSpeaker):
    """The audio driver reports only half a sentence as played."""

    def pending_seconds(self) -> float:
        return 0.0

    def played_seconds(self) -> float:
        with self.lock:
            return self.queued * 0.5


class BrokenTelemetrySpeaker(FakeSpeaker):
    def played_seconds(self) -> float:
        raise OSError("unavailable sound device")


class FrozenSpeaker(FakeSpeaker):
    """Queued audio never drains, as after a failed sound card callback."""

    def __init__(self):
        super().__init__()
        self.stopped = False

    def pending_seconds(self) -> float:
        return 0.0 if self.stopped else 1.0

    def played_seconds(self) -> float:
        return 0.0

    def stop(self) -> None:
        self.stopped = True
        super().stop()


def test_real_playback_retained_and_heard_metric_recorded():
    session, _, _ = run_call("That is the first move. Now jump carefully.")
    assert session.history == [
        {"role": "user", "content": MESSAGE},
        {"role": "assistant", "content": "That is the first move. Now jump carefully."},
    ]
    assert session.turns[0].heard_seconds > 0
    assert session.turns[0].reply_text.endswith("jump carefully.")


def test_tts_failure_does_not_turn_unspoken_model_text_into_memory():
    session, events, _ = run_call(
        "I definitely beat the boss.",
        tts=FakeTTS(fail=True),
    )
    assert session.history == []
    assert session.turns[0].reply_text == ""
    assert session.turns[0].heard_seconds == 0
    assert events.of("error")


def test_discarded_audio_is_not_counted_as_speech_or_history():
    session, events, _ = run_call("I completed the level!", speaker=DroppedSpeaker())
    assert session.history == []
    assert session.turns[0].reply_text == ""
    assert session.turns[0].heard_seconds == 0
    # PCM was sent; the speaker never confirmed output playback.
    assert session.turns[0].first_audio_at is not None
    assert "no played audio" in session.turns[0].error
    assert events.of("assistant_sentence")
    assert events.of("error")


def test_partially_played_sentence_is_not_remembered_as_complete():
    session, _, _ = run_call("Alpha bravo charlie delta.", speaker=PartialSpeaker())
    assert session.turns[0].reply_text == "Alpha bravo"
    assert session.history[-1] == {"role": "assistant", "content": "Alpha bravo"}
    assert session.turns[0].heard_seconds < session.turns[0].audio_seconds


def test_unavailable_playback_telemetry_fails_closed():
    session, events, _ = run_call("The goal is across the bridge.", speaker=BrokenTelemetrySpeaker())
    assert session.history == []
    assert session.turns[0].reply_text == ""
    assert "playback telemetry" in session.turns[0].error
    assert events.of("error")


def test_audio_stall_is_stopped_instead_of_waiting_forever():
    speaker = FrozenSpeaker()
    session, events, device = run_call(
        "Jump over the wall.", speaker=speaker, stall_seconds=0.12,
    )
    assert device.stopped and device.stops == 1
    assert session.turns[0].interrupted
    assert session.turns[0].interrupt_reason == "playout_stalled"
    assert session.turns[0].heard_seconds == 0
    assert session.history == []
    assert events.of("error")


@pytest.mark.parametrize("stall", [-1, 0, 0.01, 30.1, float("nan"), True, "two"])
def test_invalid_playback_stall_config_rejected(stall):
    with pytest.raises(ValueError):
        CallSession(
            vad=FakeVAD(), asr=FakeASR({1: MESSAGE}),
            brain=FakeBrain(["Hello."]), tts=FakeTTS(),
            speaker=FakeSpeaker(),
            config=CallConfig(playback_stall_seconds=stall),
        )


def test_default_output_watchdog_is_explicitly_opt_in():
    assert CallConfig().playback_stall_seconds is None


class SecondSentenceFailure(FakeTTS):
    def synthesize(self, text):
        if "Second" in text:
            raise RuntimeError("later voice sentence failed")
        yield from super().synthesize(text)


def test_earlier_sentence_still_finishes_playing_when_later_tts_fails():
    session, events, _ = run_call(
        "First sentence. Second sentence.",
        tts=SecondSentenceFailure(seconds_per_word=0.01),
    )
    assert session.turns[0].error
    assert session.turns[0].reply_text == "First sentence."
    assert session.history == [
        {"role": "user", "content": MESSAGE},
        {"role": "assistant", "content": "First sentence."},
    ]
    assert events.of("error")


@pytest.mark.parametrize("progress", [float("nan"), float("inf"), -1, 5000])
def test_invalid_device_report_cannot_invent_spoken_words(progress):
    class InvalidProgressSpeaker(FakeSpeaker):
        def played_seconds(self):
            return progress

    session, events, _ = run_call(
        "I solved the puzzle.", speaker=InvalidProgressSpeaker(),
    )
    assert session.history == []
    assert session.turns[0].reply_text == ""
    assert "playback telemetry" in session.turns[0].error
    assert events.of("error")
