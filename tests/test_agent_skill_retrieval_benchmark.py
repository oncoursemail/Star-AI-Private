"""Tests for the offline installed-skill retrieval evaluator."""
import json

import pytest

from benchmarks.agent_skill_retrieval import (
    RetrievalCase,
    evaluate_cases,
    load_cases,
)


def test_evaluator_reports_recall_mrr_and_ndcg_at_k():
    calls = []

    def search(query):
        calls.append(query)
        return [
            {"name": "unrelated"},
            {"name": "gold-one"},
            {"name": "gold-two"},
        ]

    report = evaluate_cases(
        [RetrievalCase("find a relevant skill", ("gold-one", "gold-two"))],
        search,
        k=3,
    )

    assert report["recall_at_k"] == 1.0
    assert report["mrr_at_k"] == 0.5
    assert report["ndcg_at_k"] == pytest.approx(
        (1 / 1.0 + 1 / 1.5849625007)
        / (1 / 1.0 + 1 / 1.5849625007)
    )
    assert len(calls) == 2
    assert report["query_count"] == 1


def test_evaluator_reports_first_and_warm_latency_without_raw_queries():
    report = evaluate_cases(
        [RetrievalCase("private query text", ("python-typing",))],
        lambda query: [{"name": "python-typing"}],
    )

    assert report["first_query_ms"] >= 0
    assert report["first_pass_p50_ms"] >= 0
    assert report["warm_pass_p95_ms"] >= 0
    assert "private query text" not in str(report)


def test_evaluator_rejects_empty_cases_and_invalid_cutoffs():
    with pytest.raises(ValueError):
        evaluate_cases([], lambda query: [])
    with pytest.raises(ValueError):
        evaluate_cases(
            [RetrievalCase("some query", ("python-typing",))],
            lambda query: [],
            k=True,
        )


def test_load_cases_accepts_strict_gold_label_jsonl(tmp_path):
    dataset = tmp_path / "queries.jsonl"
    dataset.write_text(
        json.dumps({
            "query": "Roblox server validation",
            "relevant_skills": ["roblox-secure-remotes", "roblox-luau-review"],
        }) + "\n",
        encoding="utf-8",
    )

    cases = load_cases(dataset)
    assert cases == [
        RetrievalCase(
            "Roblox server validation",
            ("roblox-secure-remotes", "roblox-luau-review"),
        )
    ]


def test_load_cases_rejects_duplicate_json_keys(tmp_path):
    dataset = tmp_path / "queries.jsonl"
    dataset.write_text(
        '{"query":"one query","query":"another","relevant_skills":["python-typing"]}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_cases(dataset)


def test_load_cases_rejects_unknown_fields_and_invalid_skill_names(tmp_path):
    dataset = tmp_path / "queries.jsonl"
    dataset.write_text(
        json.dumps({
            "query": "some valid query",
            "relevant_skills": ["../outside"],
        }) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="relevant_skills"):
        load_cases(dataset)

    dataset.write_text(
        json.dumps({
            "query": "some valid query",
            "relevant_skills": ["python-typing"],
            "extra": "not accepted",
        }) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="exactly query and relevant_skills"):
        load_cases(dataset)
