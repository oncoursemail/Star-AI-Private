"""Tests for session-clustered STAR turn-policy uncertainty."""
from dataclasses import replace

import pytest

from star.stream_turntaking_cluster import (
    evaluate_clustered_turn_policy,
    minimum_groups_for_zero_event_incidence,
)
from star.stream_turntaking_eval import (
    EndOfTurnScore,
    PauseKind,
    SilenceSpan,
    TurnPolicy,
)


def make_turn(prefix, index, *, hold_duration=500, false_hold=False):
    turn_id = f"{prefix}-turn-{index}"
    hold_scores = (
        (EndOfTurnScore(100, 0.10), EndOfTurnScore(250, 0.90))
        if false_hold
        else (EndOfTurnScore(100, 0.10), EndOfTurnScore(250, 0.10))
    )
    hold = SilenceSpan(
        span_id=f"{prefix}-hold-{index}",
        turn_id=turn_id,
        environment_id="cluster-test-v1",
        kind=PauseKind.HOLD,
        duration_ms=hold_duration,
        scores=hold_scores,
    )
    final = SilenceSpan(
        span_id=f"{prefix}-final-{index}",
        turn_id=turn_id,
        environment_id="cluster-test-v1",
        kind=PauseKind.END_OF_TURN,
        duration_ms=1200,
        scores=(EndOfTurnScore(300, 0.95),),
    )
    return hold, final


def clustered_dataset():
    rows = []
    groups = {}
    rows.extend(make_turn("rare", 0, false_hold=True))
    groups["rare-turn-0"] = "rare-session"
    for index in range(100):
        rows.extend(make_turn("many", index, false_hold=False))
        groups[f"many-turn-{index}"] = "many-session"
    return rows, groups


def test_cluster_bootstrap_exposes_session_concentration_hidden_by_pooled_rate():
    rows, groups = clustered_dataset()
    metrics = evaluate_clustered_turn_policy(
        rows,
        TurnPolicy(0.8, 200, 900),
        group_ids_by_turn=groups,
        bootstrap_replicates=500,
        random_seed=17,
    )
    assert metrics.pooled_false_cutoff_rate == pytest.approx(1 / 101)
    assert metrics.false_cutoff_session_incidence == pytest.approx(0.5)
    assert metrics.false_cutoff_session_count == 1
    assert metrics.sessions_with_hold_pauses == 2
    assert metrics.bootstrap_false_cutoff_rate_upper_bound > metrics.pooled_false_cutoff_rate


def test_cluster_bootstrap_is_deterministic_for_a_fixed_seed():
    rows, groups = clustered_dataset()
    kwargs = {
        "group_ids_by_turn": groups,
        "bootstrap_replicates": 300,
        "random_seed": 42,
    }
    first = evaluate_clustered_turn_policy(rows, TurnPolicy(0.8, 200, 900), **kwargs)
    second = evaluate_clustered_turn_policy(rows, TurnPolicy(0.8, 200, 900), **kwargs)
    assert first == second


def test_sessions_without_hold_pauses_remain_in_missed_turn_denominator():
    rows = []
    groups = {}
    rows.extend(make_turn("active", 0, false_hold=False))
    groups["active-turn-0"] = "active-session"
    final_only = make_turn("quiet", 0, false_hold=False)[1]
    rows.append(replace(final_only, span_id="quiet-final-0", turn_id="quiet-turn-0"))
    groups["quiet-turn-0"] = "quiet-session"
    metrics = evaluate_clustered_turn_policy(
        rows,
        TurnPolicy(0.8, 200, 900),
        group_ids_by_turn=groups,
        bootstrap_replicates=200,
    )
    assert metrics.session_count == 2
    assert metrics.sessions_with_hold_pauses == 1
    assert metrics.final_turn_count == 2


def test_zero_error_session_count_requirement_is_derived_from_confidence_and_budget():
    assert minimum_groups_for_zero_event_incidence(0.05, 0.95) == 52
    assert minimum_groups_for_zero_event_incidence(0.10, 0.95) < 52
    assert minimum_groups_for_zero_event_incidence(0.0, 0.95) is None


@pytest.mark.parametrize("rate", [True, -0.1, 1.1, float("nan"), float("inf")])
def test_invalid_session_incidence_budget_is_rejected(rate):
    with pytest.raises(ValueError):
        minimum_groups_for_zero_event_incidence(rate, 0.95)


def test_group_mapping_must_be_exact_and_opaque():
    rows, groups = clustered_dataset()
    policy = TurnPolicy(0.8, 200, 900)
    missing = dict(groups)
    missing.pop("rare-turn-0")
    with pytest.raises(ValueError, match="exactly"):
        evaluate_clustered_turn_policy(rows, policy, group_ids_by_turn=missing)
    invalid = dict(groups)
    invalid["rare-turn-0"] = "viewer name with spaces"
    with pytest.raises(ValueError, match="opaque"):
        evaluate_clustered_turn_policy(rows, policy, group_ids_by_turn=invalid)


def test_no_raw_group_identifiers_are_returned():
    rows, groups = clustered_dataset()
    metrics = evaluate_clustered_turn_policy(
        rows,
        TurnPolicy(0.8, 200, 900),
        group_ids_by_turn=groups,
        bootstrap_replicates=200,
    )
    serialized = repr(metrics)
    assert "rare-session" not in serialized
    assert "many-session" not in serialized
    assert "rare-turn" not in serialized
