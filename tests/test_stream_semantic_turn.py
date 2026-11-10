"""Semantic end-of-turn decisions never override trusted VAD or owner arbitration."""
from __future__ import annotations

import pytest

from star.stream_semantic_turn import SemanticTurnGate, SemanticTurnPrediction
from star.stream_turntaking import TurnTakingGate, VoiceFrame


TURN = "a" * 20
OTHER_TURN = "b" * 20


def _prediction(*, sequence=1, complete=True, turn_id=TURN, observed=1450.0,
                audio_end=1110.0, confidence=0.9):
    return SemanticTurnPrediction(
        turn_id=turn_id,
        sequence=sequence,
        audio_end_ms=audio_end,
        observed_at_ms=observed,
        is_complete=complete,
        model="livekit-turn-detector-v1-mini",
        language="en",
        confidence=confidence,
        latency_ms=80.0,
    )


def _quiet_gate():
    gate = TurnTakingGate()
    gate.enable(owner_approved=True)
    for index in range(12):
        gate.observe(VoiceFrame(
            at_ms=1000.0 + index * 10.0,
            duration_ms=10.0,
            owner_probability=0.0,
            guest_probability=0.9,
            echo_cleared=True,
        ))
    gate.observe(VoiceFrame(
        at_ms=1460.0,
        duration_ms=10.0,
        owner_probability=0.0,
        guest_probability=0.0,
        echo_cleared=True,
    ))
    return gate


def _owner_gate():
    gate = TurnTakingGate()
    gate.enable(owner_approved=True)
    for index in range(12):
        gate.observe(VoiceFrame(
            at_ms=1000.0 + index * 10.0,
            duration_ms=10.0,
            owner_probability=0.95,
            guest_probability=0.01,
            echo_cleared=True,
        ))
    return gate


def test_semantic_completion_allows_speech_only_after_trusted_vad_silence():
    gate = SemanticTurnGate(_quiet_gate())
    advice = gate.advise(
        now_ms=1460.0, star_speaking=False,
        expected_turn_id=TURN, prediction=_prediction(),
    )
    assert advice.action == "speak"
    assert advice.should_interrupt is False
    assert advice.reason == "semantic_turn_complete"


def test_mid_sentence_pause_prediction_keeps_star_silent():
    gate = SemanticTurnGate(_quiet_gate())
    advice = gate.advise(
        now_ms=1460.0, star_speaking=False,
        expected_turn_id=TURN, prediction=_prediction(complete=False),
    )
    assert advice.action == "hold"
    assert advice.should_interrupt is False
    assert advice.reason == "semantic_turn_continue"


def test_missing_semantic_prediction_fails_closed_after_vad_silence():
    gate = SemanticTurnGate(_quiet_gate())
    advice = gate.advise(
        now_ms=1460.0, star_speaking=False,
        expected_turn_id=TURN, prediction=None,
    )
    assert advice.action == "hold"
    assert advice.reason == "semantic_prediction_missing"


def test_owner_barge_in_precedes_missing_or_stale_semantic_prediction():
    gate = SemanticTurnGate(_owner_gate())
    advice = gate.advise(
        now_ms=1110.0, star_speaking=True,
        expected_turn_id=TURN, prediction=None,
    )
    assert advice.action == "yield_owner"
    assert advice.should_interrupt is True
    assert advice.reason == "confirmed_authenticated_owner_voice"


def test_guest_voice_hold_cannot_be_overridden_by_semantic_completion():
    gate = TurnTakingGate()
    gate.enable(owner_approved=True)
    for index in range(12):
        gate.observe(VoiceFrame(
            at_ms=1000.0 + index * 10.0,
            duration_ms=10.0,
            owner_probability=0.0,
            guest_probability=0.9,
            echo_cleared=True,
        ))
    advice = SemanticTurnGate(gate).advise(
        now_ms=1110.0, star_speaking=False,
        expected_turn_id=TURN, prediction=_prediction(),
    )
    assert advice.action == "hold"
    assert advice.reason == "confirmed_guest_voice"


def test_wrong_turn_id_is_rejected():
    advice = SemanticTurnGate(_quiet_gate()).advise(
        now_ms=1460.0, star_speaking=False,
        expected_turn_id=TURN, prediction=_prediction(turn_id=OTHER_TURN),
    )
    assert advice.action == "hold"
    assert advice.reason == "semantic_turn_mismatch"


def test_stale_future_and_overlong_endpointing_predictions_are_rejected():
    gate = SemanticTurnGate(_quiet_gate())
    stale = _prediction(observed=900.0, audio_end=800.0)
    assert gate.advise(
        now_ms=1460.0, star_speaking=False,
        expected_turn_id=TURN, prediction=stale,
    ).reason == "semantic_prediction_stale"

    future = _prediction(observed=1500.0, audio_end=1110.0)
    assert gate.advise(
        now_ms=1460.0, star_speaking=False,
        expected_turn_id=TURN, prediction=future,
    ).reason == "semantic_prediction_stale"

    slow_gate = _quiet_gate()
    slow_gate.observe(VoiceFrame(
        at_ms=4000.0, duration_ms=10.0,
        owner_probability=0.0, guest_probability=0.0, echo_cleared=True,
    ))
    slow = _prediction(observed=4000.0, audio_end=1000.0)
    slow_advice = SemanticTurnGate(slow_gate).advise(
        now_ms=4000.0, star_speaking=False,
        expected_turn_id=TURN, prediction=slow,
    )
    assert slow_advice.action == "speak"
    assert slow_advice.reason == "semantic_timeout_fallback"


def test_missing_prediction_uses_bounded_fallback_after_max_endpointing():
    gate = _quiet_gate()
    gate.observe(VoiceFrame(
        at_ms=3610.0, duration_ms=10.0,
        owner_probability=0.0, guest_probability=0.0, echo_cleared=True,
    ))
    semantic = SemanticTurnGate(gate)
    advice = semantic.advise(
        now_ms=3610.0, star_speaking=False,
        expected_turn_id=TURN, prediction=None,
        expected_audio_end_ms=1110.0,
    )
    assert advice.action == "speak"
    assert advice.reason == "semantic_timeout_fallback"
    assert semantic.metrics()["timeout_fallbacks"] == 1


def test_replayed_sequence_is_rejected_and_higher_sequence_is_accepted():
    gate = SemanticTurnGate(_quiet_gate())
    first = _prediction(sequence=1)
    assert gate.advise(
        now_ms=1460.0, star_speaking=False,
        expected_turn_id=TURN, prediction=first,
    ).action == "speak"
    replay = gate.advise(
        now_ms=1460.0, star_speaking=False,
        expected_turn_id=TURN, prediction=first,
    )
    assert replay.action == "hold"
    assert replay.reason == "semantic_prediction_replay"
    newer = _prediction(sequence=2)
    assert gate.advise(
        now_ms=1460.0, star_speaking=False,
        expected_turn_id=TURN, prediction=newer,
    ).action == "speak"


def test_host_audio_endpoint_must_match_the_prediction():
    advice = SemanticTurnGate(_quiet_gate()).advise(
        now_ms=1460.0, star_speaking=False,
        expected_turn_id=TURN, prediction=_prediction(),
        expected_audio_end_ms=900.0,
    )
    assert advice.action == "hold"
    assert advice.reason == "semantic_audio_end_mismatch"


def test_low_confidence_prediction_is_held():
    advice = SemanticTurnGate(_quiet_gate(), minimum_confidence=0.6).advise(
        now_ms=1460.0, star_speaking=False,
        expected_turn_id=TURN, prediction=_prediction(confidence=0.2),
    )
    assert advice.action == "hold"
    assert advice.reason == "semantic_confidence_low"


def test_untrusted_or_invalid_prediction_fields_are_rejected():
    with pytest.raises(ValueError):
        _prediction(turn_id="not-a-turn")
    with pytest.raises(ValueError):
        SemanticTurnPrediction(
            TURN, 1, 1110.0, 1450.0, True, "unknown-model", "en",
        )
    with pytest.raises(ValueError):
        SemanticTurnPrediction(
            TURN, 1, 1110.0, 1450.0, True, "custom", "en",
            confidence=1.5,
        )
    with pytest.raises(ValueError):
        SemanticTurnPrediction(
            TURN, 1, 1110.0, 1450.0, True, "custom", "not_a_language",
        )


def test_invalid_expected_turn_and_prediction_type_are_rejected():
    gate = SemanticTurnGate(_quiet_gate())
    with pytest.raises(ValueError):
        gate.advise(
            now_ms=1460.0, star_speaking=False,
            expected_turn_id="bad", prediction=_prediction(),
        )
    with pytest.raises(TypeError):
        gate.advise(
            now_ms=1460.0, star_speaking=False,
            expected_turn_id=TURN, prediction=object(),
        )


def test_metrics_expose_counts_without_turn_ids_or_audio():
    gate = SemanticTurnGate(_quiet_gate())
    gate.advise(
        now_ms=1460.0, star_speaking=False,
        expected_turn_id=TURN, prediction=_prediction(),
    )
    metrics = gate.metrics()
    assert metrics["semantic_completions"] == 1
    assert metrics["predictions_seen"] == 1
    assert TURN not in str(metrics)
    assert "audio" not in metrics
