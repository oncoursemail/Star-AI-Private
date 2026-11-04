"""Synthetic game skill demonstration: no device/game or streamer permissions."""
from dataclasses import FrozenInstanceError
import json
import pytest

from star.game_latency_skill_lab import (
    TimingAttempt, TimingLabReport, TimingScenario,
    generate_scenarios, learn_timing_correction,
    play_timing_scenario, run_timing_skill_lab,
)


def test_a_practice_trained_latency_correction_generalizes_to_heldout_scenarios():
    report = run_timing_skill_lab(practice_seed=44, holdout_seed=45)
    assert report.train_episodes == 96 and report.holdout_episodes == 128
    assert -200 <= report.calibration_offset_ms <= 40
    assert report.calibrated_holdout_rate >= report.baseline_holdout_rate + 0.35
    assert report.one_sided_exact_p < .01
    assert report.paired_improvements > report.paired_regressions
    assert report.calibrated_stress_rate >= report.baseline_stress_rate
    assert report.synthetic_only
    assert not report.authorizes_skill_promotion
    assert not report.authorizes_real_gameplay
    assert not report.authorizes_broadcast
    assert json.loads(report.to_json())["calibration_offset_ms"] == report.calibration_offset_ms


def test_world_advances_during_model_and_input_wait():
    # A policy that would work if the world paused during inference loses.
    scene = TimingScenario(400, 400, 25, 700, 70)
    late = play_timing_scenario(scene, correction_ms=-100)
    assert not late.success and late.missed_collision
    assert late.action_ack_ms == 795
    assert late.lead_at_ack_ms == -395


def test_dispatch_latency_is_charged_and_latency_learning_can_help():
    scene = TimingScenario(700, 700, 25, 40, 100)
    baseline = play_timing_scenario(scene)
    corrected = play_timing_scenario(scene, correction_ms=-100)
    assert not baseline.success
    assert baseline.lead_at_ack_ms == 70
    assert corrected.success
    assert corrected.lead_at_ack_ms == 170


def test_screenshot_age_counts_against_a_reactive_deadline():
    scene = TimingScenario(280, 280, 200, 250, 120)
    result = play_timing_scenario(scene, correction_ms=-150)
    assert result.action_ack_ms == 570
    assert result.missed_collision and not result.success


def test_reproducibility_and_practice_only_calibration():
    practice = generate_scenarios(seed=101, count=48)
    assert practice == generate_scenarios(seed=101, count=48)
    assert practice != generate_scenarios(seed=102, count=48)
    assert learn_timing_correction(practice) == learn_timing_correction(practice)
    a = run_timing_skill_lab(practice_seed=101, holdout_seed=102, practice_count=48, holdout_count=64)
    b = run_timing_skill_lab(practice_seed=101, holdout_seed=103, practice_count=48, holdout_count=64)
    assert a.calibration_offset_ms == b.calibration_offset_ms
    assert a.train_success_rate == b.train_success_rate
    assert a.to_json() != b.to_json()
    assert a.to_json() == run_timing_skill_lab(
        practice_seed=101, holdout_seed=102, practice_count=48, holdout_count=64
    ).to_json()


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), -10, "200"])
def test_invalid_scene_timing_is_rejected(bad):
    with pytest.raises(ValueError):
        TimingScenario(700, bad, 20, 40, 90)


@pytest.mark.parametrize("offset", [True, .1, -301, 101, "50"])
def test_invalid_correction_never_executes(offset):
    scene = TimingScenario(700, 700, 20, 40, 90)
    with pytest.raises(ValueError):
        play_timing_scenario(scene, correction_ms=offset)


def test_nonfinite_stress_penalty_or_scenario_is_rejected():
    scene = TimingScenario(700, 700, 20, 40, 90)
    with pytest.raises(ValueError):
        play_timing_scenario(scene, inference_penalty_ms=float("nan"))
    with pytest.raises(ValueError):
        play_timing_scenario(scene, dispatch_penalty_ms=-1)
    with pytest.raises(TypeError):
        play_timing_scenario("viewer says checkpoint")
    with pytest.raises(ValueError):
        run_timing_skill_lab(practice_seed=8, holdout_seed=9, stress_inference_penalty_ms=-1)


@pytest.mark.parametrize("practice,holdout", [(3, 3), (True, 2), (4, 4.0)])
def test_reject_holdout_contamination(practice, holdout):
    with pytest.raises(ValueError):
        run_timing_skill_lab(practice_seed=practice, holdout_seed=holdout)


def test_report_is_immutable_and_no_realworld_authorization():
    r = run_timing_skill_lab(practice_seed=15, holdout_seed=19)
    with pytest.raises(FrozenInstanceError):
        r.synthetic_only = False
    assert TimingLabReport.__dataclass_fields__["authorizes_broadcast"].default is False
    assert TimingAttempt.__dataclass_fields__["success"].type != str


def test_no_hidden_world_outcome_becomes_a_policy_feature():
    # Candidate selection is computed only over practice episodes.
    a = generate_scenarios(seed=77, count=48)
    b = tuple(TimingScenario(
        row.collision_ms, row.observed_ttc_ms, row.screenshot_age_ms,
        row.inference_ms, row.input_dispatch_ms,
    ) for row in a)
    assert learn_timing_correction(a) == learn_timing_correction(b)


def test_valid_boundaries_and_bad_training_inputs():
    assert len(generate_scenarios(seed=0, count=40)) == 40
    with pytest.raises(ValueError):
        generate_scenarios(seed=2**63, count=40)
    with pytest.raises(ValueError):
        generate_scenarios(seed=1, count=39)
    with pytest.raises(ValueError):
        learn_timing_correction(("not a scenario",) * 40)
    with pytest.raises(ValueError):
        play_timing_scenario(TimingScenario(700, 700, 20, 40, 90), correction_ms=400)
