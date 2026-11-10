from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from star.model_quality_speed_gate import (
    EvidenceError,
    evaluate_gate,
    main,
    parse_json,
)

DOMAINS = [
    "astronomy", "chemistry", "biology", "physics", "geography", "history",
    "literature", "computing", "language", "environment", "civics", "evidence",
]
WORKLOADS = [
    "short_chat", "general_knowledge", "reasoning", "luau",
    "debugging", "game_strategy", "stream_commentary", "summarization",
]


def model(alias: str, weight: str) -> dict[str, Any]:
    return {
        "model_id": alias,
        "revision": "rev-1",
        "weights_sha256": weight * 64,
        "tokenizer_sha256": "c" * 64,
        "quantization": "Q4_K_M",
    }


def identity(alias: str, weight: str) -> dict[str, Any]:
    return {
        "app_commit": "a" * 40,
        "source_sha256": "b" * 64,
        "request_builder_sha256": "d" * 64,
        "adapter_sha256": "e" * 64,
        "backend_build": "llama.cpp-test-build",
        "model": model(alias, weight),
        "mode": "auto",
        "options": {
            "temperature": 0.2,
            "top_p": 1.0,
            "max_output_tokens": 128,
            "seed": 123,
            "stop": [],
            "tools": [],
        },
    }


def score(alias: str, weight: str, bad_domain: str | None = None) -> dict[str, Any]:
    rows = []
    category_counts: dict[str, Counter[str]] = {}
    counts = Counter()
    for index, domain in enumerate(DOMAINS, start=1):
        for offset in range(2):
            task_id = f"GF-{index * 2 - 1 + offset:02}"
            status = "incorrect" if domain == bad_domain and offset == 0 else "pass"
            row = {
                "task_id": task_id,
                "attempt": 1,
                "request_sha256": f"{index * 2 - 1 + offset:064x}",
                "response_sha256": (
                    f"{index * 2 - 1 + offset + (1 if alias == 'star-deep' else 50):064x}"
                ),
                "error_code": None,
                "category": domain,
                "status": status,
            }
            rows.append(row)
            counts[status] += 1
            category_counts.setdefault(domain, Counter())[status] += 1
    return {
        "schema_version": 1,
        "kind": "general_foundation_scores",
        "suite_sha256": "1" * 64,
        "oracle_sha256": "2" * 64,
        "grader_sha256": "3" * 64,
        "identity": identity(alias, weight),
        "provenance": "operator_declared_not_authenticated",
        "scope": "24 public development tasks across 12 domains; not a holdout",
        "repeats": 1,
        "total": 24,
        "counts": dict(counts),
        "category_counts": {
            name: dict(sorted(values.items()))
            for name, values in sorted(category_counts.items())
        },
        "rows": rows,
    }


def quality(bad_domain: str | None = None) -> dict[str, Any]:
    before = score("star-fast", "4")
    after = score("star-deep", "5", bad_domain)
    changes = []
    for left, right in zip(before["rows"], after["rows"]):
        if left["status"] != right["status"]:
            changes.append({
                "task_id": left["task_id"],
                "category": left["category"],
                "attempt": left["attempt"],
                "baseline": left["status"],
                "candidate": right["status"],
            })
    return {
        "kind": "general_foundation_comparison",
        "axis": "model",
        "provenance": "operator_declared_not_authenticated",
        "scope": before["scope"],
        "comparison_status": "artifact_consistent",
        "baseline": before,
        "candidate": after,
        "changes": changes,
    }


def summary(samples: int, *, delta: float = -10.0, incomplete: int = 0) -> dict[str, Any]:
    empty = samples == 0
    return {
        "paired_samples": samples,
        "incomplete_pairs": incomplete,
        "baseline_first_content_p50_ms": None if empty else 100.0,
        "candidate_first_content_p50_ms": None if empty else 90.0 + (delta + 10.0),
        "first_content_delta_p50_ms": None if empty else delta,
        "first_content_delta_p95_ms": None if empty else (-5.0 if delta < 0 else delta),
        "candidate_faster_pairs": max(0, samples - 2),
        "candidate_tied_pairs": 1 if samples else 0,
        "candidate_slower_pairs": 1 if samples > 1 else 0,
        "baseline_end_to_end_p50_ms": None if empty else 500.0,
        "candidate_end_to_end_p50_ms": None if empty else 480.0,
        "end_to_end_delta_p50_ms": None if empty else -20.0,
        "tie_threshold_ms": 0.5,
    }


def paired(
    *, slow: bool = False, incomplete: bool = False, all_incomplete: bool = False
) -> dict[str, Any]:
    schedule: list[dict[str, Any]] = []
    totals = Counter()
    for index in range(16):
        category = WORKLOADS[index % len(WORKLOADS)]
        totals[category] += 1
        schedule.append({
            "pair_id": index,
            "category": category,
            "model_order": (
                ["star-fast", "star-deep"]
                if index % 2 == 0
                else ["star-deep", "star-fast"]
            ),
        })
    category_reports = {
        category: summary(
            0 if all_incomplete else (
                count - (1 if incomplete and category == "luau" else 0)
            ),
            delta=15.0 if slow and category == "luau" else -10.0,
            incomplete=count if all_incomplete else (
                1 if incomplete and category == "luau" else 0
            ),
        )
        for category, count in totals.items()
    }
    overall = summary(
        0 if all_incomplete else (15 if incomplete else 16),
        delta=2.0 if slow else -10.0,
        incomplete=16 if all_incomplete else (1 if incomplete else 0),
    )
    return {
        "schema_version": 1,
        "verdict": "no_complete_pairs" if all_incomplete else "paired_observations",
        "baseline_model": "star-fast",
        "models": ["star-fast", "star-deep"],
        "seed": 42,
        "pair_count": 16,
        "total_requests": 32,
        "successful_requests": 0 if all_incomplete else (31 if incomplete else 32),
        "failed_requests": 32 if all_incomplete else (1 if incomplete else 0),
        "wall_ms": 30000.0,
        "warmup_ms": 1000.0,
        "warmup_by_model_ms": {"star-fast": 500.0, "star-deep": 500.0},
        "pair_schedule": schedule,
        "by_candidate": {
            "star-deep": {
                "overall": overall,
                "by_category": category_reports,
            }
        },
        "note": "Synthetic fixture; no real model or hardware measurement.",
    }


def metrics(alias: str, prompt: float, generation: float) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "available": True,
        "scope": "model_query",
        "model_query": alias,
        "duration_seconds": 60.0,
        "counter_deltas": {
            "llamacpp:prompt_tokens_total": 100.0,
            "llamacpp:prompt_seconds_total": 2.0,
            "llamacpp:tokens_predicted_total": 200.0,
            "llamacpp:tokens_predicted_seconds_total": 4.0,
        },
        "counter_resets": [],
        "missing_counters": [],
        "prompt_tokens_per_second_from_counters": prompt,
        "generated_tokens_per_second_from_counters": generation,
        "speculative_acceptance_ratio": 0.8,
        "gauges_before": {},
        "gauges_after": {},
        "context_tokens_high_watermark_after": 4096,
        "attribution": "aggregate only",
    }


def test_passing_evidence_only_recommends_manual_review():
    result = evaluate_gate(paired(), quality())
    assert result["decision"] == "manual_review_recommended"
    assert result["automatic_route_change_authorized"] is False
    assert result["live_vtuber_rollout_authorized"] is False
    assert result["holdout_evaluation_required"] is True


def test_latency_regression_keeps_baseline():
    result = evaluate_gate(paired(slow=True), quality())
    assert result["decision"] == "keep_baseline"
    assert "first_content_gain_below_5_percent_or_5ms" in result["reasons"]
    assert "luau_latency_regression" in result["reasons"]


def test_quality_domain_regression_keeps_baseline():
    result = evaluate_gate(paired(), quality(bad_domain="biology"))
    assert result["decision"] == "keep_baseline"
    assert "biology_quality_regression" in result["reasons"]


def test_incomplete_pairs_are_inconclusive():
    result = evaluate_gate(paired(incomplete=True), quality())
    assert result["decision"] == "inconclusive"
    assert "incomplete_paired_requests" in result["reasons"]


def test_quality_model_alias_must_match_paired_report():
    artifact = quality()
    artifact["candidate"]["identity"]["model"]["model_id"] = "other-model"
    with pytest.raises(EvidenceError, match="do not match"):
        evaluate_gate(paired(), artifact)


def test_same_weight_identity_cannot_masquerade_as_candidate():
    artifact = quality()
    artifact["candidate"]["identity"]["model"]["weights_sha256"] = "4" * 64
    with pytest.raises(EvidenceError, match="identical"):
        evaluate_gate(paired(), artifact)


def test_three_model_report_is_rejected_as_ambiguous():
    artifact = paired()
    artifact["models"].append("star-third")
    artifact["total_requests"] = 48
    artifact["successful_requests"] = 48
    artifact["warmup_by_model_ms"]["star-third"] = 400.0
    for row in artifact["pair_schedule"]:
        row["model_order"].append("star-third")
    artifact["by_candidate"]["star-third"] = copy.deepcopy(artifact["by_candidate"]["star-deep"])
    with pytest.raises(EvidenceError, match="exactly one"):
        evaluate_gate(artifact, quality())


def test_optional_server_metrics_are_reported_as_aggregate_corroboration():
    result = evaluate_gate(
        paired(), quality(),
        baseline_server_metrics=metrics("star-fast", 500.0, 30.0),
        candidate_server_metrics=metrics("star-deep", 550.0, 32.0),
    )
    assert result["decision"] == "manual_review_recommended"
    assert result["server_metrics"]["candidate_to_baseline_generation_rate_ratio"] == 1.0667
    assert "aggregate corroboration only" in result["server_metrics"]["interpretation"]


def test_server_metrics_model_scope_mismatch_is_rejected():
    with pytest.raises(EvidenceError, match="expected router model"):
        evaluate_gate(
            paired(), quality(),
            baseline_server_metrics=metrics("wrong", 500.0, 30.0),
            candidate_server_metrics=metrics("star-deep", 550.0, 32.0),
        )


def test_only_one_server_metrics_artifact_is_rejected():
    with pytest.raises(EvidenceError, match="both baseline"):
        evaluate_gate(
            paired(), quality(),
            baseline_server_metrics=metrics("star-fast", 500.0, 30.0),
        )


def test_duplicate_json_keys_are_rejected():
    with pytest.raises(EvidenceError, match="duplicate"):
        parse_json(b'{"decision":"manual_review_recommended","decision":"keep_baseline"}')


def test_quality_category_counts_must_match_rows():
    artifact = quality()
    artifact["candidate"]["category_counts"]["biology"] = {"pass": 1}
    with pytest.raises(EvidenceError, match="category totals"):
        evaluate_gate(paired(), artifact)


def test_per_workload_summaries_must_cover_schedule():
    artifact = paired()
    del artifact["by_candidate"]["star-deep"]["by_category"]["luau"]
    with pytest.raises(EvidenceError, match="do not cover"):
        evaluate_gate(artifact, quality())


def test_evidence_hashes_are_attached_to_report():
    import hashlib
    paired_bytes = json.dumps(paired(), sort_keys=True).encode()
    quality_bytes = json.dumps(quality(), sort_keys=True).encode()
    result = evaluate_gate(
        paired(), quality(),
        paired_sha256=hashlib.sha256(paired_bytes).hexdigest(),
        quality_sha256=hashlib.sha256(quality_bytes).hexdigest(),
    )
    assert result["evidence_sha256"]["paired"] == hashlib.sha256(paired_bytes).hexdigest()


def test_quality_comparison_must_use_same_scope_and_shared_identity():
    artifact = quality()
    artifact["candidate"]["identity"]["backend_build"] = "different-build"
    with pytest.raises(EvidenceError, match="same application"):
        evaluate_gate(paired(), artifact)


def test_invalid_boolean_numeric_measurement_is_rejected():
    artifact = paired()
    artifact["by_candidate"]["star-deep"]["overall"]["baseline_first_content_p50_ms"] = True
    with pytest.raises(EvidenceError, match="finite number"):
        evaluate_gate(artifact, quality())


def test_first_content_p95_delta_cannot_be_better_than_its_median():
    artifact = paired()
    artifact["by_candidate"]["star-deep"]["overall"]["first_content_delta_p95_ms"] = -15.0
    with pytest.raises(EvidenceError, match="p95 delta is below"):
        evaluate_gate(artifact, quality())


def test_pair_schedule_must_include_both_order_permutations():
    artifact = paired()
    for row in artifact["pair_schedule"]:
        row["model_order"] = ["star-fast", "star-deep"]
    with pytest.raises(EvidenceError, match="both model-order"):
        evaluate_gate(artifact, quality())


def test_server_metrics_require_real_counter_deltas():
    base = metrics("star-fast", 500.0, 30.0)
    candidate = metrics("star-deep", 550.0, 32.0)
    candidate["counter_deltas"] = {
        "llamacpp:prompt_tokens_total": 100.0,
        "llamacpp:prompt_seconds_total": 2.0,
        "llamacpp:tokens_predicted_total": None,
        "llamacpp:tokens_predicted_seconds_total": 3.0,
    }
    with pytest.raises(EvidenceError, match="finite number"):
        evaluate_gate(
            paired(), quality(),
            baseline_server_metrics=base,
            candidate_server_metrics=candidate,
        )


def test_cli_writes_a_valid_report_and_never_overwrites(tmp_path: Path):
    paired_path = tmp_path / "paired.json"
    quality_path = tmp_path / "quality.json"
    output_path = tmp_path / "gate.json"
    paired_path.write_text(json.dumps(paired()), encoding="utf-8")
    quality_path.write_text(json.dumps(quality()), encoding="utf-8")
    args = [
        "--paired", str(paired_path),
        "--quality", str(quality_path),
        "--output", str(output_path),
    ]
    assert main(args) == 0
    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["decision"] == "manual_review_recommended"
    assert main(args) == 2


def test_zero_complete_pairs_are_inconclusive_not_a_parser_crash():
    result = evaluate_gate(paired(all_incomplete=True), quality())
    assert result["decision"] == "inconclusive"
    assert "incomplete_paired_requests" in result["reasons"]
    assert "insufficient_paired_samples" in result["reasons"]
