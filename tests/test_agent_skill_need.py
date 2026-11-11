"""Tests for need-aware Agent Skill incorporation evaluation."""
import json

import pytest

from benchmarks.agent_skill_need import NeedCase, evaluate_cases, load_cases


def sample_cases():
    return [
        NeedCase("T1", "private Roblox task", "required", ("roblox-luau-review",),
                 0.9, "load", ("roblox-luau-review",), "fail", "pass", 100.0, 200),
        NeedCase("T2", "private Python task", "required", ("python-typing",),
                 0.8, "skip", (), "fail", "not_run", 0.0, 0),
        NeedCase("T3", "simple arithmetic", "not_needed", (),
                 0.1, "skip", (), "pass", "not_run", 0.0, 0),
        NeedCase("T4", "simple factual lookup", "not_needed", (),
                 0.7, "load", ("python-typing",), "pass", "fail", 20.0, 50),
        NeedCase("T5", "optional Blender workflow", "optional", ("blender-modeling",),
                 0.4, "load", ("blender-modeling",), "fail", "pass", 80.0, 100),
    ]


def test_reports_need_decision_calibration_and_skill_recall():
    report = evaluate_cases(sample_cases())

    assert report["need_decision_true_positive"] == 1
    assert report["need_decision_false_positive"] == 1
    assert report["need_decision_false_negative"] == 1
    assert report["need_decision_true_negative"] == 1
    assert report["need_decision_precision"] == 0.5
    assert report["need_decision_recall"] == 0.5
    assert report["need_decision_f1"] == 0.5
    assert report["need_probability_brier"] == 0.1375
    assert report["required_gold_skill_recall"] == 0.5
    assert report["loaded_skill_precision"] == pytest.approx(2 / 3)
    assert report["not_needed_false_load_rate"] == 0.5
    assert report["optional_load_rate"] == 1.0


def test_reports_paired_skill_utility_and_load_cost():
    report = evaluate_cases(sample_cases())

    assert report["skill_assisted_pair_count"] == 3
    assert report["paired_candidate_wins"] == 2
    assert report["paired_candidate_losses"] == 1
    assert report["paired_success_gain"] == pytest.approx(1 / 3)
    assert report["load_attempt_count"] == 3
    assert report["load_latency_p50_ms"] == 80.0
    assert report["loaded_tokens_total"] == 350


def test_report_does_not_echo_queries_or_task_ids():
    report = str(evaluate_cases(sample_cases()))
    assert "private Roblox task" not in report
    assert "T1" not in report


def test_load_cases_accepts_strict_jsonl(tmp_path):
    path = tmp_path / "cases.jsonl"
    row = {
        "task_id": "T1", "query": "Roblox server validation", "need": "required",
        "relevant_skills": ["roblox-luau-review"], "need_probability": 0.9,
        "decision": "load", "loaded_skills": ["roblox-luau-review"],
        "no_skill_outcome": "fail", "assisted_outcome": "pass",
        "load_latency_ms": 42.5, "loaded_tokens": 512,
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    cases = load_cases(path)
    assert len(cases) == 1
    assert evaluate_cases(cases)["required_gold_skill_recall"] == 1.0


def test_rejects_duplicate_json_keys(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        '{"task_id":"T1","task_id":"T2","query":"some task",'
        '"need":"required","relevant_skills":["python-typing"],'
        '"need_probability":0.8,"decision":"load","loaded_skills":[], '
        '"no_skill_outcome":"fail","assisted_outcome":"not_run",'
        '"load_latency_ms":0,"loaded_tokens":0}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_cases(path)


def test_rejects_invalid_gold_labels_and_duplicate_task_ids(tmp_path):
    path = tmp_path / "cases.jsonl"
    row = {
        "task_id": "T1", "query": "some task", "need": "not_needed",
        "relevant_skills": ["python-typing"], "need_probability": 0.1,
        "decision": "skip", "loaded_skills": [], "no_skill_outcome": "pass",
        "assisted_outcome": "not_run", "load_latency_ms": 0, "loaded_tokens": 0,
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not_needed"):
        load_cases(path)

    row["need"] = "required"
    path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="repeats task_id"):
        load_cases(path)


def test_rejects_inconsistent_skip_load_cost_and_outcome(tmp_path):
    path = tmp_path / "cases.jsonl"
    row = {
        "task_id": "T1", "query": "some task", "need": "required",
        "relevant_skills": ["python-typing"], "need_probability": 0.8,
        "decision": "skip", "loaded_skills": [], "no_skill_outcome": "fail",
        "assisted_outcome": "pass", "load_latency_ms": 0, "loaded_tokens": 0,
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="require at least one loaded skill"):
        load_cases(path)


def test_rejects_boolean_probability_and_nonfinite_latency(tmp_path):
    path = tmp_path / "cases.jsonl"
    row = {
        "task_id": "T1", "query": "some task", "need": "required",
        "relevant_skills": ["python-typing"], "need_probability": True,
        "decision": "skip", "loaded_skills": [], "no_skill_outcome": "fail",
        "assisted_outcome": "not_run", "load_latency_ms": 0, "loaded_tokens": 0,
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="need_probability"):
        load_cases(path)

    row["need_probability"] = 0.5
    row["load_latency_ms"] = float("inf")
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_cases(path)


def test_optional_tasks_are_excluded_from_binary_need_calibration():
    report = evaluate_cases(sample_cases())
    assert report["required_count"] == 2
    assert report["not_needed_count"] == 2
    assert report["optional_count"] == 1
    assert report["need_decision_true_positive"] + report["need_decision_false_positive"] + \
        report["need_decision_false_negative"] + report["need_decision_true_negative"] == 4


def test_all_optional_cases_do_not_divide_by_zero():
    case = NeedCase("T1", "optional workflow", "optional", ("python-typing",),
                    0.5, "skip", (), "pass", "not_run", 0.0, 0)
    report = evaluate_cases([case])
    assert report["need_probability_brier"] == 0.0
    assert report["need_probability_ece_10_bins"] == 0.0
    assert report["optional_load_rate"] == 0.0


def test_dataclass_rejects_unvalidated_cases():
    with pytest.raises(ValueError, match="not_needed"):
        NeedCase("T1", "invalid gold", "not_needed", ("python-typing",),
                 0.1, "skip", (), "pass", "not_run", 0.0, 0)
