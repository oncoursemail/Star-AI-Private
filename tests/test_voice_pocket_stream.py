"""Offline contract tests for optional CPU Pocket TTS; no weights or devices."""
import sys
import threading
import types

import pytest

from star.voice import engines
from star.voice.pocket import PocketStreamingTTS
from star.voice.settings import VoiceSettings


class FakeTensor:
    def __init__(self, values):
        self.values = values

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.values


class FakeArray:
    def __init__(self, values):
        self.values = list(values)
        self.ndim = 1
        self.size = len(self.values)


class FakeModel:
    sample_rate = 24000

    def __init__(self):
        self.prompts = []
        self.calls = []
        self.closed = 0

    def get_state_for_audio_prompt(self, voice):
        self.prompts.append(voice)
        return "state:" + voice

    def generate_audio_stream(self, state, text, *, copy_state, stop):
        self.calls.append((state, text, copy_state, stop))
        try:
            yield FakeTensor([0.0, 0.2, -0.2])
            if not stop.is_set():
                yield FakeTensor([0.7])
        finally:
            self.closed += 1


@pytest.fixture
def pocket(monkeypatch):
    model = FakeModel()
    load = []
    factory = lambda *, language: load.append(language) or model
    fake_numpy = types.SimpleNamespace(
        float32=float,
        asarray=lambda data, dtype: FakeArray(data),
        isfinite=lambda arr: types.SimpleNamespace(
            all=lambda: all(v == v and abs(v) != float("inf") for v in arr.values)
        ),
    )
    monkeypatch.setitem(sys.modules, "numpy", fake_numpy)
    monkeypatch.setattr(engines, "float_to_pcm16", lambda arr: bytes([1, 0]) * arr.size)
    return model, load, factory


def test_settings_preserve_original_default_and_require_explicit_cpu_voice():
    assert VoiceSettings().validate().tts_engine == "kokoro"
    selected = VoiceSettings.from_mapping({
        "tts_engine": "pocket", "voice": "alba", "voice_id": "",
        "speed": 1.0, "pocket_model": "english_18m_2026-10",
    })
    assert selected.voice == "alba"
    for changed in (
        {"voice": "unknown"},
        {"voice_id": "star-mum"},
        {"speed": .8},
        {"pitch_semitones": 2},
        {"tts_lang": "en-gb"},
        {"pocket_model": "unknown"},
        {"device": "cuda"},
    ):
        with pytest.raises(ValueError):
            VoiceSettings.from_mapping({**vars(selected), **changed})


def test_streams_first_audio_in_chunks_and_reuses_preloaded_voice(pocket):
    model, load, factory = pocket
    tts = PocketStreamingTTS("alba", model="english_7m_2026-10",
                             gap_ms=10, model_factory=factory)
    assert load == ["english_7m_2026-10"] and model.prompts == ["alba"]
    assert list(tts.synthesize("Hi.")) == [
        (bytes([1, 0]) * 3, 24000), (bytes([1, 0]), 24000),
        (bytes(2) * 240, 24000),
    ]
    assert model.closed == 1 and model.calls[0][:3] == ("state:alba", "Hi.", True)


def test_interruption_cancels_only_active_stream_and_next_speech_works(pocket):
    model, _, factory = pocket
    tts = PocketStreamingTTS(model_factory=factory)
    first = tts.synthesize("Old turn.")
    assert next(first)[1] == 24000
    assert tts.stop_generation() is True
    assert list(first) == [] and tts.stop_generation() is False
    assert len(list(tts.synthesize("New turn."))) == 2
    assert model.calls[0][3] is not model.calls[1][3]


def test_close_releases_resources_and_voice_change_is_serialized(pocket):
    model, _, factory = pocket
    tts = PocketStreamingTTS(model_factory=factory)
    it = tts.synthesize("Closed.")
    next(it)
    it.close()
    assert model.closed == 1
    tts.set_voice("jane")
    assert model.prompts == ["alba", "jane"]
    assert list(tts.synthesize("Again."))


def test_invalid_configuration_cannot_load_unapproved_voice_source(pocket):
    _, load, factory = pocket
    for voice in ("invalid", "unknown.wav"):
        with pytest.raises(ValueError):
            PocketStreamingTTS(voice, model_factory=factory)
    with pytest.raises(ValueError):
        PocketStreamingTTS(model="other-model", model_factory=factory)
    assert load == []


def test_refuses_empty_text_and_nonfinite_or_empty_audio(pocket):
    model, _, factory = pocket
    tts = PocketStreamingTTS(model_factory=factory)
    for text in ("", " ", None, "Hi." * 1500):
        with pytest.raises(ValueError):
            list(tts.synthesize(text))
    model.generate_audio_stream = lambda *a, **kw: iter([FakeTensor([float("nan")])])
    with pytest.raises(ValueError, match="nonfinite"):
        list(tts.synthesize("Hello."))
    model.generate_audio_stream = lambda *a, **kw: iter([FakeTensor([])])
    with pytest.raises(ValueError, match="invalid Pocket"):
        list(tts.synthesize("Hello."))
    assert tts.stop_generation() is False


def test_engine_factory_exposes_opt_in_pocket_without_changing_kokoro(monkeypatch):
    from star.voice import pocket as module
    calls = []
    monkeypatch.setattr(module, "PocketStreamingTTS",
                        lambda *a, **kw: calls.append((a, kw)) or "CPU-STREAM")
    assert engines.make_tts("pocket", "vera", 1.0, "auto",
                            pocket_model="english_2m_2026-10") == "CPU-STREAM"
    assert calls == [(("vera",), {"model": "english_2m_2026-10", "gap_ms": 0})]
    with pytest.raises(ValueError, match="native speed"):
        engines.make_tts("pocket", "alba", .8, "cpu")
    with pytest.raises(ValueError, match="native speed"):
        engines.make_tts("pocket", "alba", 1, "cpu", pitch_semitones=2)


def test_stop_generation_does_not_wait_for_busy_model(pocket):
    model, _, factory = pocket
    ready = threading.Event()
    release = threading.Event()

    def slow_stream(state, text, *, stop, copy_state):
        yield FakeTensor([0.1])
        ready.set()
        release.wait(1)
        if not stop.is_set():
            yield FakeTensor([0.2])

    model.generate_audio_stream = slow_stream
    tts = PocketStreamingTTS(model_factory=factory)
    received = []
    worker = threading.Thread(target=lambda: received.extend(tts.synthesize("Hi.")))
    worker.start()
    assert ready.wait(1)
    assert tts.stop_generation() is True
    release.set()
    worker.join(1)
    assert not worker.is_alive() and len(received) == 1


def test_cancel_speech_host_stops_cpu_generation_before_output_device():
    from star.voice.bridge import VoiceBridge, _SpeechJob
    recorder = []
    bridge = VoiceBridge(lambda *args: None)
    job = _SpeechJob("test")
    job.tts = types.SimpleNamespace(stop_generation=lambda: recorder.append("tts"))
    job.speaker = types.SimpleNamespace(stop=lambda: recorder.append("speaker"))
    bridge._speech = job
    assert bridge.stop_speaking(wait=0) is True
    assert job.cancel.is_set() and recorder == ["tts", "speaker"]


def test_status_requires_pocket_dependency_only_when_selected(monkeypatch):
    from star.voice.bridge import VoiceBridge
    from star.voice import bridge as module
    bridge = VoiceBridge(lambda *args: None)
    selected = VoiceSettings.from_mapping({
        "tts_engine": "pocket", "voice": "alba", "voice_id": "", "speed": 1.0
    })
    monkeypatch.setattr(bridge, "_load_settings", lambda: selected)
    monkeypatch.setattr(module.importlib.util, "find_spec",
                        lambda name: None if name == "pocket_tts" else object())
    report = bridge._status()
    assert "pocket-tts" in report["missingPackages"]
    assert "kokoro-onnx" not in report["missingPackages"]


def test_readaloud_cache_switches_model_and_does_not_reuse_old_engine():
    from star.voice.bridge import VoiceBridge
    from star.voice.runtime import Engines
    class Factories:
        created = []

        @classmethod
        def tts(cls, settings):
            tts = object()
            cls.created.append((settings.tts_engine, settings.pocket_model, tts))
            return tts

    bridge = VoiceBridge(lambda *args: None, factories=Factories)
    default = VoiceSettings()
    pocket = VoiceSettings.from_mapping({
        "tts_engine": "pocket", "voice": "alba",
        "voice_id": "", "speed": 1.0,
    })
    # A call engine loaded for Kokoro must not own Pocket read-aloud.
    kokoro = object()
    bridge._engines = Engines(None, None, None, kokoro, {})
    bridge._engines_key = (
        "kokoro", "faster-whisper", "auto", "", "auto", "silero",
        "smart-turn", "",
    )
    assert bridge._speech_tts(default) is kokoro
    first = bridge._speech_tts(pocket)
    assert bridge._speech_tts(pocket) is first
    next_settings = VoiceSettings.from_mapping(
        {"pocket_model": "english_7m_2026-10"}, pocket
    )
    assert bridge._speech_tts(next_settings) is not first
    assert [row[:2] for row in Factories.created] == [
        ("pocket", "english_18m_2026-10"),
        ("pocket", "english_7m_2026-10"),
    ]


def test_speaker_still_stops_when_synthesis_cancel_callback_fails():
    from star.voice.bridge import VoiceBridge, _SpeechJob
    recorder = []
    bridge = VoiceBridge(lambda *args: None)
    job = _SpeechJob("test")

    def fail():
        raise RuntimeError("backend unavailable")

    job.tts = types.SimpleNamespace(stop_generation=fail)
    job.speaker = types.SimpleNamespace(stop=lambda: recorder.append("physical-stop"))
    bridge._speech = job
    assert bridge.stop_speaking(wait=0) is True
    assert recorder == ["physical-stop"]

def test_iterator_close_failure_cannot_poison_next_utterance(pocket):
    """An upstream close error cannot retain an abandoned cancellation epoch."""
    model, _, factory = pocket
    tts = PocketStreamingTTS(model_factory=factory)

    class BrokenClose:
        def __iter__(self):
            yield FakeTensor([0.25])

        def close(self):
            raise RuntimeError("backend close failure")

    normal = model.generate_audio_stream
    model.generate_audio_stream = lambda *args, **kwargs: BrokenClose()
    with pytest.raises(RuntimeError, match="backend close failure"):
        list(tts.synthesize("First."))
    assert tts.stop_generation() is False
    model.generate_audio_stream = normal
    assert len(list(tts.synthesize("Recovered."))) == 2


def test_engine_rejects_cuda_label_before_loading_cpu_model(monkeypatch):
    from star.voice import pocket as module
    loaded = []
    monkeypatch.setattr(module, "PocketStreamingTTS",
                        lambda *args, **kwargs: loaded.append(True))
    with pytest.raises(ValueError, match="CPU-only"):
        engines.make_tts("pocket", "alba", 1.0, "cuda")
    assert loaded == []
