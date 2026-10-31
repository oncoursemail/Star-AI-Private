"""Deterministic offline checks for real-time game action age and replay rules."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import pytest

from star.game_action_freshness import GameActionFreshnessGate, GameActionTiming


def signal(*, seq: int = 1, observed: float = 100.0,
           decided: float = 100.05, verified: bool = True,
           scope: str = "platformer_v1", session: str = "stream_01") -> GameActionTiming:
    return GameActionTiming(
        session_id=session, game_scope=scope, observation_seq=seq,
        observed_at_s=observed, decided_at_s=decided, host_observed=verified,
    )


def gate(*, age_ms: float = 250.0) -> GameActionFreshnessGate:
    instance = GameActionFreshnessGate(max_observation_age_ms=age_ms)
    instance.enable(
        owner_approved=True, session_id="stream_01", game_scope="platformer_v1",
    )
    return instance


def test_off_by_default_and_owner_approval_required():
    g = GameActionFreshnessGate()
    assert not g.assess(signal(), now_s=100.1).fresh
    assert g.metrics()["enabled"] is False
    with pytest.raises(PermissionError):
        g.enable(owner_approved=1, session_id="stream_01", game_scope="platformer_v1")
    g.enable(owner_approved=True, session_id="stream_01", game_scope="platformer_v1")
    with pytest.raises(RuntimeError):
        g.enable(owner_approved=True, session_id="stream_02", game_scope="platformer_v1")
    verdict = g.assess(signal(), now_s=100.1)
    assert verdict.fresh and verdict.reason == "fresh"
    assert verdict.authorizes_game_input is False


def test_observation_age_includes_model_and_dispatch_queue_delays():
    g = gate(age_ms=200.0)
    assert g.assess(signal(seq=1, decided=100.05), now_s=100.19).fresh
    assert g.assess(signal(seq=2, decided=100.06), now_s=100.21).reason == "stale"
    # Even fast model generation cannot justify an old game observation.
    assert not g.assess(signal(seq=3, decided=100.19), now_s=100.4).fresh
    assert g.metrics()["stale"] == 2


def test_action_too_late_even_when_model_responded_quickly():
    g = gate(age_ms=250.0)
    timing = signal(observed=10.0, decided=10.01)
    assert g.assess(timing, now_s=11.0).reason == "stale"


def test_future_decision_and_reversed_host_clock_fail_closed():
    g = gate()
    assert g.assess(signal(), now_s=100.01).reason == "bad_clock"
    assert g.assess(signal(), now_s=100.1).fresh
    assert g.assess(signal(seq=2, observed=100.01, decided=100.02),
                    now_s=100.05).reason == "bad_clock"
    assert g.metrics()["bad_clock"] == 2


def test_replay_and_out_of_order_observations_are_rejected():
    g = gate()
    assert g.assess(signal(seq=3), now_s=100.1).fresh
    assert g.assess(signal(seq=3), now_s=100.15).reason == "replayed"
    assert g.assess(signal(seq=2), now_s=100.2).reason == "replayed"
    assert g.metrics()["replayed"] == 2


def test_no_chat_attestation_and_no_cross_game_or_cross_session_replay():
    g = gate()
    assert g.assess(signal(verified=False), now_s=999_999).reason == "unverified"
    assert g.assess(signal(scope="different_game"), now_s=999_999).reason == "wrong_session"
    assert g.assess(signal(session="another_session"), now_s=999_999).reason == "wrong_session"
    # Rejected claims did not poison the trusted session's clock.
    assert g.assess(signal(), now_s=100.1).fresh
    assert g.metrics()["allowed"] == 1


def test_disable_erases_replay_state_and_reenable_starts_fresh_session():
    g = gate()
    assert g.assess(signal(), now_s=100.1).fresh
    g.disable()
    assert g.assess(signal(), now_s=100.1).reason == "disabled"
    g.enable(owner_approved=True, session_id="stream_01", game_scope="platformer_v1")
    assert g.assess(signal(), now_s=100.1).fresh


def test_concurrent_duplicate_observations_admit_one_only():
    g = gate()
    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(
            lambda _: g.assess(signal(), now_s=100.1).fresh, range(64),
        ))
    assert sum(results) == 1


@pytest.mark.parametrize("kwargs", [
    {"session_id": "../escape"}, {"game_scope": "bad scope"},
    {"observation_seq": True}, {"observation_seq": -1},
    {"observation_seq": 2**63}, {"observed_at_s": True},
    {"observed_at_s": -1}, {"observed_at_s": float("nan")},
    {"decided_at_s": float("inf")}, {"decided_at_s": 99.9},
    {"host_observed": 1},
])
def test_timing_rejects_invalid_and_untrusted_types(kwargs):
    with pytest.raises(ValueError):
        replace(signal(), **kwargs)


@pytest.mark.parametrize("age", [-1, True, float("inf"), 0, 5001])
def test_invalid_action_age_budget_rejected(age):
    with pytest.raises(ValueError):
        GameActionFreshnessGate(max_observation_age_ms=age)


def test_bounded_no_private_data_metrics():
    g = gate()
    assert g.assess(signal(), now_s=100.1).fresh
    result = g.metrics()
    assert "stream_01" not in repr(result)
    assert "platformer_v1" not in repr(result)
    assert result["allowed"] == 1
