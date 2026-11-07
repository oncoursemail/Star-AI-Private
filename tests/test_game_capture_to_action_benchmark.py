"""Adversarial, offline regression tests for capture-to-action gaming audit."""
from dataclasses import asdict, replace
import json
import subprocess
import sys

import pytest

from star.game_capture_to_action_benchmark import (
    CaptureToActionTrial, compare_capture_to_action, read_jsonl,
)


def trial(n: int, variant: str, *, duration: float = 200,
          victory: bool = False, frame: int | None = None) -> CaptureToActionTrial:
    origin = n * 2000 + 1000.0
    end = origin + duration
    return CaptureToActionTrial(
        pair_id=f"pair{n}", variant=variant,
        episode_id=f"episode{n}{variant}", game_id="obby", game_version="v1",
        scenario_id=f"level{n}", initial_state_sha256="a" * 64,
        capture_start_ms=origin, capture_end_ms=origin + 20,
        transfer_end_ms=origin + 30, preprocess_end_ms=origin + 40,
        inference_end_ms=origin + min(duration - 10, 65),
        input_ack_ms=end, scene_deadline_ms=origin + 250,
        world_frame_at_capture=1000,
        world_frame_at_preprocess=1002, world_frame_at_inference=1004,
        world_frame_at_ack=frame if frame is not None else 1000 + round(duration * 60 / 1000),
        nominal_world_fps=60, progress_before=.1,
        progress_after=.9 if victory else .2,
        objective_success=victory, game_p99_frame_ms=18,
        obs_dropped_pct=0, independently_measured=True,
    )


def cohort(n: int = 24):
    output = []
    for i in range(n):
        output.append(trial(i, "baseline", duration=210))
        output.append(trial(i, "candidate", duration=100, victory=True))
    return output


def test_full_pipeline_improvement_manual_only():
    report = compare_capture_to_action(cohort())
    assert report.verdict == "manual_pilot_candidate"
    assert report.baseline_p95_ms == 210
    assert report.candidate_p95_ms == 100
    assert report.latency_gain_ci95_lower_ms == 110
    assert report.progress_gain_ci95_lower == .7
    assert report.candidate_stage_p95_ms["capture"] == 20
    assert report.candidate_stage_p95_ms["inference"] == 25
    assert report.candidate_stage_p95_ms["dispatch"] == 35
    assert not report.authorized_to_act


def test_fast_but_not_better_at_game_cannot_claim_intelligence_gain():
    group = cohort()
    group = [replace(r, progress_after=.1) if r.variant == "candidate" else r
             for r in group]
    report = compare_capture_to_action(group)
    assert report.verdict == "inconclusive"
    assert report.progress_gain_ci95_lower is not None
    assert report.progress_gain_ci95_lower < 0


def test_full_path_includes_capture_transfer_and_dispatch():
    group = cohort()
    fast = group[1]
    # 40ms is the "model" portion, but 100ms is full input response.
    assert fast.inference_end_ms - fast.preprocess_end_ms == 25
    assert fast.end_to_end_ms == 100
    assert sum(fast.stage_durations().values()) == 100


def test_pause_during_capture_transfer_invalidates_promotion():
    group = cohort()
    group[1] = replace(group[1], world_frame_at_preprocess=1000,
                       world_frame_at_inference=1000,
                       world_frame_at_ack=1001)  # entire game froze
    report = compare_capture_to_action(group)
    assert report.non_live == 1
    assert report.verdict == "inconclusive"


def test_paused_capture_cannot_be_hidden_by_world_catchup_during_inference():
    group = cohort()
    group[1] = replace(group[1], world_frame_at_preprocess=1000)
    assert group[1].world_frame_at_ack == 1006
    assert compare_capture_to_action(group).non_live == 1


def test_paused_dispatch_cannot_be_hidden_by_inference_world_clock():
    group = cohort()
    group[1] = replace(group[1], world_frame_at_inference=1006)
    assert compare_capture_to_action(group).non_live == 1


def test_candidate_frame_regression_not_offset_by_speed():
    group = cohort()
    group[1] = replace(group[1], game_p99_frame_ms=30)
    report = compare_capture_to_action(group)
    assert report.qos_regressions == 1
    assert report.verdict == "regressed"


def test_candidate_obs_regression_not_offset_by_speed():
    group = cohort()
    group[1] = replace(group[1], obs_dropped_pct=1)
    assert compare_capture_to_action(group).verdict == "regressed"


def test_newly_lost_baseline_success_rejected():
    group = cohort()
    group[0] = replace(group[0], objective_success=True)
    group[1] = replace(group[1], objective_success=False)
    report = compare_capture_to_action(group)
    assert report.candidate_new_failures == 1
    assert report.verdict == "regressed"


def test_missing_input_ack_ineligible_and_fails_closed():
    group = cohort()
    group[1] = replace(group[1], input_ack_ms=None, world_frame_at_ack=None)
    report = compare_capture_to_action(group)
    assert report.verdict != "manual_pilot_candidate"
    assert report.non_live == 1
    assert report.candidate_late_or_missing == 1
    assert report.verdict == "regressed"


def test_unverified_or_incomplete_never_qualifies():
    group = cohort()
    group[1] = replace(group[1], independently_measured=False)
    assert compare_capture_to_action(group).unverified == 1
    assert compare_capture_to_action(group).verdict == "inconclusive"
    group = cohort()[:-1]
    assert compare_capture_to_action(group).incomplete == 1
    assert compare_capture_to_action(group).verdict == "inconclusive"


def test_no_data_does_not_claim_improvement():
    report = compare_capture_to_action([])
    assert report.verdict == "inconclusive"
    assert not report.authorized_to_act


def test_reused_episode_and_duplicate_variant_rejected():
    group = cohort()
    group[3] = replace(group[3], episode_id=group[1].episode_id)
    with pytest.raises(ValueError, match="episode replay"):
        compare_capture_to_action(group)
    group = cohort()
    with pytest.raises(ValueError, match="duplicate variant"):
        compare_capture_to_action(group + [replace(group[0], episode_id="other")])


def test_mismatched_deadlines_starting_state_or_world_rate_rejected():
    for changes in (
        dict(scene_deadline_ms=3000),
        dict(initial_state_sha256="b" * 64),
        dict(nominal_world_fps=59),
        dict(scenario_id="unexpected"),
    ):
        group = cohort()
        group[1] = replace(group[1], **changes)
        with pytest.raises(ValueError, match="paired baseline"):
            compare_capture_to_action(group)


@pytest.mark.parametrize("changes", [
    dict(capture_end_ms=500), dict(transfer_end_ms=1),
    dict(input_ack_ms=0), dict(input_ack_ms=float("nan")),
    dict(input_ack_ms=True), dict(scene_deadline_ms=float("inf")),
    dict(world_frame_at_capture=True), dict(world_frame_at_preprocess=True),
    dict(world_frame_at_inference=1001), dict(world_frame_at_ack=999),
    dict(world_frame_at_ack=True), dict(obs_dropped_pct=101),
    dict(nominal_world_fps=0), dict(progress_before=-1),
    dict(independently_measured=1), dict(episode_id="user text"),
    dict(game_p99_frame_ms=float("nan")),
])
def test_invalid_time_or_source_metrics_rejected(changes):
    with pytest.raises(ValueError):
        replace(trial(0, "baseline"), **changes)


def test_no_ack_cannot_have_ack_frame():
    with pytest.raises(ValueError, match="unacknowledged"):
        replace(trial(0, "baseline"), input_ack_ms=None)
    with pytest.raises(ValueError, match="world frame"):
        replace(trial(0, "baseline"), world_frame_at_ack=None)


def test_read_jsonl_and_cli_metrics_only(tmp_path):
    input_file = tmp_path / "host.jsonl"
    input_file.write_text(
        "".join(json.dumps(asdict(row)) + "\n" for row in cohort()), encoding="utf8"
    )
    assert len(read_jsonl(input_file)) == 48
    result = subprocess.run(
        [sys.executable, "-m", "star.game_capture_to_action_benchmark", str(input_file)],
        text=True, capture_output=True, check=True,
    )
    metrics = json.loads(result.stdout)
    assert metrics["verdict"] == "manual_pilot_candidate"
    assert "episode" not in result.stdout
    assert "level" not in result.stdout


def test_bounded_schema_forbids_text_and_duplicate_keys(tmp_path):
    row = asdict(trial(0, "baseline"))
    f = tmp_path / "bad.jsonl"
    f.write_text(json.dumps({**row, "viewer_chat": "private"}), encoding="utf8")
    with pytest.raises(ValueError, match="bounded"):
        read_jsonl(f)
    f.write_text('{"pair_id":"a","pair_id":"b"}\n', encoding="utf8")
    with pytest.raises(ValueError, match="duplicate"):
        read_jsonl(f)


def test_minimum_pairs_and_limit_enforced():
    assert compare_capture_to_action(cohort(10)).verdict == "inconclusive"
    for bad in (True, 1, 501):
        with pytest.raises(ValueError):
            compare_capture_to_action([], minimum_pairs=bad)
    with pytest.raises(ValueError, match="too many"):
        compare_capture_to_action(
            replace(trial(i, "baseline"), episode_id=f"unique{i}") for i in range(1001)
        )
