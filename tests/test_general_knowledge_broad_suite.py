"""Domain coverage and scoring for STAR's broad general-knowledge development suite."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

import pytest

from star import general_knowledge_benchmark as bench


ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "evals/general_knowledge/broad-development-v1.prompts.json"
ORACLES_PATH = ROOT / "evals/general_knowledge/broad-development-v1.oracles.json"


def model(name="fixture-model"):
    return {
        "model_id": name,
        "revision": "fixture-revision",
        "weights_sha256": "b" * 64,
        "tokenizer_sha256": "c" * 64,
        "quantization": "fixture-q4",
    }


def identity():
    return {
        "app_commit": "a" * 40,
        "source_sha256": "a" * 64,
        "request_builder_sha256": "d" * 64,
        "adapter_sha256": "e" * 64,
        "backend_build": "fixture-build",
        "model": model(),
        "mode": "direct_text",
        "options": {
            "temperature": 0,
            "top_p": 1,
            "max_output_tokens": 128,
            "seed": None,
            "stop": [],
            "tools": [],
        },
    }


def artifacts():
    suite = bench.load_suite(SUITE_PATH)
    return suite, bench.load_oracles(suite, ORACLES_PATH)


def answer(row, value):
    row["response"] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    row["response_sha256"] = bench.digest(row["response"].encode("utf-8"))


def raw_run(suite, oracles):
    plan = bench.prepare(suite)
    rows = []
    for request in plan["requests"]:
        row = {
            key: request[key]
            for key in ("task_id", "attempt", "request_sha256")
        }
        row.update(outcome="completed", error_code=None)
        answer(row, oracles.data["cases"][request["task_id"]]["expected"])
        rows.append(row)
    return {
        "schema_version": 1,
        "kind": "general_foundation_raw_run",
        "suite_id": suite.data["suite_id"],
        "suite_sha256": suite.sha256,
        "oracle_sha256": oracles.sha256,
        "grader_sha256": bench.grader_digest(),
        "identity": identity(),
        "repeats": 1,
        "rows": rows,
    }


def test_broad_suite_has_two_tasks_in_each_of_twelve_domains():
    suite, oracles = artifacts()
    counts = Counter(task["category"] for task in suite.data["tasks"])
    assert len(suite.data["tasks"]) == 24
    assert len(counts) == 12
    assert set(counts.values()) == {2}
    assert set(oracles.data["cases"]) == {task["id"] for task in suite.data["tasks"]}


def test_all_reviewed_development_oracles_score_and_report_each_domain():
    suite, oracles = artifacts()
    report = bench.score_run(suite, oracles, raw_run(suite, oracles))
    assert report["counts"] == {"pass": 24}
    assert report["total"] == 24
    assert len(report["category_counts"]) == 12
    assert all(counts == {"pass": 2} for counts in report["category_counts"].values())
    assert all("response" not in row for row in report["rows"])
    assert report["provenance"] == "operator_declared_not_authenticated"


def test_one_wrong_answer_is_visible_in_its_domain_not_hidden_by_overall_average():
    suite, oracles = artifacts()
    run = raw_run(suite, oracles)
    answer(run["rows"][0], {"planet": "Saturn"})
    report = bench.score_run(suite, oracles, run)
    assert report["counts"] == {"pass": 23, "incorrect": 1}
    assert report["category_counts"]["astronomy"] == {"incorrect": 1, "pass": 1}
    assert all(
        counts == {"pass": 2}
        for category, counts in report["category_counts"].items()
        if category != "astronomy"
    )


def test_preparation_exposes_no_oracle_sidecar(monkeypatch):
    suite = bench.load_suite(SUITE_PATH)
    monkeypatch.setattr(
        bench,
        "load_oracles",
        lambda *args, **kwargs: pytest.fail("prepare must not load oracle data"),
    )
    plan = bench.prepare(suite)
    assert len(plan["requests"]) == 24
    assert plan["category_counts"]["astronomy"] == 2
    assert all("messages" in request for request in plan["requests"])
    assert all("category" not in request for request in plan["requests"])


def test_category_metadata_is_pinned_into_request_identity(tmp_path):
    suite = bench.load_suite(SUITE_PATH)
    before = bench.prepare(suite)
    data = suite.data
    data["tasks"][0]["category"] = "alternate_domain"
    changed_path = tmp_path / "changed-suite.json"
    changed_path.write_text(json.dumps(data), encoding="utf-8")
    changed = bench.load_suite(changed_path)
    after = bench.prepare(changed)
    assert before["suite_sha256"] != after["suite_sha256"]
    assert before["requests"][0]["request_sha256"] != after["requests"][0]["request_sha256"]


def test_oracle_case_set_must_match_broad_suite_exactly(tmp_path):
    suite = bench.load_suite(SUITE_PATH)
    data = json.loads(ORACLES_PATH.read_text(encoding="utf-8"))
    data["cases"].pop("GF-24")
    path = tmp_path / "incomplete-oracles.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        bench.load_oracles(suite, path)


def test_malformed_calendar_date_is_rejected_by_the_oracle_loader(tmp_path):
    suite = bench.load_suite(SUITE_PATH)
    data = json.loads(ORACLES_PATH.read_text(encoding="utf-8"))
    data["cases"]["GF-11"]["expected"]["date"] = "1969-02-30"
    path = tmp_path / "bad-date-oracles.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        bench.load_oracles(suite, path)


def test_cli_list_reports_suite_specific_scope_and_domain_counts(capsys):
    assert bench.main(["list", "--suite", str(SUITE_PATH)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["suite_id"] == "star-general-foundations-broad-development-v1"
    assert report["category_counts"]["evidence_reasoning"] == 2
    assert len(report["tasks"]) == 24


def test_old_ten_task_development_suite_remains_backward_compatible():
    suite = bench.load_suite()
    assert len(suite.data["tasks"]) == 10
    assert len(bench.load_oracles(suite).data["cases"]) == 10
