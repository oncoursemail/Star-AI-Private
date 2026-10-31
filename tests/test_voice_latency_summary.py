"""Voice latency percentiles: synthetic timings, no microphone or GPU needed."""
from __future__ import annotations

from math import inf, nan

import pytest

from star.voice.metrics import TurnMetrics, latency_summary


def test_nearest_rank_percentiles_and_excluded_errors():
    turns = [
        TurnMetrics(turn=n, speech_end=0.0, turn_end=0.01, transcript_at=0.02,
                    first_token_at=0.03, first_audio_at=n / 10,
                    user_text="PRIVATE DO NOT EXPORT", reply_text="SENSITIVE",
                    interrupted=n == 20)
        for n in range(1, 21)
    ]
    turns.extend([
        TurnMetrics(turn=21, speech_end=0, first_audio_at=0.001, error="GPU error"),
        TurnMetrics(turn=22, speech_end=0.0),  # incomplete, not zero latency
        TurnMetrics(turn=23, speech_end=2.0, first_audio_at=1.0),  # reversed clock
    ])
    summary = latency_summary(turns)
    assert summary["total_turns"] == 23
    assert summary["errored_turns"] == 1
    assert summary["incomplete_turns"] == 1
    assert summary["invalid_clock_turns"] == 1
    assert summary["interrupted_turns"] == 1
    output = summary["latency"]["speech_end_to_audio_submitted"]
    assert output == {"n": 20, "p50_ms": 1000.0, "p95_ms": 1900.0, "max_ms": 2000.0}
    assert summary["latency"]["brain_first_token"]["n"] == 20
    assert "PRIVATE DO NOT EXPORT" not in str(summary)
    assert "SENSITIVE" not in str(summary)


def test_no_data_means_unknown_not_fast():
    empty = latency_summary([])
    assert empty["total_turns"] == 0
    assert empty["latency"]["speech_end_to_audio_submitted"] == {
        "n": 0, "p50_ms": None, "p95_ms": None, "max_ms": None,
    }
    incomplete = latency_summary([TurnMetrics(turn=1, interrupted=True)])
    assert incomplete["incomplete_turns"] == 1
    assert incomplete["interrupted_turns"] == 1
    assert incomplete["latency"]["speech_end_to_audio_submitted"]["n"] == 0


@pytest.mark.parametrize("value", [nan, inf, float("-inf"), True, "1.5"])
def test_invalid_timestamps_cannot_poison_tail_latency(value):
    summary = latency_summary([TurnMetrics(speech_end=0.0, first_audio_at=value)])
    assert summary["invalid_clock_turns"] == 1
    assert summary["latency"]["speech_end_to_audio_submitted"]["p95_ms"] is None


def test_audio_before_first_token_is_invalid():
    summary = latency_summary([TurnMetrics(speech_end=1.0, first_token_at=1.5,
                                           first_audio_at=1.1)])
    assert summary["invalid_clock_turns"] == 1


def test_each_stage_uses_only_ordered_pairs():
    summary = latency_summary([TurnMetrics(
        speech_end=0.0, turn_end=0.25, transcript_at=0.1,
        first_token_at=0.4, first_audio_at=0.7,
    )])
    assert summary["latency"]["endpointer"]["p95_ms"] == 250.0
    assert summary["latency"]["transcription"]["n"] == 0
    assert summary["latency"]["tts_and_queue"]["p95_ms"] == 300.0


def test_unbounded_or_malformed_input_rejected():
    with pytest.raises(ValueError):
        latency_summary([TurnMetrics()] * 10001)
    with pytest.raises(ValueError):
        latency_summary([object()])
