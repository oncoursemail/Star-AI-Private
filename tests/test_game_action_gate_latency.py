"""Offline action-gate tests for capture order and bounded latency evidence.

No OS input, games, streaming, personal information, or wall-clock dependencies.
"""
from __future__ import annotations

from dataclasses import replace

from star.game_action_gate import (
    ActionPermit, GameActionGate, GameActionHint, GameFrame, GameScope,
)
from star.stream_budget import StreamTelemetry


_SCOPE = GameScope("test_platformer", "build1", "run1")
_DIGEST = "a" * 64
_TELEMETRY = StreamTelemetry(False, True, 4500, 8192, 60, 0)


def _gate() -> GameActionGate:
    gate = GameActionGate()
    gate.start(_SCOPE, ("jump",), owner_approved=True)
    return gate


def _request(gate: GameActionGate, *, seq: int, captured_ms: float,
             now_ms: float, host_verified: bool = True) -> ActionPermit:
    frame = GameFrame(
        _SCOPE, seq, captured_ms, _DIGEST, True, True, 0.95,
    )
    hint = GameActionHint(
        "jump", seq, _DIGEST, captured_ms + 15, 70,
    )
    return gate.request(
        frame, hint, now_ms=now_ms, host_verified=host_verified,
        telemetry=_TELEMETRY,
    )


def test_reordered_observation_is_rejected_despite_higher_sequence() -> None:
    gate = _gate()
    permit = _request(gate, seq=1, captured_ms=1000, now_ms=1020)
    assert permit.offered and permit.ticket is not None
    assert gate.release(permit.ticket, now_ms=1040, host_confirmed_released=True)

    # Both are within the age budget and well past the action-spacing budget.
    # They would previously have been offered only because sequence increased.
    for captured in (990, 1000):
        refused = _request(gate, seq=2, captured_ms=captured, now_ms=1260)
        assert not refused.offered
        assert refused.reason == "out_of_order_frame_capture"

    # The denied frames did not poison sequence/capture history.
    valid = _request(gate, seq=2, captured_ms=1230, now_ms=1260)
    assert valid.offered
    assert gate.metrics()["denied"] == 2


def test_anonymous_offer_and_claim_percentiles_follow_host_clock() -> None:
    gate = _gate()
    first = _request(gate, seq=1, captured_ms=1000, now_ms=1020)
    assert first.offered and first.ticket is not None
    m = gate.metrics()
    assert m["observation_to_offer_p50_ms"] == 20
    assert m["observation_to_offer_p95_ms"] == 20
    assert m["observation_to_host_claim_p95_ms"] is None

    # A copied permit or a rejected host approval cannot inflate latency.
    copied = replace(first)
    assert not gate.claim_offered(
        copied, now_ms=1030, host_focus_and_permission=True,
    )
    assert not gate.claim_offered(
        first, now_ms=1040, host_focus_and_permission=False,
    )
    assert gate.metrics()["observation_to_host_claim_p95_ms"] is None

    assert gate.claim_offered(
        first, now_ms=1045, host_focus_and_permission=True,
    )
    assert gate.metrics()["observation_to_host_claim_p95_ms"] == 45
    assert gate.release(first.ticket, now_ms=1060, host_confirmed_released=True)

    second = _request(gate, seq=2, captured_ms=1240, now_ms=1280)
    assert second.offered and second.ticket is not None
    assert gate.claim_offered(
        second, now_ms=1305, host_focus_and_permission=True,
    )
    assert gate.release(second.ticket, now_ms=1320, host_confirmed_released=True)

    m = gate.metrics()
    assert m["observation_to_offer_p50_ms"] == 20
    assert m["observation_to_offer_p95_ms"] == 40
    assert m["observation_to_host_claim_p50_ms"] == 45
    assert m["observation_to_host_claim_p95_ms"] == 65
    assert "test_platformer" not in repr(m)
    assert "jump" not in repr(m)
    assert _DIGEST not in repr(m)


def test_expired_unclaimed_permit_does_not_fake_a_dispatched_action() -> None:
    gate = _gate()
    permit = _request(gate, seq=1, captured_ms=1000, now_ms=1020)
    assert permit.offered and permit.ticket is not None
    assert not gate.claim_offered(
        permit, now_ms=1200, host_focus_and_permission=True,
    )
    assert gate.metrics()["observation_to_host_claim_p95_ms"] is None
    assert gate.metrics()["observation_to_offer_p95_ms"] == 20
    assert gate.release(permit.ticket, now_ms=1210,
                        host_confirmed_released=True)


def test_unverified_frames_do_not_modify_capture_or_latency_history() -> None:
    gate = _gate()
    refused = _request(
        gate, seq=30, captured_ms=1000, now_ms=1020, host_verified=False,
    )
    assert refused.reason == "trusted_observation_missing"
    assert gate.metrics()["observation_to_offer_p95_ms"] is None
    assert _request(gate, seq=1, captured_ms=1000, now_ms=1020).offered


def test_next_episode_resets_latency_samples_and_capture_state() -> None:
    gate = _gate()
    permit = _request(gate, seq=8, captured_ms=1000, now_ms=1020)
    assert permit.ticket is not None
    assert gate.release(permit.ticket, now_ms=1040, host_confirmed_released=True)
    gate.revoke()
    gate.start(
        GameScope("test_platformer", "build1", "run2"),
        ("jump",), owner_approved=True,
    )
    measurements = gate.metrics()
    assert measurements["observation_to_offer_p95_ms"] is None
    assert measurements["observation_to_host_claim_p95_ms"] is None
    assert measurements["enabled"] is True
