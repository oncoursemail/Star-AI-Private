"""Deterministic zero-device probes; first generated != first physically audible."""
import pytest

from star.voice.pocket_benchmark import (
    SpeechProbe, probe_generation, summarize_probes,
)


class StaticTTS:
    def synthesize(self, text):
        yield bytes(4800), 24000
        yield bytes(4800), 24000


def test_probe_measurements_stay_aggregate_and_do_not_play_audio():
    times = iter((0.0, .1, .2))
    probe = probe_generation(StaticTTS(), "Hello.", clock=lambda: next(times))
    assert probe == SpeechProbe(100.0, 200.0, 200.0, 1.0, 2)
    assert not hasattr(probe, "audio") and not hasattr(probe, "text")


def test_summary_has_predefined_metrics_with_no_content():
    rows = [
        SpeechProbe(80, 200, 300, .6667, 4),
        SpeechProbe(120, 180, 400, .45, 3),
        SpeechProbe(90, 160, 350, .4571, 3),
    ]
    result = summarize_probes(rows)
    assert result["probes"] == 3
    assert result["first_generated_chunk_p50_ms"] == 90
    assert result["first_generated_chunk_p95_ms"] == 120
    assert result["total_audio_s"] == 1.05
    assert "first-audible" in result["note"]


def test_empty_samples_or_nonpcm_and_sample_rate_changes_fail():
    class Empty:
        def synthesize(self, text):
            return iter(())

    class Invalid:
        def synthesize(self, text):
            yield b"x", 24000

    class RateChanges:
        def synthesize(self, text):
            yield bytes(48), 24000
            yield bytes(48), 16000

    for tts, error in (
        (Empty(), RuntimeError), (Invalid(), ValueError),
        (RateChanges(), ValueError),
    ):
        with pytest.raises(error):
            probe_generation(tts, "Public sample.")


def test_benchmark_does_not_accept_unbounded_inputs():
    with pytest.raises(ValueError):
        probe_generation(StaticTTS(), "")
    with pytest.raises(ValueError):
        probe_generation(StaticTTS(), "long" * 52)
    for rows in ([], [SpeechProbe(1, 2, 3, .7, 1)]):
        with pytest.raises(ValueError):
            summarize_probes(rows)
