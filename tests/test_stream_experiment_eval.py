"""Regression tests for paired STAR speed/quality experiments."""
import pytest

from star.stream_experiment_eval import (
    ExperimentObservation,
    ExperimentPolicy,
    LatencyMetric,
    QualityEvidence,
    Variant,
    evaluate_experiment,
)


def make_pair(
    index,
    *,
    base_latency=250.0,
    candidate_latency=200.0,
    base_quality=0.9,
    candidate_quality=0.9,
    base_frame=16.7,
    candidate_frame=16.0,
    base_underruns=0,
    candidate_underruns=0,
    include_frame=True,
    include_audio=True,
):
    common = {
        "pair_id": f"pair-{index}",
        "task_id": f"task-{index}",
        "environment_id": "same-hardware-game-build",
        "quality_evidence": QualityEvidence.HELD_OUT_TEST,
    }
    baseline = ExperimentObservation(
        **common,
        variant=Variant.BASELINE,
        quality_score=base_quality,
        first_content_ms=base_latency * 0.5,
        first_audible_ms=base_latency,
        inter_token_ms=25.0,
        request_ms=base_latency * 4,
        game_frame_p99_ms=base_frame if include_frame else None,
        audio_underrun_chunks=base_underruns if include_audio else None,
        audio_playback_chunks=1_000 if include_audio else None,
    )
    candidate = ExperimentObservation(
        **common,
        variant=Variant.CANDIDATE,
        quality_score=candidate_quality,
        first_content_ms=candidate_latency * 0.5,
        first_audible_ms=candidate_latency,
        inter_token_ms=20.0,
        request_ms=candidate_latency * 4,
        game_frame_p99_ms=candidate_frame if include_frame else None,
        audio_underrun_chunks=candidate_underruns if include_audio else None,
        audio_playback_chunks=1_000 if include_audio else None,
    )
    return baseline, candidate


def observations(count=30, **kwargs):
    return [item for index in range(count) for item in make_pair(index, **kwargs)]


def policy(**kwargs):
    return ExperimentPolicy(bootstrap_replicates=500, **kwargs)


def test_faster_candidate_with_noninferior_quality_is_improved():
    result = evaluate_experiment("exp-1", observations(), policy())
    assert result["decision"] == "IMPROVED"
    assert result["pair_count"] == 30


def test_speed_gain_cannot_hide_a_clear_quality_regression():
    result = evaluate_experiment("exp-2", observations(candidate_quality=0.7), policy())
    assert result["decision"] == "REGRESSION"
    assert result["gates"][0]["status"] == "FAIL"


def test_candidate_that_is_confidently_slower_is_a_regression():
    result = evaluate_experiment("exp-3", observations(candidate_latency=320.0), policy())
    assert result["decision"] == "REGRESSION"
    assert result["gates"][1]["status"] == "FAIL"


def test_equal_latency_is_inconclusive_not_a_speed_claim():
    result = evaluate_experiment("exp-4", observations(candidate_latency=250.0), policy())
    assert result["decision"] == "INCONCLUSIVE"
    assert result["gates"][1]["status"] == "INCONCLUSIVE"


def test_insufficient_pairs_cannot_pass():
    result = evaluate_experiment("exp-5", observations(10), policy(min_pairs=30))
    assert result["decision"] == "INCONCLUSIVE"


def test_frame_time_regression_blocks_speed_promotion():
    result = evaluate_experiment(
        "exp-6",
        observations(candidate_frame=22.0),
        policy(max_frame_time_regression_pct=0.05),
    )
    assert result["decision"] == "REGRESSION"
    assert result["gates"][2]["status"] == "FAIL"


def test_frame_time_guardrail_can_pass_when_stable():
    result = evaluate_experiment(
        "exp-7",
        observations(),
        policy(max_frame_time_regression_pct=0.05),
    )
    assert result["decision"] == "IMPROVED"
    assert result["gates"][2]["status"] == "PASS"


def test_audio_underrun_regression_blocks_speed_promotion():
    result = evaluate_experiment(
        "exp-8",
        observations(candidate_underruns=10),
        policy(max_audio_underrun_rate_increase=0.001),
    )
    assert result["decision"] == "REGRESSION"
    assert result["gates"][2]["status"] == "FAIL"


def test_audio_guardrail_can_pass_when_no_underruns_are_added():
    result = evaluate_experiment(
        "exp-9",
        observations(),
        policy(max_audio_underrun_rate_increase=0.001),
    )
    assert result["decision"] == "IMPROVED"
    assert result["gates"][2]["status"] == "PASS"


def test_missing_stream_guardrail_data_is_inconclusive():
    result = evaluate_experiment(
        "exp-10",
        observations(include_audio=False),
        policy(max_audio_underrun_rate_increase=0.001),
    )
    assert result["decision"] == "INCONCLUSIVE"
    assert result["gates"][2]["status"] == "INCONCLUSIVE"


def test_primary_metric_can_be_selected_explicitly():
    result = evaluate_experiment(
        "exp-11",
        observations(),
        policy(primary_latency=LatencyMetric.FIRST_CONTENT),
    )
    assert result["decision"] == "IMPROVED"
    assert result["primary_latency"] == "first_content_ms"


def test_missing_primary_metric_is_rejected():
    rows = observations()
    rows[0] = ExperimentObservation(
        pair_id="pair-0",
        task_id="task-0",
        environment_id="same-hardware-game-build",
        variant=Variant.BASELINE,
        quality_evidence=QualityEvidence.HELD_OUT_TEST,
        quality_score=0.9,
        first_content_ms=125.0,
        first_audible_ms=None,
        inter_token_ms=25.0,
        request_ms=1000.0,
    )
    with pytest.raises(ValueError, match="primary latency"):
        evaluate_experiment("exp-12", rows, policy())


def test_duplicate_variant_for_a_pair_is_rejected():
    baseline, candidate = make_pair(1)
    with pytest.raises(ValueError, match="duplicate variant"):
        evaluate_experiment("exp-13", [baseline, baseline, candidate], policy())


def test_incomplete_pair_is_rejected():
    baseline, _ = make_pair(1)
    with pytest.raises(ValueError, match="exactly one"):
        evaluate_experiment("exp-14", [baseline], policy())


def test_task_mismatch_within_pair_is_rejected():
    baseline, candidate = make_pair(1)
    candidate = ExperimentObservation(
        pair_id=candidate.pair_id,
        task_id="different-task",
        environment_id=candidate.environment_id,
        variant=candidate.variant,
        quality_evidence=candidate.quality_evidence,
        quality_score=candidate.quality_score,
        first_audible_ms=candidate.first_audible_ms,
    )
    with pytest.raises(ValueError, match="must match"):
        evaluate_experiment("exp-15", [baseline, candidate], policy())


def test_environment_mismatch_within_pair_is_rejected():
    baseline, candidate = make_pair(1)
    candidate = ExperimentObservation(
        pair_id=candidate.pair_id,
        task_id=candidate.task_id,
        environment_id="different-environment",
        variant=candidate.variant,
        quality_evidence=candidate.quality_evidence,
        quality_score=candidate.quality_score,
        first_audible_ms=candidate.first_audible_ms,
    )
    with pytest.raises(ValueError, match="must match"):
        evaluate_experiment("exp-16", [baseline, candidate], policy())


def test_evidence_source_mismatch_within_pair_is_rejected():
    baseline, candidate = make_pair(1)
    candidate = ExperimentObservation(
        pair_id=candidate.pair_id,
        task_id=candidate.task_id,
        environment_id=candidate.environment_id,
        variant=candidate.variant,
        quality_evidence=QualityEvidence.HUMAN,
        quality_score=candidate.quality_score,
        first_audible_ms=candidate.first_audible_ms,
    )
    with pytest.raises(ValueError, match="must match"):
        evaluate_experiment("exp-17", [baseline, candidate], policy())


def test_model_judge_is_not_an_allowed_quality_source():
    with pytest.raises(ValueError):
        QualityEvidence("model_judge")


@pytest.mark.parametrize("score", [True, float("nan"), float("inf"), -0.1, 1.1, "0.9"])
def test_invalid_quality_scores_are_rejected(score):
    with pytest.raises(ValueError):
        ExperimentObservation(
            pair_id="p1",
            task_id="t1",
            environment_id="env1",
            variant=Variant.BASELINE,
            quality_evidence=QualityEvidence.HUMAN,
            quality_score=score,
            first_audible_ms=100.0,
        )


@pytest.mark.parametrize("latency", [True, 0, -1, float("nan"), float("inf")])
def test_invalid_latency_measurements_are_rejected(latency):
    with pytest.raises(ValueError):
        ExperimentObservation(
            pair_id="p1",
            task_id="t1",
            environment_id="env1",
            variant=Variant.BASELINE,
            quality_evidence=QualityEvidence.HUMAN,
            quality_score=0.9,
            first_audible_ms=latency,
        )


def test_audio_counts_must_be_a_valid_pair():
    with pytest.raises(ValueError, match="supplied together"):
        ExperimentObservation(
            pair_id="p1",
            task_id="t1",
            environment_id="env1",
            variant=Variant.BASELINE,
            quality_evidence=QualityEvidence.HUMAN,
            quality_score=0.9,
            first_audible_ms=100.0,
            audio_underrun_chunks=0,
        )


def test_audio_underruns_cannot_exceed_playback_chunks():
    with pytest.raises(ValueError, match="outside"):
        ExperimentObservation(
            pair_id="p1",
            task_id="t1",
            environment_id="env1",
            variant=Variant.BASELINE,
            quality_evidence=QualityEvidence.HUMAN,
            quality_score=0.9,
            first_audible_ms=100.0,
            audio_underrun_chunks=2,
            audio_playback_chunks=1,
        )


def test_bootstrap_result_is_deterministic_and_order_independent():
    rows = observations()
    first = evaluate_experiment("exp-18", rows, policy())
    second = evaluate_experiment("exp-18", list(reversed(rows)), policy())
    assert first == second


def test_experiment_id_is_validated():
    with pytest.raises(ValueError):
        evaluate_experiment("not a valid id", observations(), policy())


def test_observation_limit_is_enforced():
    rows = observations() * 334
    with pytest.raises(ValueError, match="bounded limit"):
        evaluate_experiment("exp-19", rows, policy())


def test_confident_quality_improvement_is_reported():
    result = evaluate_experiment(
        "exp-20",
        observations(base_quality=0.7, candidate_quality=0.9),
        policy(),
    )
    assert result["gates"][0]["status"] == "PASS"
    assert result["decision"] == "IMPROVED"
