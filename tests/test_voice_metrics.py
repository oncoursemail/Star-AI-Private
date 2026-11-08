"""Latency arithmetic and report formatting independently of live voice calls."""
import pytest

from star.voice.metrics import TurnMetrics, latency_table


def test_empty_turn_has_unknown_stage_latencies_and_empty_table():
    stages = TurnMetrics().stages()
    assert all(value is None for value in stages.values())
    assert TurnMetrics().to_dict()["stages"] == stages
    table = latency_table([])
    assert "TOTAL" in table
    assert "mean" not in table


def test_stages_use_clock_differences_and_generated_token_count():
    m = TurnMetrics(
        turn=1, speech_end=1.0, turn_end=1.25, transcript_at=1.40,
        first_token_at=1.65, first_sentence_at=1.7, first_audio_at=1.9,
        last_token_at=2.65, tokens=11,
    )
    stages = m.stages()
    assert stages["endpoint"] == pytest.approx(0.25)
    assert stages["asr"] == pytest.approx(0.15)
    assert stages["speech_end_to_transcript"] == pytest.approx(0.40)
    assert stages["transcript_to_first_token"] == pytest.approx(0.25)
    assert stages["first_token_to_first_audio"] == pytest.approx(0.25)
    assert stages["total"] == pytest.approx(0.90)
    assert stages["tokens_per_second"] == pytest.approx(10.0)


def test_negative_clock_differences_are_clamped_and_zero_generation_has_no_rate():
    m = TurnMetrics(
        speech_end=2.0, turn_end=1.0, transcript_at=0.5,
        first_token_at=0.0, first_audio_at=-1.0, last_token_at=0.0, tokens=15,
    )
    assert all(value == 0.0 for key, value in m.stages().items()
               if key not in ("tokens_per_second", "queue_to_output_callback", "output_callback_total"))
    assert m.stages()["output_callback_total"] is None
    assert m.stages()["tokens_per_second"] is None
    m.first_token_at, m.last_token_at, m.tokens = 1.0, 3.0, 2
    assert m.stages()["tokens_per_second"] is None
    m.tokens = 3
    assert m.stages()["tokens_per_second"] == pytest.approx(1.0)


def test_to_dict_retains_fields_and_rounds_only_stage_values():
    m = TurnMetrics(turn=3, user_text="hello", speech_end=0.0, turn_end=0.333333,
                    first_audio_at=1.987654, error="asr unavailable")
    result = m.to_dict()
    assert result["turn"] == 3
    assert result["user_text"] == "hello"
    assert result["turn_end"] == 0.333333
    assert result["stages"]["endpoint"] == 0.333
    assert result["stages"]["total"] == 1.988
    assert result["error"] == "asr unavailable"


def test_latency_table_only_averages_complete_turns_and_reports_failure_reasons():
    first = TurnMetrics(
        turn=1, speech_end=0.0, turn_end=0.2, transcript_at=0.3,
        first_token_at=0.5, first_audio_at=1.0, last_token_at=0.9,
        tokens=6, end_reason="model", asr_speculative=True,
    )
    second = TurnMetrics(
        turn=2, speech_end=0.0, turn_end=0.4, transcript_at=0.8,
        first_token_at=1.2, first_audio_at=2.0, last_token_at=1.8,
        tokens=4, interrupted=True, heard_seconds=0.75, interrupt_reason="barge_in",
    )
    failed = TurnMetrics(turn=3, error="E" * 100)
    table = latency_table([first, second, failed])
    assert "end=model" in table
    assert "early transcript" in table
    assert "interrupted after 0.8s (barge_in)" in table
    assert "ERROR " + "E" * 60 in table
    assert "E" * 61 not in table
    mean = table.splitlines()[-1].split()
    assert mean[0] == "mean"
    assert "1.50" in mean  # Average of complete turns: (1.0 + 2.0) / 2.


def test_latencies_do_not_silently_accept_non_numeric_timestamps():
    with pytest.raises(TypeError):
        TurnMetrics(speech_end=0.0, first_audio_at="invalid").stages()
