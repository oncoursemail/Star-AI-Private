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



def test_new_sequence_cannot_use_older_observation_snapshot():
    g = gate(age_ms=250.0)
    assert g.assess(signal(seq=1, observed=100.10, decided=100.11),
                    now_s=100.13).fresh
    out_of_order = g.assess(
        signal(seq=2, observed=100.09, decided=100.14), now_s=100.15,
    )
    assert out_of_order.reason == "out_of_order_observation"
    assert g.metrics()["out_of_order_observation"] == 1
    assert g.assess(signal(seq=2, observed=100.16, decided=100.17),
                    now_s=100.18).fresh


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


def test_higher_sequence_with_same_capture_time_is_not_a_new_scene():
    g = gate()
    assert g.assess(signal(seq=1, observed=100.0, decided=100.01),
                    now_s=100.02).fresh
    duplicate_capture = g.assess(
        signal(seq=2, observed=100.0, decided=100.03), now_s=100.04,
    )
    assert not duplicate_capture.fresh
    assert duplicate_capture.reason == "out_of_order_observation"
    assert g.metrics()["accepted_samples"] == 1
    # The rejected duplicate does not poison sequence or capture history.
    assert g.assess(signal(seq=2, observed=100.05, decided=100.06),
                    now_s=100.07).fresh


def test_pre_dispatch_percentiles_separate_model_and_queue_delay():
    g = gate()
    for sequence, observed, decided, assessment in (
        (1, 100.0, 100.01, 100.02),
        (2, 100.3, 100.33, 100.34),
        (3, 100.6, 100.64, 100.66),
    ):
        assert g.assess(
            signal(seq=sequence, observed=observed, decided=decided),
            now_s=assessment,
        ).fresh
    stats = g.metrics()
    assert stats["accepted_samples"] == 3
    assert stats["capture_to_assessment_p50_ms"] == pytest.approx(40.0)
    assert stats["capture_to_assessment_p95_ms"] == pytest.approx(60.0)
    assert stats["capture_to_decision_p50_ms"] == pytest.approx(30.0)
    assert stats["capture_to_decision_p95_ms"] == pytest.approx(40.0)
    assert stats["decision_to_assessment_p50_ms"] == pytest.approx(10.0)
    assert stats["decision_to_assessment_p95_ms"] == pytest.approx(20.0)
    assert "stream_01" not in repr(stats)
    assert "platformer_v1" not in repr(stats)


def test_denials_do_not_fabricate_latency_samples():
    g = gate(age_ms=200.0)
    assert g.metrics()["capture_to_assessment_p95_ms"] is None
    assert g.assess(signal(verified=False), now_s=100.1).reason == "unverified"
    assert g.assess(signal(scope="wrong"), now_s=100.1).reason == "wrong_session"
    assert g.assess(signal(seq=1), now_s=100.1).fresh
    assert g.assess(signal(seq=1), now_s=100.12).reason == "replayed"
    assert g.assess(signal(seq=2, observed=100.12, decided=100.15),
                    now_s=100.4).reason == "stale"
    assert g.metrics()["accepted_samples"] == 1
    assert g.metrics()["capture_to_assessment_p95_ms"] == pytest.approx(100.0)


def test_episode_change_clears_pre_dispatch_latency_history():
    g = gate()
    assert g.assess(signal(), now_s=100.1).fresh
    assert g.metrics()["accepted_samples"] == 1
    g.disable()
    assert g.metrics()["accepted_samples"] == 0
    assert g.metrics()["capture_to_assessment_p95_ms"] is None
    g.enable(owner_approved=True, session_id="stream_02", game_scope="platformer_v2")
    assert g.metrics()["capture_to_decision_p50_ms"] is None
    assert g.assess(
        signal(session="stream_02", scope="platformer_v2"), now_s=100.1,
    ).fresh
    assert g.metrics()["accepted_samples"] == 1


def test_latency_history_stays_bounded_after_many_accepted_scenes():
    g = gate()
    for seq in range(1, 101):
        t = 100.0 + seq
        assert g.assess(
            signal(seq=seq, observed=t, decided=t + 0.01),
            now_s=t + 0.02,
        ).fresh
    metrics = g.metrics()
    assert metrics["allowed"] == 100
    assert metrics["accepted_samples"] == 64
    assert metrics["capture_to_assessment_p95_ms"] == pytest.approx(20.0)
