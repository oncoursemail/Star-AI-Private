"""Deterministic offline tests for STAR's private-stream rehearsal evaluator."""
import copy

import pytest

from star.stream_rehearsal_eval import RehearsalLimits, evaluate_rehearsal


def snapshot(**changes):
    value = {
        "schema_version": 1,
        "run_id": "private-rehearsal-001",
        "first_content_latency_ms": [180.0] * 20,
        "first_audible_latency_ms": [420.0] * 20,
        "game_frame_time_ms": [16.7] * 20,
        "avatar_sync_error_ms": [24.0] * 20,
        "audio_underruns": 0,
        "audio_playback_chunks": 1000,
        "obs_render_skipped_frames": 2,
        "obs_render_total_frames": 10000,
        "obs_output_skipped_frames": 3,
        "obs_output_total_frames": 10000,
        "turn_true_positives": 19,
        "turn_false_positives": 1,
        "turn_false_negatives": 1,
        "task_recovery_attempts": 20,
        "task_recovery_successes": 19,
        "stale_task_resumes": 0,
        "duplicate_speech_replays": 0,
        "held_out_skill_trials": 20,
        "held_out_skill_successes": 17,
    }
    value.update(changes)
    return value


def limits(**changes):
    value = {
        "min_observations": 20,
        "max_first_content_p95_ms": 300.0,
        "max_first_audible_p95_ms": 600.0,
        "max_game_frame_p99_ms": 20.0,
        "max_avatar_sync_p95_ms": 50.0,
        "max_audio_underrun_rate": 0.001,
        "max_obs_render_skip_rate": 0.001,
        "max_obs_output_skip_rate": 0.001,
        "min_turn_precision": 0.9,
        "min_turn_recall": 0.9,
        "min_task_recovery_rate": 0.9,
        "min_held_out_skill_transfer_rate": 0.8,
        "max_stale_task_resumes": 0,
        "max_duplicate_speech_replays": 0,
    }
    value.update(changes)
    return RehearsalLimits(**value)


def test_complete_rehearsal_passes_all_configured_gates():
    report = evaluate_rehearsal(snapshot(), limits())

    assert report["overall"] == "PASS"
    assert len(report["gates"]) == 13
    assert all(gate["status"] == "PASS" for gate in report["gates"])
    assert report["metrics"]["turn_precision"] == 0.95
    assert report["metrics"]["turn_recall"] == 0.95
    assert report["metrics"]["task_recovery_rate"] == 0.95
    assert report["metrics"]["held_out_skill_transfer_rate"] == 0.85
    assert report["metrics"]["audio_underrun_rate"] == 0.0


def test_any_measured_regression_fails_the_run():
    report = evaluate_rehearsal(
        snapshot(
            first_audible_latency_ms=[900.0] * 20,
            game_frame_time_ms=[25.0] * 20,
            audio_underruns=5,
        ),
        limits(),
    )

    assert report["overall"] == "FAIL"
    statuses = {gate["name"]: gate["status"] for gate in report["gates"]}
    assert statuses["first_audible_p95_ms"] == "FAIL"
    assert statuses["game_frame_p99_ms"] == "FAIL"
    assert statuses["audio_underrun_rate"] == "FAIL"


def test_missing_or_insufficient_measurements_are_inconclusive_not_zero():
    report = evaluate_rehearsal(
        snapshot(first_audible_latency_ms=[100.0], game_frame_time_ms=[]),
        limits(),
    )

    assert report["overall"] == "INCONCLUSIVE"
    statuses = {gate["name"]: gate["status"] for gate in report["gates"]}
    assert statuses["first_audible_p95_ms"] == "INCONCLUSIVE"
    assert statuses["game_frame_p99_ms"] == "INCONCLUSIVE"


def test_zero_denominators_are_inconclusive():
    report = evaluate_rehearsal(
        snapshot(
            audio_playback_chunks=0,
            obs_render_total_frames=0,
            obs_output_total_frames=0,
            turn_true_positives=0,
            turn_false_positives=0,
            turn_false_negatives=0,
            task_recovery_attempts=0,
            task_recovery_successes=0,
            held_out_skill_trials=0,
            held_out_skill_successes=0,
        ),
        limits(),
    )

    assert report["overall"] == "INCONCLUSIVE"
    by_name = {gate["name"]: gate["status"] for gate in report["gates"]}
    assert by_name["audio_underrun_rate"] == "INCONCLUSIVE"
    assert by_name["obs_render_skip_rate"] == "INCONCLUSIVE"
    assert by_name["turn_precision"] == "INCONCLUSIVE"
    assert by_name["task_recovery_rate"] == "INCONCLUSIVE"


def test_stale_resume_and_duplicate_speech_zero_tolerance_gates():
    report = evaluate_rehearsal(
        snapshot(stale_task_resumes=1, duplicate_speech_replays=1),
        limits(),
    )

    assert report["overall"] == "FAIL"
    by_name = {gate["name"]: gate["status"] for gate in report["gates"]}
    assert by_name["stale_task_resumes"] == "FAIL"
    assert by_name["duplicate_speech_replays"] == "FAIL"


def test_nearest_rank_percentiles_are_reported_without_interpolation():
    values = [float(number) for number in range(1, 101)]
    report = evaluate_rehearsal(
        snapshot(
            first_content_latency_ms=values,
            first_audible_latency_ms=values,
            game_frame_time_ms=values,
            avatar_sync_error_ms=values,
        ),
        limits(min_observations=100),
    )

    assert report["metrics"]["first_content_p95_ms"] == 95.0
    assert report["metrics"]["game_frame_p99_ms"] == 99.0


def test_report_does_not_retain_raw_measurement_arrays():
    report = evaluate_rehearsal(snapshot(), limits())

    assert set(report) == {"schema_version", "run_id", "overall", "metrics", "gates", "notes"}
    assert "first_audible_latency_ms" not in report["metrics"]
    assert "audio" not in report["metrics"]
    assert all("transcript" not in str(gate).lower() for gate in report["gates"])


@pytest.mark.parametrize("bad", [True, -1, float("nan"), float("inf"), "420"])
def test_invalid_latency_samples_are_rejected(bad):
    data = snapshot(first_audible_latency_ms=[bad] * 20)
    with pytest.raises(ValueError):
        evaluate_rehearsal(data, limits())


def test_unexpected_private_payload_fields_are_rejected():
    data = snapshot()
    data["transcript"] = "private viewer conversation"

    with pytest.raises(ValueError):
        evaluate_rehearsal(data, limits())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("audio_underruns", -1),
        ("audio_playback_chunks", True),
        ("obs_render_skipped_frames", 10_001),
        ("task_recovery_successes", 21),
        ("held_out_skill_successes", 21),
    ],
)
def test_inconsistent_or_invalid_counters_are_rejected(field, value):
    data = snapshot(**{field: value})

    with pytest.raises(ValueError):
        evaluate_rehearsal(data, limits())


def test_limits_require_at_least_one_configured_gate():
    with pytest.raises(ValueError):
        RehearsalLimits()


def test_rate_limits_must_be_fractions():
    with pytest.raises(ValueError):
        RehearsalLimits(max_audio_underrun_rate=1.1)


def test_only_exact_opaque_run_ids_are_accepted():
    for bad in ("", "private viewer name", "../stream", "x" * 81):
        with pytest.raises(ValueError):
            evaluate_rehearsal(snapshot(run_id=bad), limits())


def test_evaluator_is_deterministic_and_does_not_mutate_input():
    data = snapshot()
    before = copy.deepcopy(data)

    first = evaluate_rehearsal(data, limits())
    second = evaluate_rehearsal(data, limits())

    assert first == second
    assert data == before
