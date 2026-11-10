from __future__ import annotations

import pytest

from star.voice.eot_calibration import (
    CalibrationConfig,
    EOTTrial,
    ScoreObservation,
    calibrate_end_of_turn,
    evaluate_threshold,
)


def trial(example_id: str, *, split="calibration", end=True, scores=((1100.0, 0.85), (1200.0, 0.95)),
          reference=1000.0, resume=None, language="en", group=None):
    if group is None:
        split_offset = 0 if split == "calibration" else 1000
        class_offset = 100 if example_id.startswith("p-") else 500
        suffix = example_id.rsplit("-", 1)[-1]
        index = int(suffix) if suffix.isdigit() else 999
        conversation_group = f"{split_offset + class_offset + index + 1:064x}"
    else:
        conversation_group = group
    return EOTTrial(
        example_id=example_id,
        conversation_group=conversation_group,
        model_id="turn-v1-mini",
        language=language,
        split=split,
        is_turn_end=end,
        reference_ms=reference,
        resume_ms=resume,
        observations=tuple(ScoreObservation(at, score) for at, score in scores),
    )


def cohort(split: str):
    values = []
    for index in range(120):
        values.append(trial(f"p-{split}-{index}", split=split, end=True,
                            scores=((1100.0, 0.85), (1200.0, 0.95))))
        values.append(trial(f"n-{split}-{index}", split=split, end=False,
                            scores=((1100.0, 0.75),), resume=1400.0))
    return values


def config():
    return CalibrationConfig(
        thresholds=(0.5, 0.8, 0.9),
        false_cutoff_budget=0.05,
        missed_turn_budget=0.05,
        max_response_delay_ms=1000.0,
        minimum_positive_conversations=100,
        minimum_negative_conversations=100,
    )


def test_selects_threshold_only_after_calibration_and_holdout_pass():
    report = calibrate_end_of_turn(cohort("calibration") + cohort("holdout"), config())
    group = report["groups"][0]
    assert group["status"] == "manual_review_recommended"
    assert group["selected_threshold"] == 0.8
    assert group["calibration_operating_point"]["p95_response_delay_ms"] == 100.0
    assert group["holdout_result"]["false_cutoffs"] == 0
    assert group["holdout_result"]["missed_turns"] == 0
    assert report["automatic_runtime_changes"] is False
    assert report["raw_examples_included"] is False


def test_false_cutoff_budget_rejects_aggressive_threshold():
    values = cohort("calibration") + cohort("holdout")
    for index, item in enumerate(values):
        if not item.is_turn_end:
            values[index] = EOTTrial(
                item.example_id, item.conversation_group, item.model_id, item.language,
                item.split, False, item.reference_ms, item.resume_ms,
                (ScoreObservation(1100.0, 0.85),),
            )
    report = calibrate_end_of_turn(values, config())
    group = report["groups"][0]
    assert group["status"] == "manual_review_recommended"
    assert group["selected_threshold"] == 0.9


def test_no_holdout_never_recommends_runtime_threshold():
    report = calibrate_end_of_turn(cohort("calibration"), config())
    group = report["groups"][0]
    assert group["status"] == "inconclusive_holdout_sample_size"
    assert group["selected_threshold"] is None
    assert group["candidate_threshold"] == 0.8


def test_insufficient_calibration_is_inconclusive():
    values = cohort("calibration")[:20]
    report = calibrate_end_of_turn(values, config())
    assert report["groups"][0]["status"] == "inconclusive_calibration_sample_size"


def test_missed_turn_budget_is_enforced():
    values = cohort("calibration") + cohort("holdout")
    for index, item in enumerate(values):
        if item.is_turn_end:
            values[index] = EOTTrial(
                item.example_id, item.conversation_group, item.model_id, item.language,
                item.split, True, item.reference_ms, None,
                (ScoreObservation(1100.0, 0.1),),
            )
    report = calibrate_end_of_turn(values, config())
    assert report["groups"][0]["status"] == "no_calibration_operating_point"


def test_decisions_after_speaker_resumes_are_not_false_cutoffs():
    examples = [
        trial("pause", end=False, scores=((1500.0, 0.99),),
              reference=1000.0, resume=1400.0),
        trial("end", end=True, scores=((1200.0, 0.99),), reference=1000.0),
    ]
    metrics = evaluate_threshold(examples, 0.5, config())
    assert metrics["false_cutoffs"] == 0
    assert metrics["median_response_delay_ms"] == 200.0


def test_first_crossing_defines_latency_not_the_last_high_score():
    item = trial("fast", scores=((1050.0, 0.81), (1300.0, 0.99)))
    metrics = evaluate_threshold([item], 0.8, config())
    assert metrics["median_response_delay_ms"] == 50.0


def test_duplicate_examples_are_rejected():
    item = trial("same")
    with pytest.raises(ValueError, match="duplicate"):
        calibrate_end_of_turn([item, item], config())


def test_raw_content_fields_are_rejected_at_ingest():
    raw = {
        "example_id": "id1", "conversation_group": "a" * 32,
        "model_id": "turn-v1-mini", "language": "en", "split": "calibration",
        "is_turn_end": True, "reference_ms": 1, "resume_ms": None,
        "observations": [{"at_ms": 2, "end_probability": 0.9}],
        "transcript": "private text",
    }
    with pytest.raises(ValueError, match="unsupported fields"):
        EOTTrial.from_mapping(raw)


def test_nonfinite_boolean_and_invalid_timestamps_are_rejected():
    with pytest.raises(ValueError):
        ScoreObservation(1, float("nan"))
    with pytest.raises(ValueError):
        trial("bool", reference=True)
    with pytest.raises(ValueError):
        trial("reverse", end=False, reference=1000, resume=999)
    with pytest.raises(ValueError):
        trial("early", end=True, reference=1000, scores=((999.0, 0.9),))
    with pytest.raises(ValueError):
        trial("unordered", scores=((1200.0, 0.9), (1100.0, 0.8)))


def test_config_requires_sorted_unique_thresholds_and_valid_budgets():
    with pytest.raises(ValueError):
        CalibrationConfig(thresholds=(0.5, 0.4))
    with pytest.raises(ValueError):
        CalibrationConfig(false_cutoff_budget=1.5)


def test_conversation_group_cannot_leak_across_calibration_and_holdout():
    calibration = trial("calibration-id", split="calibration", group="e" * 32)
    holdout = trial("holdout-id", split="holdout", group=calibration.conversation_group)
    with pytest.raises(ValueError, match="appears in both"):
        calibrate_end_of_turn([calibration, holdout], config())


def _jsonl_record(example_id, conversation_group, split, is_turn_end, reference_ms, resume_ms, observations):
    import json
    return json.dumps({
        "example_id": example_id, "conversation_group": conversation_group,
        "model_id": "turn-v1-mini", "language": "en", "split": split,
        "is_turn_end": is_turn_end, "reference_ms": reference_ms,
        "resume_ms": resume_ms,
        "observations": [{"at_ms": at, "end_probability": score} for at, score in observations],
    })


def test_cli_writes_aggregate_report_without_overwriting(tmp_path):
    from star.voice.eot_calibration import main
    source = tmp_path / "trials.jsonl"
    source.write_text("\n".join([
        _jsonl_record("p-cal", "a" * 32, "calibration", True, 1000, None, [(1200, 0.9)]),
        _jsonl_record("n-cal", "b" * 32, "calibration", False, 1000, 1400, [(1100, 0.1)]),
        _jsonl_record("p-hold", "c" * 32, "holdout", True, 1000, None, [(1200, 0.9)]),
        _jsonl_record("n-hold", "d" * 32, "holdout", False, 1000, 1400, [(1100, 0.1)]),
    ]) + "\n", encoding="utf-8")
    output = tmp_path / "report.json"
    args = [str(source), "--output", str(output), "--min-positive-conversations", "1",
            "--min-negative-conversations", "1", "--thresholds", "0.5"]
    assert main(args) == 0
    assert '"automatic_runtime_changes": false' in output.read_text(encoding="utf-8")
    assert main(args) == 2


def test_cli_rejects_duplicate_json_keys(tmp_path):
    from star.voice.eot_calibration import main
    source = tmp_path / "bad.jsonl"
    source.write_text('{"example_id":"x","example_id":"y"}\n', encoding="utf-8")
    assert main([str(source)]) == 2


def test_confidence_bounds_count_conversations_not_repeated_pause_rows():
    first = trial("pause-1", end=False, scores=((1100.0, 0.99),),
                  reference=1000.0, resume=1400.0, group="f" * 32)
    second = trial("pause-2", end=False, scores=((1150.0, 0.1),),
                   reference=1000.0, resume=1450.0, group="f" * 32)
    metrics = evaluate_threshold([first, second], 0.5, config())
    assert metrics["negative_examples"] == 2
    assert metrics["negative_conversations"] == 1
    assert metrics["false_cutoffs"] == 1
    assert metrics["false_cutoff_conversation_failures"] == 1
    assert metrics["false_cutoff_upper_confidence"] == 1.0
