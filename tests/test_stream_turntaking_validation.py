"""Regression tests for leakage-resistant STAR turn-policy validation."""
from dataclasses import replace

import pytest

from star.stream_turntaking_eval import EndOfTurnScore, PauseKind, SilenceSpan
from star.stream_turntaking_validation import (
    TurnPolicyConstraints,
    ValidationStatus,
    _wilson_upper,
    select_and_validate_turn_policy,
)


def make_turn(prefix, index, *, hold_duration=500, final_horizon=1200):
    turn_id = f"{prefix}-turn-{index}"
    hold = SilenceSpan(
        span_id=f"{prefix}-hold-{index}",
        turn_id=turn_id,
        environment_id="private-rehearsal-v1",
        kind=PauseKind.HOLD,
        duration_ms=hold_duration,
        scores=(
            EndOfTurnScore(100, 0.10),
            EndOfTurnScore(250, 0.90),
            EndOfTurnScore(400, 0.20),
        ),
    )
    final = SilenceSpan(
        span_id=f"{prefix}-final-{index}",
        turn_id=turn_id,
        environment_id="private-rehearsal-v1",
        kind=PauseKind.END_OF_TURN,
        duration_ms=final_horizon,
        scores=(
            EndOfTurnScore(100, 0.10),
            EndOfTurnScore(300, 0.85),
            EndOfTurnScore(600, 0.95),
        ),
    )
    return hold, final


def dataset(prefix, count=100, **kwargs):
    rows = [span for index in range(count) for span in make_turn(prefix, index, **kwargs)]
    groups = {
        f"{prefix}-turn-{index}": f"{prefix}-session-{index}"
        for index in range(count)
    }
    return rows, groups


def run(calibration, holdout, groups, **kwargs):
    return select_and_validate_turn_policy(
        calibration,
        holdout,
        group_ids_by_turn=groups,
        thresholds=kwargs.pop("thresholds", (0.8, 0.94)),
        action_delays_ms=kwargs.pop("action_delays_ms", (200, 350)),
        timeouts_ms=kwargs.pop("timeouts_ms", (900, 1000)),
        constraints=kwargs.pop("constraints", TurnPolicyConstraints()),
    )


def test_policy_is_selected_on_calibration_and_passes_independent_holdout():
    calibration, cal_groups = dataset("cal")
    holdout, hold_groups = dataset("hold")
    result = run(calibration, holdout, {**cal_groups, **hold_groups})
    assert result.status is ValidationStatus.PASS
    assert result.selected_policy is not None
    assert result.calibration_metrics is not None
    assert result.holdout_metrics is not None
    assert result.holdout_silence_baseline is not None
    assert result.calibration_policy_count == 8
    assert result.calibration_eligible_count > 0
    assert result.holdout_metrics.false_cutoffs == 0
    assert result.holdout_metrics.missed_final_turns == 0
    assert result.holdout_silence_baseline.false_cutoffs == 100
    assert result.holdout_false_cutoff_upper_bound is not None
    assert result.holdout_false_cutoff_upper_bound <= 0.05


def test_holdout_regression_is_not_hidden_by_good_calibration():
    calibration, cal_groups = dataset("cal")
    holdout, hold_groups = dataset("hold", hold_duration=1200)
    result = run(calibration, holdout, {**cal_groups, **hold_groups})
    assert result.status is ValidationStatus.FAIL
    assert result.calibration_metrics is not None
    assert result.holdout_metrics is not None
    assert result.holdout_metrics.false_cutoffs == 100
    assert result.holdout_false_cutoff_upper_bound == 1.0


def test_too_small_calibration_never_selects_or_consumes_holdout():
    calibration, cal_groups = dataset("cal", 20)
    holdout, hold_groups = dataset("hold")
    result = run(
        calibration,
        holdout,
        {**cal_groups, **hold_groups},
        constraints=TurnPolicyConstraints(min_hold_pauses=50, min_final_turns=50),
    )
    assert result.status is ValidationStatus.INSUFFICIENT_CALIBRATION
    assert result.selected_policy is None
    assert result.holdout_metrics is None
    assert result.calibration_policy_count == 0


def test_too_small_holdout_is_inconclusive_even_when_point_estimates_are_good():
    calibration, cal_groups = dataset("cal")
    holdout, hold_groups = dataset("hold", 20)
    result = run(
        calibration,
        holdout,
        {**cal_groups, **hold_groups},
        constraints=TurnPolicyConstraints(min_hold_pauses=50, min_final_turns=50),
    )
    assert result.status is ValidationStatus.INCONCLUSIVE_HOLDOUT
    assert result.holdout_metrics is not None


def test_no_calibration_policy_meets_predeclared_latency_limit():
    calibration, cal_groups = dataset("cal")
    holdout, hold_groups = dataset("hold")
    result = run(
        calibration,
        holdout,
        {**cal_groups, **hold_groups},
        thresholds=(0.999,),
        action_delays_ms=(200,),
        timeouts_ms=(1000,),
        constraints=TurnPolicyConstraints(max_p95_latency_ms=500),
    )
    assert result.status is ValidationStatus.NO_CALIBRATION_CANDIDATE
    assert result.selected_policy is None
    assert result.holdout_metrics is None


def test_turn_ids_cannot_appear_in_both_partitions():
    calibration, cal_groups = dataset("cal", 2)
    holdout, hold_groups = dataset("hold", 2)
    holdout[0] = replace(holdout[0], turn_id="cal-turn-0")
    holdout[1] = replace(holdout[1], turn_id="cal-turn-0")
    groups = {**cal_groups, **hold_groups}
    groups.pop("hold-turn-0")
    groups["cal-turn-0"] = "cal-session-0"
    with pytest.raises(ValueError, match="turn IDs must be disjoint"):
        run(calibration, holdout, groups)


def test_span_ids_cannot_appear_in_both_partitions():
    calibration, cal_groups = dataset("cal", 2)
    holdout, hold_groups = dataset("hold", 2)
    holdout[0] = replace(holdout[0], span_id=calibration[0].span_id)
    with pytest.raises(ValueError, match="span IDs must be disjoint"):
        run(calibration, holdout, {**cal_groups, **hold_groups})


def test_conversation_groups_cannot_leak_across_partitions():
    calibration, cal_groups = dataset("cal", 2)
    holdout, hold_groups = dataset("hold", 2)
    hold_groups["hold-turn-0"] = "cal-session-0"
    with pytest.raises(ValueError, match="groups must be disjoint"):
        run(calibration, holdout, {**cal_groups, **hold_groups})


def test_missing_or_extra_group_mapping_is_rejected():
    calibration, cal_groups = dataset("cal", 2)
    holdout, hold_groups = dataset("hold", 2)
    groups = {**cal_groups, **hold_groups}
    groups.pop("cal-turn-0")
    with pytest.raises(ValueError, match="exactly the supplied"):
        run(calibration, holdout, groups)


def test_invalid_group_identifier_is_rejected():
    calibration, cal_groups = dataset("cal", 2)
    holdout, hold_groups = dataset("hold", 2)
    groups = {**cal_groups, **hold_groups}
    groups["cal-turn-0"] = "raw viewer name with spaces"
    with pytest.raises(ValueError, match="opaque IDs"):
        run(calibration, holdout, groups)


def test_grouped_turns_are_allowed_within_one_partition():
    calibration, cal_groups = dataset("cal", 2)
    holdout, hold_groups = dataset("hold", 2)
    cal_groups["cal-turn-1"] = cal_groups["cal-turn-0"]
    result = run(calibration, holdout, {**cal_groups, **hold_groups})
    assert result.status is ValidationStatus.PASS


def test_calibration_and_holdout_can_share_environment_label():
    calibration, cal_groups = dataset("cal", 2)
    holdout, hold_groups = dataset("hold", 2)
    result = run(calibration, holdout, {**cal_groups, **hold_groups})
    assert result.status is ValidationStatus.PASS


def test_wilson_upper_bound_is_conservative_for_zero_observed_errors():
    upper = _wilson_upper(0, 100, 0.95)
    assert 0.02 < upper < 0.05


@pytest.mark.parametrize("value", [True, -0.1, 1.1, float("nan"), float("inf"), "0.5"])
def test_invalid_rate_constraints_are_rejected(value):
    with pytest.raises(ValueError):
        TurnPolicyConstraints(max_false_cutoff_rate=value)


@pytest.mark.parametrize("value", [True, 0, -1, 120001, 1.5])
def test_invalid_latency_limit_is_rejected(value):
    with pytest.raises(ValueError):
        TurnPolicyConstraints(max_p95_latency_ms=value)


@pytest.mark.parametrize("value", [True, 0, -1, 20001])
def test_invalid_minimum_sample_counts_are_rejected(value):
    with pytest.raises(ValueError):
        TurnPolicyConstraints(min_hold_pauses=value)


@pytest.mark.parametrize("value", [True, 0.5, 1.0, float("nan"), "0.95"])
def test_invalid_confidence_level_is_rejected(value):
    with pytest.raises(ValueError):
        TurnPolicyConstraints(confidence_level=value)


def test_invalid_or_empty_partition_is_rejected():
    calibration, cal_groups = dataset("cal", 2)
    holdout, hold_groups = dataset("hold", 2)
    with pytest.raises(ValueError, match="1..20000"):
        run([], holdout, {**cal_groups, **hold_groups})


def test_policy_selection_is_deterministic_when_calibration_rows_are_reordered():
    calibration, cal_groups = dataset("cal")
    holdout, hold_groups = dataset("hold")
    groups = {**cal_groups, **hold_groups}
    first = run(calibration, holdout, groups)
    second = run(list(reversed(calibration)), list(reversed(holdout)), groups)
    assert first == second


def test_holdout_is_not_evaluated_when_no_candidate_is_eligible():
    calibration, cal_groups = dataset("cal")
    holdout, hold_groups = dataset("hold")
    result = run(
        calibration,
        holdout,
        {**cal_groups, **hold_groups},
        thresholds=(0.999,),
        action_delays_ms=(200,),
        timeouts_ms=(1000,),
        constraints=TurnPolicyConstraints(max_p95_latency_ms=500),
    )
    assert result.holdout_metrics is None
    assert result.holdout_silence_baseline is None


def test_probe_requires_hold_and_final_spans_in_each_partition():
    calibration, cal_groups = dataset("cal", 2)
    holdout, hold_groups = dataset("hold", 2)
    calibration = [span for span in calibration if span.kind is PauseKind.HOLD]
    with pytest.raises(ValueError, match="both hold"):
        run(calibration, holdout, {**cal_groups, **hold_groups})


def test_selected_policy_uses_model_scores_not_silence_baseline():
    calibration, cal_groups = dataset("cal")
    holdout, hold_groups = dataset("hold")
    result = run(calibration, holdout, {**cal_groups, **hold_groups})
    assert result.selected_policy is not None
    assert result.calibration_metrics is not None
    assert result.calibration_metrics.threshold is not None
    assert result.holdout_metrics is not None
    assert result.holdout_metrics.score_source.value == "model"
    assert result.holdout_silence_baseline is not None
    assert result.holdout_silence_baseline.score_source.value == "silence_only"
