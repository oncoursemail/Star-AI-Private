"""Tests for the offline multiparty floor-decision evaluator."""
from __future__ import annotations

from dataclasses import asdict
import json

import pytest

from benchmarks.stream_multiparty_floor_eval import (
    FloorEvalCase,
    evaluate_cases,
    load_cases,
)


def _case(
    event_id: str,
    conversation_id: str,
    split: str,
    gold_action: str,
    predicted_action: str,
    gold_addressee: str,
    gold_speech_act: str,
    *,
    predicted_addressee: str | None = None,
    predicted_speech_act: str | None = None,
    active_speakers: int = 1,
    receipt_age_ms: float = 30.0,
    decision_latency_ms: float = 150.0,
    response_probability: float = 0.5,
) -> FloorEvalCase:
    return FloorEvalCase(
        event_id=event_id,
        conversation_id=conversation_id,
        split=split,
        gold_action=gold_action,
        predicted_action=predicted_action,
        gold_addressee=gold_addressee,
        predicted_addressee=predicted_addressee or gold_addressee,
        gold_speech_act=gold_speech_act,
        predicted_speech_act=predicted_speech_act or gold_speech_act,
        active_speakers=active_speakers,
        receipt_age_ms=receipt_age_ms,
        decision_latency_ms=decision_latency_ms,
        response_probability=response_probability,
    )


def sample_cases() -> list[FloorEvalCase]:
    return [
        _case("E1", "C1", "calibration", "respond", "respond",
              "star", "question", response_probability=0.95, decision_latency_ms=180),
        _case("E2", "C1", "calibration", "silence", "respond",
              "other", "side_conversation", predicted_addressee="star",
              predicted_speech_act="question", active_speakers=2,
              response_probability=0.70, decision_latency_ms=200),
        _case("E3", "C2", "calibration", "backchannel", "backchannel",
              "star", "backchannel", response_probability=0.20, decision_latency_ms=110),
        _case("E4", "C2", "calibration", "listen", "listen",
              "group", "question", active_speakers=3,
              response_probability=0.15, decision_latency_ms=130),
        _case("E5", "C3", "holdout", "respond", "hold",
              "star", "request", response_probability=0.65, decision_latency_ms=240),
        _case("E6", "C3", "holdout", "hold", "hold",
              "unknown", "uncertain", active_speakers=2,
              response_probability=0.10, decision_latency_ms=210),
        _case("E7", "C4", "holdout", "silence", "silence",
              "other", "side_conversation", active_speakers=2,
              response_probability=0.05, decision_latency_ms=160),
        _case("E8", "C4", "holdout", "backchannel", "respond",
              "star", "backchannel", response_probability=0.60, decision_latency_ms=220),
        _case("E9", "C5", "holdout", "listen", "listen",
              "group", "statement", response_probability=0.30, decision_latency_ms=190),
        _case("E10", "C5", "holdout", "respond", "respond",
              "star", "correction", response_probability=0.95, decision_latency_ms=170),
    ]


def test_reports_conversation_disjoint_calibration_and_holdout_metrics():
    report = evaluate_cases(sample_cases())

    assert report["split_policy"] == "conversation-disjoint"
    assert report["calibration"]["event_count"] == 4
    assert report["holdout"]["event_count"] == 6
    assert report["calibration"]["response_precision_recall_f1"] == {
        "precision": 0.5, "recall": 1.0, "f1": 0.666667,
    }
    assert report["holdout"]["response_precision_recall_f1"] == {
        "precision": 0.5, "recall": 0.5, "f1": 0.5,
    }
    assert report["calibration"]["conversation_response_scored_count"] == 1
    assert report["holdout"]["conversation_response_scored_count"] == 3


def test_reports_social_floor_failures_and_latency_separately():
    report = evaluate_cases(sample_cases())
    holdout = report["holdout"]

    assert holdout["false_response_rate"] == 0.25
    assert holdout["group_address_response_rate"] == 0.0
    assert holdout["side_conversation_response_rate"] == 0.0
    assert holdout["backchannel_spoken_rate"] == 1.0
    assert holdout["overlap_response_rate"] == 0.0
    assert holdout["decision_latency_ms"]["p50"] == 200.0
    assert holdout["decision_latency_ms"]["p95"] == 235.0
    assert holdout["response_decision_latency_ms"]["p50"] == 195.0


def test_reports_addressee_act_and_probability_calibration():
    report = evaluate_cases(sample_cases())
    calibration = report["calibration"]

    assert calibration["addressee_accuracy"] == 0.75
    assert calibration["speech_act_accuracy"] == 0.75
    assert calibration["response_probability_calibration"]["count"] == 4
    assert 0.0 <= calibration["response_probability_calibration"]["brier"] <= 1.0
    assert 0.0 <= calibration["response_probability_calibration"]["ece_10_bins"] <= 1.0


def test_aggregate_output_does_not_echo_event_or_conversation_ids():
    report = str(evaluate_cases(sample_cases()))

    assert "E1" not in report
    assert "C1" not in report
    assert "event_id" not in report
    assert "conversation_id" not in report


def test_load_cases_accepts_strict_jsonl_and_reports_aggregate_only(tmp_path):
    path = tmp_path / "floor.jsonl"
    path.write_text(
        "".join(json.dumps(asdict(case)) + "\n" for case in sample_cases()),
        encoding="utf-8",
    )

    report = evaluate_cases(load_cases(path))
    assert report["holdout"]["event_count"] == 6
    assert report["privacy"].startswith("aggregate metrics only")


def test_rejects_duplicate_json_keys_and_unknown_fields(tmp_path):
    path = tmp_path / "floor.jsonl"
    path.write_text(
        '{"event_id":"E1","event_id":"E2"}\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_cases(path)

    row = asdict(sample_cases()[0])
    row["transcript"] = "must never be accepted"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly the declared fields"):
        load_cases(path)


def test_rejects_conversation_leakage_between_splits(tmp_path):
    path = tmp_path / "floor.jsonl"
    first = asdict(sample_cases()[0])
    second = asdict(sample_cases()[4])
    second["conversation_id"] = first["conversation_id"]
    path.write_text(
        json.dumps(first) + "\n" + json.dumps(second) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="both calibration and holdout"):
        load_cases(path)


def test_rejects_duplicate_events_invalid_probabilities_and_boolean_counts(tmp_path):
    path = tmp_path / "floor.jsonl"
    row = asdict(sample_cases()[0])
    row["active_speakers"] = True
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="active_speakers"):
        load_cases(path)

    row["active_speakers"] = 1
    row["response_probability"] = float("nan")
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="non-finite"):
        load_cases(path)

    row["response_probability"] = 0.5
    path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="repeats an event_id"):
        load_cases(path)


def test_requires_both_calibration_and_holdout_groups():
    rows = [
        _case("E1", "C1", "holdout", "respond", "respond", "star", "question"),
    ]
    with pytest.raises(ValueError, match="both calibration and holdout"):
        evaluate_cases(rows)


def test_rejects_invalid_case_values():
    with pytest.raises(ValueError, match="response_probability"):
        _case(
            "E1", "C1", "calibration", "respond", "respond", "star", "question",
            response_probability=1.1,
        )
    with pytest.raises(ValueError, match="active_speakers"):
        _case(
            "E1", "C1", "calibration", "respond", "respond", "star", "question",
            active_speakers=True,
        )


def test_selects_response_threshold_on_calibration_and_freezes_it_for_holdout():
    rows = []
    for index in range(10):
        rows.append(_case(
            f"CP{index}", f"CALP{index}", "calibration",
            "respond", "respond", "star", "question",
            response_probability=0.8 if index < 5 else 0.9,
        ))
    for index in range(10):
        rows.append(_case(
            f"CN{index}", f"CALN{index}", "calibration",
            "silence", "silence", "other", "side_conversation",
            response_probability=0.75 if index == 0 else 0.1,
        ))
    for index in range(5):
        rows.append(_case(
            f"HP{index}", f"HOLDP{index}", "holdout",
            "respond", "respond", "star", "question",
            response_probability=0.85,
        ))
    for index in range(5):
        rows.append(_case(
            f"HN{index}", f"HOLDN{index}", "holdout",
            "silence", "silence", "other", "side_conversation",
            response_probability=0.95,
        ))

    selection = evaluate_cases(
        rows, max_calibration_false_response_rate=0.05,
    )["response_threshold_selection"]

    assert selection["status"] == "selected"
    assert selection["selected_threshold"] == 0.75
    assert selection["calibration_metrics"]["false_response_rate"] == 0.0
    assert selection["calibration_metrics"]["recall"] == 1.0
    # Holdout is scored with the frozen calibration threshold; it is not retuned.
    assert selection["holdout_metrics"]["false_response_rate"] == 1.0
    assert selection["holdout_metrics"]["recall"] == 1.0


def test_threshold_selection_declines_small_calibration_sets():
    selection = evaluate_cases(sample_cases())["response_threshold_selection"]

    assert selection["status"] == "insufficient_calibration"
    assert selection["selected_threshold"] is None
    assert selection["holdout_metrics"] is None
    assert selection["observed_events"] == 4


@pytest.mark.parametrize("rate", [True, -0.01, 1.01, float("nan")])
def test_threshold_selection_rejects_invalid_false_response_budgets(rate):
    with pytest.raises(ValueError, match="max_calibration_false_response_rate"):
        evaluate_cases(sample_cases(), max_calibration_false_response_rate=rate)
