"""Verify device output callback timestamps separately from queued audio.

Offline fake engines and speaker callback. No mic, model, or OBS connection.
"""
from __future__ import annotations

import collections
import math
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from star.voice.call import CallConfig, CallSession
from star.voice.devices import SoundSpeaker
from star.voice.metrics import TurnMetrics, latency_table
from star.voice.turn import TurnConfig
from voice_fakes import Events, FakeASR, FakeBrain, FakeSpeaker, FakeTTS, FakeVAD, quiet, speech


class StampedSpeaker(FakeSpeaker):
    def __init__(self):
        super().__init__()
        self.stamp = None

    def reset(self):
        super().reset()
        self.stamp = None

    def play(self, pcm, sample_rate):
        super().play(pcm, sample_rate)
        if self.stamp is None:
            self.stamp = time.monotonic()

    def first_output_callback_at(self):
        return self.stamp


class InvalidStampedSpeaker(StampedSpeaker):
    def __init__(self, value):
        super().__init__()
        self.value = value

    def first_output_callback_at(self):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class NoOutputSpeaker(StampedSpeaker):
    def play(self, pcm, sample_rate):
        pass

    def played_seconds(self):
        return 0.0

    def pending_seconds(self):
        return 0.0


def run_turn(device):
    events = Events()
    session = CallSession(
        vad=FakeVAD(),
        asr=FakeASR({1: "Show me how to beat this."}),
        brain=FakeBrain(["Jump once. Then dodge carefully."]),
        tts=FakeTTS(seconds_per_word=0.01),
        speaker=device,
        config=CallConfig(turn=TurnConfig(), partial_transcripts=False),
        on_event=events,
    )
    session.start()
    for frame in speech(1, 20) + quiet(40):
        session.feed(frame)
    assert session.wait_idle(5)
    assert len(session.turns) == 1
    return session.turns[0], events


def test_output_callback_latency_is_distinct_from_queued_latency():
    metrics, events = run_turn(StampedSpeaker())
    assert metrics.output_callback_status == "observed"
    assert metrics.first_output_callback_at >= metrics.first_audio_at
    assert metrics.stages()["output_callback_total"] >= metrics.stages()["total"]
    assert metrics.stages()["queue_to_output_callback"] >= 0
    assert events.of("turn_metrics")[0]["output_callback_status"] == "observed"
    assert "OUT_CB" in latency_table([metrics])


def test_unsupported_speaker_never_claims_verified_device_callback():
    metrics, _ = run_turn(FakeSpeaker())
    assert metrics.output_callback_status == "unsupported"
    assert metrics.first_output_callback_at is None
    assert metrics.stages()["total"] is not None
    assert metrics.stages()["output_callback_total"] is None


def test_missing_device_callback_does_not_fall_back_to_queue_time():
    metrics, _ = run_turn(InvalidStampedSpeaker(None))
    assert metrics.output_callback_status == "unobserved"
    assert metrics.stages()["output_callback_total"] is None


def test_audio_never_played_does_not_report_output_callback_time():
    metrics, _ = run_turn(NoOutputSpeaker())
    assert metrics.heard_seconds == 0
    assert metrics.output_callback_status == "unplayed"
    assert metrics.first_output_callback_at is None


@pytest.mark.parametrize("stamp", [
    -5, True, float("nan"), float("inf"), "42.0", 1e100, OSError("driver failed")
])
def test_corrupted_or_faulty_callback_does_not_break_the_voice_call(stamp):
    metrics, _ = run_turn(InvalidStampedSpeaker(stamp))
    assert metrics.output_callback_status == "invalid"
    assert metrics.stages()["output_callback_total"] is None
    assert metrics.reply_text == "Jump once. Then dodge carefully."


def test_latency_stage_arithmetic_preserves_legacy_queue_total():
    metrics = TurnMetrics(speech_end=1.0, first_audio_at=2.0,
                          first_output_callback_at=2.075)
    assert metrics.stages()["total"] == 1.0
    assert metrics.stages()["queue_to_output_callback"] == pytest.approx(0.075)
    assert metrics.stages()["output_callback_total"] == pytest.approx(1.075)


def test_sound_speaker_output_callback_only_timestamps_first_nonzero_pcm(monkeypatch):
    # SoundSpeaker uses optional NumPy for RMS; stub unrelated math to test
    # the actual callback timeline without installing multimedia packages.
    class Array:
        def astype(self, _kind):
            return self

        def __mul__(self, _other):
            return self

    fake_numpy = SimpleNamespace(
        frombuffer=lambda *_args, **_kwargs: Array(),
        float32=object(),
        mean=lambda _array: 0.0,
        sqrt=lambda value: math.sqrt(value),
    )
    monkeypatch.setitem(sys.modules, "numpy", fake_numpy)
    device = SoundSpeaker.__new__(SoundSpeaker)
    device.sample_rate = 16000
    device._lock = threading.Lock()
    device._buffer = bytearray()
    device._played = 0
    device._first_output_callback_at = None
    device._levels = collections.deque(maxlen=64)

    assert device.first_output_callback_at() is None
    device.play(b"\x00\x00" * 8, 16000)
    output = bytearray(16)
    device._callback(output, 8, None, None)
    assert device.first_output_callback_at() is None

    device.play(b"\x03\x00" * 8, 16000)
    device._callback(output, 8, None, None)
    first = device.first_output_callback_at()
    assert isinstance(first, float) and first <= time.monotonic()
    assert output == b"\x03\x00" * 8

    device.play(b"\x04\x00" * 8, 16000)
    device._callback(output, 8, None, None)
    assert device.first_output_callback_at() == first
    device.stop()
    assert device.first_output_callback_at() == first
    device.reset()
    assert device.first_output_callback_at() is None
