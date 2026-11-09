"""Offline paired tests for running-game deadlines and state outcomes."""
from dataclasses import asdict, replace
import json
import subprocess
import sys

import pytest

from star.game_live_clock_benchmark import LiveClockTrial, assess_live_clock, read_jsonl


def trial(pair: int, variant: str, *, progress: float = .25,
          success: bool = False, response: float | None = 150,
          scored: bool = True, frame: float = 17,
          dropped: float = 0, episode: str | None = None) -> LiveClockTrial:
    start = 1000.0 + pair * 2000
    return LiveClockTrial(
        pair_id=f"pair-{pair}", variant=variant,
        episode_id=episode or f"episode-{pair}-{variant}",
        game_id="obby", game_version="v2", scenario_id=f"map-{pair}",
        initial_state_sha256="a" * 64, observed_at_ms=start,
        inference_started_ms=start + 5, inference_finished_ms=start + 50,
        input_ack_ms=None if response is None else start + response,
        scene_deadline_ms=start + 200, world_advanced_ms=50,
        world_advanced_to_input_ack_ms=None if response is None else float(response),
        progress_before=.10,
        progress_after=progress, objective_success=success,
        game_p99_frame_ms=frame, obs_dropped_pct=dropped,
        independently_scored=scored,
    )


def cohort(n=24):
    out = []
    for i in range(n):
        out.extend([trial(i, "baseline"), trial(i, "candidate", progress=.80,
                    success=True, response=90)])
    return out


def test_good_faster_successful_agent_eligible_for_manual_pilot_only():
    report = assess_live_clock(cohort())
    assert report.verdict == "manual_pilot_candidate"
    assert report.matched_pairs == 24
    assert report.baseline_timely_successes == 0
    assert report.candidate_timely_successes == 24
    assert report.progress_gain_ci95 == (.55, .55)
    assert report.candidate_action_p95_ms == 90
    assert report.baseline_action_p95_ms == 150
    assert report.paired_win_sign_pvalue == pytest.approx(2 ** -24)
    assert not report.authorized_to_act


def test_fast_but_wrong_agent_does_not_win_benchmark():
    runs = cohort()
    runs = [replace(item, objective_success=False, progress_after=.12)
            if item.variant == "candidate" else item for item in runs]
    report = assess_live_clock(runs)
    # This candidate loses progress in every scenario, not just a weak win.
    assert report.verdict == "regressed"
    assert report.scenario_progress_regressions == 24
    assert report.progress_gain_ci95 is not None


def test_late_input_never_counts_as_timely_success():
    runs = cohort()
    runs[1] = replace(runs[1], input_ack_ms=runs[1].observed_at_ms + 205,
                      world_advanced_to_input_ack_ms=205)
    report = assess_live_clock(runs)
    assert report.candidate_timely_successes == 23
    assert report.candidate_missed_or_late_inputs == 1
    assert report.verdict == "regressed"


def test_paused_game_world_cannot_claim_live_clock_improvement():
    runs = cohort()
    runs[1] = replace(runs[1], world_advanced_ms=0)
    report = assess_live_clock(runs)
    assert report.non_live_pairs == 1
    assert report.verdict == "inconclusive"


def test_different_game_clock_speed_cannot_masquerade_as_live_clock():
    runs = cohort()
    runs[1] = replace(runs[1], world_advanced_ms=500,
                      world_advanced_to_input_ack_ms=500)
    report = assess_live_clock(runs)
    assert report.non_live_pairs == 1
    assert report.verdict == "inconclusive"


def test_mismatched_deadline_and_starting_progress_do_not_form_valid_pair():
    runs = cohort()
    runs[1] = replace(runs[1], scene_deadline_ms=runs[1].scene_deadline_ms + 100)
    with pytest.raises(ValueError, match="time budget"):
        assess_live_clock(runs)
    runs = cohort()
    runs[1] = replace(runs[1], progress_before=.2)
    with pytest.raises(ValueError, match="time budget"):
        assess_live_clock(runs)


def test_no_input_receipt_cannot_claim_real_time_action():
    runs = cohort()
    runs[1] = replace(runs[1], input_ack_ms=None, world_advanced_to_input_ack_ms=None)
    report = assess_live_clock(runs)
    assert report.candidate_missed_or_late_inputs == 1
    assert report.candidate_timely_successes == 23
    assert report.verdict == "regressed"


def test_previously_successful_scenario_cannot_be_sacrificed():
    runs = cohort()
    runs[0] = replace(runs[0], objective_success=True)
    runs[1] = replace(runs[1], objective_success=False)
    report = assess_live_clock(runs)
    assert report.candidate_new_failures == 1
    assert report.verdict == "regressed"


def test_obs_quality_cannot_be_traded_for_inference_speed():
    runs = cohort()
    runs[1] = replace(runs[1], obs_dropped_pct=0.8)
    result = assess_live_clock(runs)
    assert result.candidate_qos_regressions == 1
    assert result.verdict == "regressed"
    runs[1] = replace(runs[1], obs_dropped_pct=0, game_p99_frame_ms=30)
    assert assess_live_clock(runs).verdict == "regressed"


def test_short_or_unverified_or_incomplete_cohort_not_positive():
    assert assess_live_clock(cohort(12)).verdict == "inconclusive"
    runs = cohort()
    runs[1] = replace(runs[1], independently_scored=False)
    assert assess_live_clock(runs).unverified_pairs == 1
    assert assess_live_clock(runs).verdict == "inconclusive"
    report = assess_live_clock(cohort()[:-1])
    assert report.incomplete_pairs == 1
    assert report.verdict == "inconclusive"


def test_reused_episode_cannot_manufacture_independent_cases():
    runs = cohort(12)
    runs[3] = replace(runs[3], episode_id=runs[1].episode_id)
    with pytest.raises(ValueError, match="episode reused"):
        assess_live_clock(runs)


def test_mismatched_initial_state_or_scenario_rejected():
    runs = cohort(12)
    runs[1] = replace(runs[1], initial_state_sha256="b" * 64)
    with pytest.raises(ValueError, match="identical scenario"):
        assess_live_clock(runs)
    runs = cohort(12)
    runs[1] = replace(runs[1], scenario_id="different")
    with pytest.raises(ValueError, match="identical scenario"):
        assess_live_clock(runs)


def test_duplicate_and_mixed_game_version_rejected():
    runs = cohort(12)
    with pytest.raises(ValueError, match="duplicate variant"):
        assess_live_clock(runs + [replace(runs[0], episode_id="new-one")])
    runs[1] = replace(runs[1], game_version="v3")
    with pytest.raises(ValueError, match="different games"):
        assess_live_clock(runs)


@pytest.mark.parametrize("field,value", [
    ("observed_at_ms", float("nan")), ("inference_started_ms", True),
    ("inference_finished_ms", float("inf")), ("input_ack_ms", -1),
    ("scene_deadline_ms", 0), ("progress_before", 1.01),
    ("progress_after", -0.1), ("obs_dropped_pct", 101),
    ("game_p99_frame_ms", float("nan")), ("world_advanced_ms", float("inf")),
    ("objective_success", 1),
    ("world_advanced_to_input_ack_ms", -1),
    ("world_advanced_to_input_ack_ms", float("nan")),
    ("independently_scored", "yes"), ("episode_id", "bad space"),
    ("initial_state_sha256", "not-a-sha"), ("variant", "preferred"),
])
def test_untrusted_or_nonfinite_data_rejected(field, value):
    with pytest.raises(ValueError):
        replace(trial(0, "baseline"), **{field: value})


def test_clock_order_and_scene_deadline_validation():
    t = trial(0, "baseline")
    for modifications in (
        dict(inference_started_ms=t.observed_at_ms - 1),
        dict(inference_finished_ms=t.inference_started_ms - 1),
        dict(input_ack_ms=t.inference_finished_ms - 1),
        dict(scene_deadline_ms=t.observed_at_ms),
        dict(scene_deadline_ms=t.observed_at_ms + 61_000),
    ):
        with pytest.raises(ValueError):
            replace(t, **modifications)


def test_no_data_returns_inconclusive_and_no_authority():
    result = assess_live_clock([])
    assert result.verdict == "inconclusive"
    assert result.matched_pairs == 0
    assert not result.authorized_to_act


def test_invalid_cohort_and_threshold_parameters():
    for minimum in (True, 9, 501):
        with pytest.raises(ValueError):
            assess_live_clock([], minimum_pairs=minimum)
    for val in (True, float("nan"), -1):
        with pytest.raises(ValueError):
            assess_live_clock([], max_obs_dropped_regression_pct=val)
    with pytest.raises(TypeError):
        assess_live_clock([{}])


def test_offline_jsonl_cli_emits_only_aggregate_metrics(tmp_path):
    path = tmp_path / "scores.jsonl"
    path.write_text("".join(json.dumps(asdict(row)) + "\n" for row in cohort()),
                    encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "star.game_live_clock_benchmark", str(path)],
        capture_output=True, text=True, check=True,
    )
    report = json.loads(result.stdout)
    assert report["verdict"] == "manual_pilot_candidate"
    assert "pair-1" not in result.stdout
    assert "scene" not in result.stdout


def test_cli_rejects_extra_sensitive_or_missing_fields(tmp_path):
    good = asdict(trial(1, "candidate"))
    file = tmp_path / "bad.jsonl"
    file.write_text(json.dumps({**good, "screen_capture": "secret"}) + "\n")
    with pytest.raises(ValueError, match="bounded"):
        read_jsonl(file)
    good.pop("episode_id")
    file.write_text(json.dumps(good) + "\n")
    with pytest.raises(ValueError, match="bounded"):
        read_jsonl(file)

def test_game_paused_after_inference_before_input_ack_cannot_qualify():
    # A fast model's world advances while it reasons, but freezes during the
    # host-to-key dispatch window: aggregate inference-only checks miss this.
    runs = cohort()
    c = runs[1]
    assert c.inference_finished_ms < c.input_ack_ms
    runs[1] = replace(c, world_advanced_to_input_ack_ms=c.world_advanced_ms)
    report = assess_live_clock(runs)
    assert report.non_live_pairs == 1
    assert report.verdict == "inconclusive"
    assert not report.authorized_to_act


def test_cumulative_world_clock_must_be_monotonic_and_present_when_ack_exists():
    t = trial(0, "baseline")
    with pytest.raises(ValueError, match="world.*clock"):
        replace(t, world_advanced_to_input_ack_ms=40)
    with pytest.raises(ValueError, match="world.*clock"):
        replace(t, world_advanced_to_input_ack_ms=None)
    with pytest.raises(ValueError, match="world.*clock"):
        replace(t, input_ack_ms=None)  # no ack must also clear its witness


def test_world_moves_during_inference_but_not_host_dispatch_across_cohort():
    runs = cohort()
    runs = [replace(t, world_advanced_to_input_ack_ms=t.world_advanced_ms)
            if t.variant == "candidate" else t for t in runs]
    result = assess_live_clock(runs)
    assert result.non_live_pairs == 24
    assert result.verdict == "inconclusive"


def test_post_inference_world_clock_speedup_is_not_live_gameplay():
    runs = cohort()
    c = runs[1]
    runs[1] = replace(c, world_advanced_to_input_ack_ms=1000)
    report = assess_live_clock(runs)
    assert report.verdict == "inconclusive"
    assert report.non_live_pairs == 1


def test_replayed_initial_state_cannot_inflate_independent_pair_count():
    # Different pair/episode IDs do NOT turn an identical game reset into
    # a new holdout. Earlier the 24-case fixture still qualified.
    runs = cohort()
    runs[2] = replace(runs[2], scenario_id="map-0")
    runs[3] = replace(runs[3], scenario_id="map-0")
    with pytest.raises(ValueError, match="reused paired starting state"):
        assess_live_clock(runs)


def test_one_lucky_new_win_with_large_progress_claim_does_not_qualify():
    # A large reported progress delta and faster actuation must not disguise
    # weak paired win evidence. One discordant new win gives p=0.5.
    runs = cohort()
    runs = [
        replace(row, objective_success=False)
        if row.variant == "candidate" and row.pair_id != "pair-0" else row
        for row in runs
    ]
    report = assess_live_clock(runs)
    assert report.candidate_timely_successes == 1
    assert report.progress_gain_ci95 == (.55, .55)
    assert report.paired_win_sign_pvalue == pytest.approx(0.5)
    assert report.verdict == "inconclusive"
    assert not report.authorized_to_act


def test_many_resets_from_one_stage_do_not_claim_broad_gameplay_readiness():
    # Distinct host start-state fingerprints may represent different seeds,
    # but all of them coming from the same stage is not transfer evidence.
    runs = cohort()
    runs = [
        replace(row, scenario_id="only-stage",
                initial_state_sha256=f"{int(row.pair_id.split('-')[1]):064x}")
        for row in runs
    ]
    report = assess_live_clock(runs)
    assert report.matched_pairs == 24
    assert report.paired_win_sign_pvalue == pytest.approx(2 ** -24)
    assert report.verdict == "inconclusive"
    assert not report.authorized_to_act


def test_imbalanced_scenarios_cannot_manufacture_broad_game_mastery():
    # Different initial-state hashes genuinely represent distinct resets,
    # but 22 resets from one easy level plus two one-offs do not establish
    # a generalist player across three independent scenarios.
    rows = []
    for row in cohort():
        index = int(row.pair_id.split("-")[1])
        scenario = "easy" if index < 22 else f"tail-{index}"
        rows.append(replace(
            row, scenario_id=scenario,
            initial_state_sha256=f"{index:064x}",
        ))
    report = assess_live_clock(rows)
    assert report.matched_pairs == 24
    assert report.paired_win_sign_pvalue == pytest.approx(2 ** -24)
    assert report.effective_scenarios == pytest.approx(24**2 / (22**2 + 1 + 1), abs=0.0001)
    assert report.verdict == "inconclusive"
    assert report.authorized_to_act is False


def test_one_stage_progress_loss_does_not_disappear_in_global_gain():
    rows = cohort()
    rows[1] = replace(rows[1], progress_after=.10)
    report = assess_live_clock(rows)
    assert report.progress_gain_ci95 is not None
    assert report.progress_gain_ci95[0] > 0.02
    assert report.candidate_timely_successes == 24
    assert report.scenario_progress_regressions == 1
    assert report.verdict == "regressed"


def test_one_stage_input_slowdown_does_not_hide_under_global_p95():
    rows = cohort()
    old = rows[1]
    rows[1] = replace(
        old, input_ack_ms=old.observed_at_ms + 190,
        world_advanced_to_input_ack_ms=190,
    )
    report = assess_live_clock(rows)
    assert report.baseline_action_p95_ms == 150
    assert report.candidate_action_p95_ms == 90
    assert report.scenario_action_p95_regressions == 1
    assert report.verdict == "regressed"


def test_balanced_and_many_distinct_scenarios_keep_positive_manual_pilot():
    assert assess_live_clock(cohort()).verdict == "manual_pilot_candidate"
    rows = []
    for row in cohort():
        index = int(row.pair_id.split("-")[1])
        rows.append(replace(
            row, scenario_id=f"stage-{index % 3}",
            initial_state_sha256=f"{index:064x}",
        ))
    report = assess_live_clock(rows)
    assert report.effective_scenarios == 3.0
    assert report.verdict == "manual_pilot_candidate"
