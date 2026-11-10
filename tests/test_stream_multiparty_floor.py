from __future__ import annotations

import pytest

from star.stream_multiparty_floor import (
    FloorObservation,
    FloorPolicy,
    StreamMultipartyFloorGate,
)


def make_observation(
    gate: StreamMultipartyFloorGate,
    *,
    turn_id: str = "turn-0001",
    sequence: int = 1,
    captured_ms: float = 10_000.0,
    addressed_to: str = "star",
    speech_act: str = "question",
    speaker_confidence: float = 0.95,
    addressee_confidence: float = 0.95,
    act_confidence: float = 0.95,
    active_speakers: int = 1,
    turn_complete: bool = True,
    interrupted: bool = False,
) -> FloorObservation:
    return FloorObservation(
        turn_id=turn_id,
        session_epoch=gate.session_epoch,
        sequence=sequence,
        captured_ms=captured_ms,
        speaker_slot=1,
        addressed_to=addressed_to,
        speech_act=speech_act,
        speaker_confidence=speaker_confidence,
        addressee_confidence=addressee_confidence,
        act_confidence=act_confidence,
        active_speakers=active_speakers,
        turn_complete=turn_complete,
        interrupted=interrupted,
    )


def evaluate(**kwargs):
    gate = StreamMultipartyFloorGate()
    gate.enable(owner_approved=True)
    observation = make_observation(gate, **kwargs)
    assert gate.observe(observation)
    return gate.decide(observation.turn_id, now_ms=10_000.0), gate, observation


def test_owner_approval_is_required():
    gate = StreamMultipartyFloorGate()
    with pytest.raises(PermissionError):
        gate.enable()
    assert gate.status()["enabled"] is False


def test_direct_question_to_star_is_allowed_once():
    decision, gate, observation = evaluate()
    assert decision.action == "respond"
    assert decision.should_speak is True
    replay = gate.decide(observation.turn_id, now_ms=10_001.0)
    assert replay.action == "hold"
    assert replay.reason == "missing_receipt"


@pytest.mark.parametrize(
    ("addressed_to", "speech_act", "expected"),
    [
        ("other", "question", "silence"),
        ("other", "side_conversation", "silence"),
        ("group", "question", "listen"),
        ("star", "backchannel", "backchannel"),
        ("star", "statement", "listen"),
        ("star", "request", "respond"),
        ("star", "correction", "respond"),
        ("star", "side_conversation", "silence"),
    ],
)
def test_address_and_speech_act_policy(addressed_to, speech_act, expected):
    decision, _, _ = evaluate(addressed_to=addressed_to, speech_act=speech_act)
    assert decision.action == expected


def test_unknown_or_low_confidence_addressee_holds():
    decision, _, _ = evaluate(addressed_to="unknown")
    assert decision.action == "hold"
    decision, _, _ = evaluate(addressee_confidence=0.4)
    assert decision.reason == "uncertain_addressee"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("speaker_confidence", 0.2, "low_speaker_confidence"),
        ("act_confidence", 0.2, "low_act_confidence"),
    ],
)
def test_low_confidence_suppresses_response(field, value, reason):
    decision, _, _ = evaluate(**{field: value})
    assert decision.action == "hold"
    assert decision.reason == reason


def test_overlap_and_interruption_hold():
    decision, _, _ = evaluate(active_speakers=2)
    assert decision.reason == "overlapping_speakers"
    decision, _, _ = evaluate(interrupted=True)
    assert decision.reason == "interrupted_turn"


def test_incomplete_turn_is_listened_to_not_answered():
    decision, _, _ = evaluate(turn_complete=False)
    assert decision.action == "listen"
    assert decision.should_speak is False


def test_uncertain_speech_act_holds():
    decision, _, _ = evaluate(speech_act="uncertain")
    assert decision.action == "hold"
    assert decision.reason == "uncertain_speech_act"


@pytest.mark.parametrize(
    ("captured_ms", "now_ms", "reason"),
    [
        (1_000.0, 3_000.0, "stale_receipt"),
        (10_100.0, 10_000.0, "future_receipt"),
    ],
)
def test_stale_and_future_receipts_hold(captured_ms, now_ms, reason):
    gate = StreamMultipartyFloorGate()
    gate.enable(owner_approved=True)
    observation = make_observation(gate, captured_ms=captured_ms)
    assert gate.observe(observation)
    decision = gate.decide(observation.turn_id, now_ms=now_ms)
    assert decision.action == "hold"
    assert decision.reason == reason


def test_clock_regression_latches_until_new_session():
    gate = StreamMultipartyFloorGate()
    gate.enable(owner_approved=True)
    first = make_observation(gate, turn_id="turn-0001", sequence=1, captured_ms=10_000)
    assert gate.observe(first)
    assert gate.decide(first.turn_id, now_ms=10_000).action == "respond"
    second = make_observation(gate, turn_id="turn-0002", sequence=2, captured_ms=10_100)
    assert gate.observe(second)
    assert gate.decide(second.turn_id, now_ms=9_999).reason == "clock_regression"
    assert gate.status()["clock_fault"] is True
    third = make_observation(gate, turn_id="turn-0003", sequence=3, captured_ms=10_200)
    assert gate.observe(third) is False
    gate.disable()
    gate.enable(owner_approved=True)
    assert gate.status()["clock_fault"] is False


def test_session_sequence_and_turn_replay_are_rejected():
    gate = StreamMultipartyFloorGate()
    gate.enable(owner_approved=True)
    observation = make_observation(gate)
    assert gate.observe(observation)
    assert gate.observe(observation) is False
    wrong_epoch = FloorObservation(
        turn_id="turn-0002", session_epoch=gate.session_epoch + 1, sequence=2,
        captured_ms=10_001, speaker_slot=1, addressed_to="star",
        speech_act="question", speaker_confidence=0.95,
        addressee_confidence=0.95, act_confidence=0.95,
    )
    assert gate.observe(wrong_epoch) is False
    out_of_order = make_observation(
        gate, turn_id="turn-0003", sequence=1, captured_ms=10_002
    )
    assert gate.observe(out_of_order) is False


def test_bounded_capacity_rejects_without_evicting_replay_history():
    gate = StreamMultipartyFloorGate(FloorPolicy(max_pending=1, max_seen=2))
    gate.enable(owner_approved=True)
    first = make_observation(gate, turn_id="turn-0001", sequence=1, captured_ms=10_000)
    second = make_observation(gate, turn_id="turn-0002", sequence=2, captured_ms=10_001)
    assert gate.observe(first)
    assert gate.observe(second) is False
    assert gate.status()["pending"] == 1
    assert gate.status()["capacity_rejections"] == 1


def test_disable_clears_pending_receipts_and_invalidates_epoch():
    gate = StreamMultipartyFloorGate()
    first_epoch = gate.enable(owner_approved=True)
    observation = make_observation(gate)
    assert observation.session_epoch == first_epoch
    assert gate.observe(observation)
    gate.disable()
    assert gate.status()["pending"] == 0
    gate.enable(owner_approved=True)
    assert gate.session_epoch != first_epoch
    assert gate.observe(observation) is False


def test_status_is_aggregate_only():
    decision, gate, observation = evaluate()
    status = str(gate.status())
    assert decision.action == "respond"
    assert observation.turn_id not in status
    assert "speaker_slot" not in status
    assert "turn_id" not in status


@pytest.mark.parametrize(
    "kwargs",
    [
        {"turn_id": ""},
        {"session_epoch": True},
        {"sequence": False},
        {"captured_ms": float("nan")},
        {"speaker_slot": 0},
        {"addressed_to": "owner"},
        {"speech_act": "tool_call"},
        {"speaker_confidence": 1.1},
        {"active_speakers": 0},
        {"turn_complete": 1},
    ],
)
def test_invalid_observation_fields_are_rejected(kwargs):
    gate = StreamMultipartyFloorGate()
    gate.enable(owner_approved=True)
    base = dict(
        turn_id="turn-0001", session_epoch=gate.session_epoch, sequence=1,
        captured_ms=10_000, speaker_slot=1, addressed_to="star",
        speech_act="question", speaker_confidence=0.95,
        addressee_confidence=0.95, act_confidence=0.95,
        active_speakers=1, turn_complete=True, interrupted=False,
    )
    base.update(kwargs)
    with pytest.raises(ValueError):
        FloorObservation(**base)
