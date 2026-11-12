"""Regression tests for causal STAR turn-taking policy evaluation."""
import pytest

from star.stream_turntaking_eval import (
    EndOfTurnScore,
    PauseKind,
    ScoreSource,
    SilenceSpan,
    TurnPolicy,
    evaluate_turn_policy,
    pareto_frontier,
    sweep_turn_policies,
)


def make_turn(index, *, hold_duration=500, final_horizon=1200):
    hold = SilenceSpan(
        span_id=f"hold-{index}",
        turn_id=f"turn-{index}",
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
        span_id=f"final-{index}",
        turn_id=f"turn-{index}",
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


def dataset(count=30, **kwargs):
    return [span for index in range(count) for span in make_turn(index, **kwargs)]


def test_model_policy_counts_false_cutoff_and_detects_final_turn():
    result = evaluate_turn_policy(
        dataset(4),
        TurnPolicy(threshold=0.8, action_delay_ms=200, timeout_ms=1000),
    )
    assert result.false_cutoffs == 4
    assert result.false_cutoff_rate == 1.0
    assert result.detected_final_turns == 4
    assert result.missed_final_turns == 0
    assert result.p50_observed_latency_ms == 300


def test_action_delay_ignores_scores_before_the_delay():
    result = evaluate_turn_policy(
        dataset(2),
        TurnPolicy(threshold=0.8, action_delay_ms=350, timeout_ms=1000),
    )
    assert result.false_cutoffs == 2
    assert result.p50_observed_latency_ms == 600


def test_threshold_can_avoid_a_mid_turn_cutoff():
    result = evaluate_turn_policy(
        dataset(2),
        TurnPolicy(threshold=0.96, action_delay_ms=200, timeout_ms=1000),
    )
    assert result.false_cutoffs == 0
    assert result.detected_final_turns == 0
    assert result.missed_final_turns == 2


def test_timeout_detects_final_turn_even_without_a_high_score():
    result = evaluate_turn_policy(
        dataset(2),
        TurnPolicy(threshold=0.99, action_delay_ms=200, timeout_ms=900),
    )
    assert result.detected_final_turns == 2
    assert result.p50_observed_latency_ms == 900


def test_timeout_causes_false_cutoff_when_it_precedes_speech_resume():
    rows = dataset(1, hold_duration=1000)
    result = evaluate_turn_policy(
        rows,
        TurnPolicy(threshold=0.99, action_delay_ms=200, timeout_ms=800),
    )
    assert result.false_cutoffs == 1


def test_timeout_at_exact_hold_resume_boundary_does_not_cut_off():
    rows = dataset(1, hold_duration=800)
    result = evaluate_turn_policy(
        rows,
        TurnPolicy(threshold=0.99, action_delay_ms=200, timeout_ms=800),
    )
    assert result.false_cutoffs == 0


def test_final_turn_is_missed_when_observation_horizon_ends_before_timeout():
    rows = dataset(2, final_horizon=600)
    result = evaluate_turn_policy(
        rows,
        TurnPolicy(threshold=0.99, action_delay_ms=200, timeout_ms=900),
    )
    assert result.missed_final_turns == 2
    assert result.missed_final_rate == 1.0
    assert result.p95_observed_latency_ms == 600


def test_silence_only_baseline_is_evaluated_without_model_scores():
    result = evaluate_turn_policy(
        dataset(3),
        TurnPolicy(threshold=0.0, action_delay_ms=200, timeout_ms=1000),
        score_source=ScoreSource.SILENCE_ONLY,
    )
    assert result.score_source is ScoreSource.SILENCE_ONLY
    assert result.threshold is None
    assert result.false_cutoffs == 3
    assert result.p50_observed_latency_ms == 200


def test_model_score_after_timeout_is_ignored():
    rows = [
        SilenceSpan(
            span_id="h1",
            turn_id="t1",
            environment_id="env1",
            kind=PauseKind.HOLD,
            duration_ms=900,
            scores=(EndOfTurnScore(800, 1.0),),
        ),
        SilenceSpan(
            span_id="f1",
            turn_id="t1",
            environment_id="env1",
            kind=PauseKind.END_OF_TURN,
            duration_ms=1200,
            scores=(EndOfTurnScore(1100, 1.0),),
        ),
    ]
    result = evaluate_turn_policy(
        rows,
        TurnPolicy(threshold=0.5, action_delay_ms=100, timeout_ms=500),
    )
    assert result.false_cutoffs == 1  # The HOLD timeout itself fires at 500 ms.
    assert result.detected_final_turns == 1
    assert result.p50_observed_latency_ms == 500


def test_score_at_exact_hold_resume_time_is_not_a_false_cutoff():
    rows = [
        SilenceSpan(
            span_id="h1",
            turn_id="t1",
            environment_id="env1",
            kind=PauseKind.HOLD,
            duration_ms=300,
            scores=(EndOfTurnScore(300, 1.0),),
        ),
        SilenceSpan(
            span_id="f1",
            turn_id="t1",
            environment_id="env1",
            kind=PauseKind.END_OF_TURN,
            duration_ms=1000,
            scores=(EndOfTurnScore(300, 1.0),),
        ),
    ]
    result = evaluate_turn_policy(
        rows,
        TurnPolicy(threshold=0.5, action_delay_ms=100, timeout_ms=900),
    )
    assert result.false_cutoffs == 0


def test_final_score_at_observation_horizon_is_allowed():
    rows = [
        SilenceSpan("h1", "t1", "env1", PauseKind.HOLD, 300, ()),
        SilenceSpan(
            "f1", "t1", "env1", PauseKind.END_OF_TURN, 300,
            (EndOfTurnScore(300, 1.0),),
        ),
    ]
    result = evaluate_turn_policy(
        rows,
        TurnPolicy(threshold=0.5, action_delay_ms=100, timeout_ms=900),
    )
    assert result.detected_final_turns == 1
    assert result.p50_observed_latency_ms == 300


def test_sweep_contains_model_and_silence_baseline_operating_points():
    result = sweep_turn_policies(
        dataset(3),
        thresholds=(0.5, 0.9),
        action_delays_ms=(100, 250),
        timeouts_ms=(800,),
    )
    assert len(result.evaluations) == 6
    assert any(item.score_source is ScoreSource.SILENCE_ONLY for item in result.evaluations)
    assert result.pareto_frontier


def test_sweep_without_baseline_has_only_model_policies():
    result = sweep_turn_policies(
        dataset(2),
        thresholds=(0.5, 0.9),
        action_delays_ms=(100,),
        timeouts_ms=(800,),
        include_silence_baseline=False,
    )
    assert len(result.evaluations) == 2
    assert all(item.score_source is ScoreSource.MODEL for item in result.evaluations)


def test_pareto_frontier_removes_dominated_policy():
    result = sweep_turn_policies(
        dataset(5),
        thresholds=(0.5, 0.9, 0.99),
        action_delays_ms=(100, 300),
        timeouts_ms=(700, 1000),
    )
    frontier = result.pareto_frontier
    assert frontier
    for item in frontier:
        assert not any(
            other is not item
            and other.false_cutoff_rate <= item.false_cutoff_rate
            and other.p95_observed_latency_ms <= item.p95_observed_latency_ms
            and other.missed_final_rate <= item.missed_final_rate
            and (
                other.false_cutoff_rate < item.false_cutoff_rate
                or other.p95_observed_latency_ms < item.p95_observed_latency_ms
                or other.missed_final_rate < item.missed_final_rate
            )
            for other in result.evaluations
        )


def test_multiple_turns_are_aggregated_without_exposing_ids():
    result = evaluate_turn_policy(
        dataset(7),
        TurnPolicy(threshold=0.9, action_delay_ms=200, timeout_ms=1000),
    )
    assert result.turn_count == 7
    assert result.final_turn_count == 7
    assert "turn_id" not in result.__dataclass_fields__


def test_duplicate_span_ids_are_rejected():
    hold, final = make_turn(1)
    duplicate = SilenceSpan(
        hold.span_id, "turn-2", "private-rehearsal-v1",
        PauseKind.HOLD, 500, (),
    )
    with pytest.raises(ValueError, match="duplicate span_id"):
        evaluate_turn_policy([hold, final, duplicate], TurnPolicy(0.5, 100, 900))


def test_each_turn_requires_exactly_one_final_span():
    hold, final = make_turn(1)
    duplicate_final = SilenceSpan(
        "final-2", "turn-1", "private-rehearsal-v1",
        PauseKind.END_OF_TURN, 1200, (),
    )
    with pytest.raises(ValueError, match="exactly one"):
        evaluate_turn_policy(
            [hold, final, duplicate_final], TurnPolicy(0.5, 100, 900)
        )


def test_each_turn_must_use_one_environment():
    hold, final = make_turn(1)
    mismatched = SilenceSpan(
        final.span_id, final.turn_id, "different-env",
        final.kind, final.duration_ms, final.scores,
    )
    with pytest.raises(ValueError, match="share an environment"):
        evaluate_turn_policy([hold, mismatched], TurnPolicy(0.5, 100, 900))


def test_evaluation_requires_both_hold_and_final_examples():
    _, final = make_turn(1)
    with pytest.raises(ValueError, match="both hold"):
        evaluate_turn_policy([final], TurnPolicy(0.5, 100, 900))


def test_score_points_must_be_strictly_ordered():
    with pytest.raises(ValueError, match="strictly increasing"):
        SilenceSpan(
            "h1", "t1", "env1", PauseKind.HOLD, 500,
            (EndOfTurnScore(200, 0.2), EndOfTurnScore(200, 0.8)),
        )


def test_score_point_cannot_exceed_observed_span():
    with pytest.raises(ValueError, match="exceeds"):
        SilenceSpan(
            "h1", "t1", "env1", PauseKind.HOLD, 100,
            (EndOfTurnScore(101, 0.8),),
        )


@pytest.mark.parametrize("score", [True, -0.1, 1.1, float("nan"), float("inf"), "0.5"])
def test_invalid_scores_are_rejected(score):
    with pytest.raises(ValueError):
        EndOfTurnScore(100, score)


@pytest.mark.parametrize("threshold", [True, -0.1, 1.1, float("nan"), float("inf")])
def test_invalid_thresholds_are_rejected(threshold):
    with pytest.raises(ValueError):
        TurnPolicy(threshold, 100, 900)


@pytest.mark.parametrize(
    "delay,timeout",
    [(True, 900), (-1, 900), (100, 0), (1000, 900), (100, True)],
)
def test_invalid_policy_times_are_rejected(delay, timeout):
    with pytest.raises(ValueError):
        TurnPolicy(0.5, delay, timeout)


def test_policy_grid_limit_is_enforced():
    with pytest.raises(ValueError, match="256 combinations"):
        sweep_turn_policies(
            dataset(1),
            thresholds=tuple(i / 10 for i in range(10)),
            action_delays_ms=tuple(range(10)),
            timeouts_ms=tuple(range(100, 130)),
        )


def test_empty_sweep_dimensions_are_rejected():
    with pytest.raises(ValueError, match="thresholds"):
        sweep_turn_policies(
            dataset(1), thresholds=(), action_delays_ms=(100,), timeouts_ms=(900,)
        )


def test_sweep_is_deterministic_and_order_independent():
    rows = dataset(4)
    first = sweep_turn_policies(
        rows, thresholds=(0.5, 0.9), action_delays_ms=(100, 250),
        timeouts_ms=(800, 1000),
    )
    second = sweep_turn_policies(
        list(reversed(rows)), thresholds=(0.5, 0.9), action_delays_ms=(100, 250),
        timeouts_ms=(800, 1000),
    )
    assert first == second


def test_hold_timeout_that_fires_before_resume_is_counted_even_without_scores():
    rows = [
        SilenceSpan("h1", "t1", "env1", PauseKind.HOLD, 700, ()),
        SilenceSpan("f1", "t1", "env1", PauseKind.END_OF_TURN, 1000, ()),
    ]
    result = evaluate_turn_policy(
        rows, TurnPolicy(0.8, 100, 500), score_source=ScoreSource.MODEL
    )
    assert result.false_cutoffs == 1


def test_frontier_rejects_empty_or_invalid_inputs():
    with pytest.raises(ValueError):
        pareto_frontier([])
    with pytest.raises(TypeError):
        pareto_frontier([object()])
