"""Runtime loading tests for low-latency room-only streaming."""
import pytest

from star.voice import engines as engine_factories
from star.voice.runtime import Engines
from star.voice.settings import VoiceSettings


class FakeTTS:
    def __init__(self):
        self.warmed = 0

    def warm_up(self):
        self.warmed += 1


def test_room_only_engine_load_skips_vad_endpointer_and_asr(monkeypatch):
    calls = []
    tts = FakeTTS()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("local speech-input model should not be loaded")

    monkeypatch.setattr(engine_factories, "make_vad", forbidden)
    monkeypatch.setattr(engine_factories, "make_endpointer", forbidden)
    monkeypatch.setattr(engine_factories, "make_asr", forbidden)
    monkeypatch.setattr(engine_factories, "make_tts", lambda *_args, **_kwargs: tts)
    engines = Engines.load(VoiceSettings(), calls.append, input_enabled=False)

    assert engines.endpointer is None
    assert engines.vad.probability(b"") == 0.0
    assert engines.asr.transcribe(b"", 16_000) == ""
    assert tts.warmed == 1
    assert any("Skipping local microphone" in message for message in calls)
    assert "Loading speech recognition" not in calls


def test_engine_loader_rejects_non_boolean_input_mode():
    with pytest.raises(TypeError, match="input_enabled"):
        Engines.load(VoiceSettings(), input_enabled=1)
