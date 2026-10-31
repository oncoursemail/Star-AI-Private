"""Synthetic offline acceptance tests. Game outcomes are NOT live play results."""
from dataclasses import FrozenInstanceError
from dataclasses import replace

import pytest

from star.game_skill_gate import GamePerformanceTrial, compare_game_skill


def cases(*, split="holdout", mode="realtime", win=False, delay=80.0):
    return [
        GamePerformanceTrial(
            case_id=f"trial_{i}", game_scope="platformer_v1",
            scenario_id=f"map_{i % 3}", seed=i, split=split,
            mode=mode, success=win, progress=0.4 if not win else 1.0,
            action_delay_ms=delay, host_verified=True,
        )
        for i in range(24)
    ]


def test_offline_heldout_skill_gain_qualifies_without_speaking_or_tool_actions():
    baseline = cases()
    candidate = [replace(t, progress=0.55, success=True) if i % 4 == 0
                 else t for i, t in enumerate(baseline)]
    verdict = compare_game_skill(baseline, candidate)
    assert verdict.eligible and verdict.reasons == ()
    assert verdict.matched_holdouts == 24
    assert verdict.candidate_wins == 6
    assert verdict.baseline_wins == 0
    assert verdict.evidence == "host_attested_not_cryptographic_proof"


def test_unverified_host_result_is_rejected_even_when_score_is_better():
    baseline = cases()
    candidate = [replace(t, progress=1.0) for t in baseline]
    candidate[0] = replace(candidate[0], host_verified=False)
    v = compare_game_skill(baseline, candidate)
    assert not v.eligible and v.reasons == ("invalid_evidence",)


def test_match_exact_seed_case_and_control_mode():
    baseline = cases()
    candidate = [replace(t, progress=0.9) for t in baseline]
    candidate[-1] = replace(candidate[-1], seed=999)
    assert compare_game_skill(baseline, candidate).reasons == ("unmatched_holdouts",)
    candidate = [replace(t, progress=0.9, mode="paused") for t in baseline]
    assert compare_game_skill(baseline, candidate).reasons == ("unmatched_holdouts",)


def test_paused_improvement_cannot_claim_realtime_skill():
    original = cases(mode="paused")
    improved = [replace(t, success=True, progress=1.0) for t in original]
    assert compare_game_skill(original, improved).eligible is False
    assert compare_game_skill(original, improved, mode="paused").eligible is True


def test_new_failure_blocks_an_aggregate_gain():
    baseline = cases()
    baseline[0] = replace(baseline[0], success=True, progress=1.0)
    candidate = [replace(t, progress=1.0) for t in baseline]
    candidate[0] = replace(candidate[0], success=False, progress=0.2)
    v = compare_game_skill(baseline, candidate)
    assert not v.eligible and "new_failures" in v.reasons


def test_normalized_progress_regression_blocks_more_successes():
    baseline = cases()
    candidate = [replace(t, success=True, progress=1.0) for t in baseline]
    candidate[3] = replace(candidate[3], success=False, progress=0.3)
    v = compare_game_skill(baseline, candidate)
    assert not v.eligible and "progress_regression" in v.reasons


def test_paired_scenario_guard_blocks_hidden_local_regression():
    # Every case loses less than the old 2.5-point per-case tolerance on
    # map_0, while other maps gain enough to improve the overall average.
    # A supposedly smarter student must not silently forget a whole map.
    baseline = cases()
    candidate = [
        replace(t, progress=0.38) if t.scenario_id == "map_0"
        else replace(t, progress=0.85) if t.scenario_id == "map_1"
        else t for t in baseline
    ]
    verdict = compare_game_skill(baseline, candidate)
    assert not verdict.eligible
    assert "scenario_progress_regression" in verdict.reasons
    assert "progress_regression" not in verdict.reasons


def test_scenario_guard_preserves_real_cross_map_gain():
    baseline = cases()
    candidate = [
        replace(t, progress=0.53) if t.scenario_id in {"map_0", "map_1"}
        else t for t in baseline
    ]
    verdict = compare_game_skill(baseline, candidate)
    assert verdict.eligible
    assert "scenario_progress_regression" not in verdict.reasons


def test_zero_gain_is_not_an_intelligence_improvement():
    same = cases()
    v = compare_game_skill(same, tuple(reversed(same)))
    assert not v.eligible and v.reasons == ("no_verified_improvement",)


def test_p95_action_delay_improvement_counts_when_success_holds():
    baseline = cases(delay=100.0)
    candidate = [replace(t, action_delay_ms=70.0) for t in baseline]
    v = compare_game_skill(baseline, candidate)
    assert v.eligible and v.baseline_p95_action_delay_ms == 100
    assert v.candidate_p95_action_delay_ms == 70


def test_latency_tail_regression_blocks_even_when_game_score_improves():
    baseline = cases(delay=100.0)
    candidate = [replace(t, success=True, progress=1.0, action_delay_ms=150.0)
                 for t in baseline]
    v = compare_game_skill(baseline, candidate)
    assert not v.eligible and "p95_action_delay_regression" in v.reasons


def test_one_extreme_delay_cannot_hide_outside_p95():
    baseline = cases(delay=100.0)
    candidate = [replace(t, progress=0.9) for t in baseline]
    candidate[0] = replace(candidate[0], action_delay_ms=600.0)
    v = compare_game_skill(baseline, candidate)
    assert not v.eligible and "severe_action_delay_regression" in v.reasons


def test_training_holdout_seed_leakage_fails_closed():
    baseline = cases()
    candidate = [replace(t, progress=1.0) for t in baseline]
    # Different case ID and control mode do not justify seeing a secret map
    # and seed as practice material before holdout qualification.
    candidate.append(replace(candidate[0], case_id="leaked",
                             split="practice", mode="paused"))
    v = compare_game_skill(baseline, candidate)
    assert not v.eligible and v.reasons == ("invalid_evidence",)


def test_duplicate_case_and_unverified_trial_fail_closed():
    baseline = cases()
    candidate = [replace(t, progress=0.8) for t in baseline]
    assert compare_game_skill(baseline + [baseline[0]], candidate).reasons == (
        "invalid_evidence",)
    assert compare_game_skill(baseline, candidate + [candidate[0]]).reasons == (
        "invalid_evidence",)


def test_too_few_or_one_scenario_is_not_credible():
    original = cases()
    improved = [replace(t, progress=1.0) for t in original]
    assert "insufficient_unseen_scenarios" in compare_game_skill(
        original[:10], improved[:10]).reasons
    one = [replace(t, scenario_id="same_map") for t in original]
    assert "insufficient_unseen_scenarios" in compare_game_skill(
        one, [replace(t, progress=0.9) for t in one]).reasons


@pytest.mark.parametrize("value,field", [
    (float("nan"), "progress"), (float("inf"), "action_delay_ms"),
    (True, "action_delay_ms"), (-1, "action_delay_ms"),
    (1.1, "progress"), ("oops", "progress"),
])
def test_metrics_are_finite_and_bounded(value, field):
    with pytest.raises(ValueError):
        replace(cases()[0], **{field: value})


@pytest.mark.parametrize("field,value", [
    ("case_id", "hello from viewer"), ("game_scope", "../private"),
    ("scenario_id", ""), ("seed", True), ("seed", 2**32),
    ("success", 1), ("host_verified", 1),
    ("split", "evaluation"), ("mode", "game"),
])
def test_trial_cannot_hold_arbitrary_text_or_implicit_evidence(field, value):
    with pytest.raises(ValueError):
        replace(cases()[0], **{field: value})


def test_readonly_report_and_invalid_settings():
    trial = cases()[0]
    with pytest.raises(FrozenInstanceError):
        trial.success = True
    verdict = compare_game_skill(cases(), [replace(t, progress=0.9) for t in cases()])
    with pytest.raises(FrozenInstanceError):
        verdict.eligible = True
    with pytest.raises(ValueError):
        compare_game_skill(cases(), cases(), min_holdouts=True)
    with pytest.raises(ValueError):
        compare_game_skill(cases(), cases(), mode="wrong")


def test_empty_or_unbounded_evidence_never_qualifies():
    assert compare_game_skill([], []).eligible is False
    assert "invalid_evidence" in compare_game_skill(
        [None], cases()).reasons
    assert "invalid_evidence" in compare_game_skill(
        cases() * 100, cases()).reasons
