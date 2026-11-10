"""Evidence-only quality/speed gate for STAR model experiments.

This module never changes the active model route. It combines a randomized
paired latency report with a provenance-bound general-knowledge comparison.
A passing result is a request for human review, never deployment authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_NODES = 50_000
MAX_DEPTH = 16
MIN_PAIRED_SAMPLES = 16
MIN_PAIRS_PER_WORKLOAD = 2
WORKLOADS = frozenset({
    "short_chat", "general_knowledge", "reasoning", "luau",
    "debugging", "game_strategy", "stream_commentary", "summarization",
})
STATUSES = frozenset({"pass", "incorrect", "invalid_format", "empty", "transport_error"})
_SCORE_KEYS = {
    "schema_version", "kind", "suite_sha256", "oracle_sha256", "grader_sha256",
    "identity", "provenance", "scope", "repeats", "total", "counts",
    "category_counts", "rows",
}
_IDENTITY_KEYS = {
    "app_commit", "source_sha256", "request_builder_sha256", "adapter_sha256",
    "backend_build", "model", "mode", "options",
}
_MODEL_KEYS = {"model_id", "revision", "weights_sha256", "tokenizer_sha256", "quantization"}
_ROW_KEYS = {
    "task_id", "attempt", "request_sha256", "response_sha256",
    "error_code", "category", "status",
}
_PAIRED_KEYS = {
    "schema_version", "verdict", "baseline_model", "models", "seed",
    "pair_count", "total_requests", "successful_requests", "failed_requests",
    "wall_ms", "warmup_ms", "warmup_by_model_ms", "pair_schedule",
    "by_candidate", "note",
}
_COMPARISON_KEYS = {
    "paired_samples", "incomplete_pairs", "baseline_first_content_p50_ms",
    "candidate_first_content_p50_ms", "first_content_delta_p50_ms",
    "first_content_delta_p95_ms", "candidate_faster_pairs",
    "candidate_tied_pairs", "candidate_slower_pairs",
    "baseline_end_to_end_p50_ms", "candidate_end_to_end_p50_ms",
    "end_to_end_delta_p50_ms", "tie_threshold_ms",
}
_METRIC_KEYS = {
    "schema_version", "available", "scope", "model_query", "duration_seconds",
    "counter_deltas", "counter_resets", "missing_counters",
    "prompt_tokens_per_second_from_counters",
    "generated_tokens_per_second_from_counters",
    "speculative_acceptance_ratio", "gauges_before", "gauges_after",
    "context_tokens_high_watermark_after", "attribution",
}


class EvidenceError(ValueError):
    """An evidence artifact is malformed, inconsistent, or unsafe to compare."""


def _keys(value: Any, expected: set[str], label: str) -> None:
    if type(value) is not dict or set(value) != expected:
        raise EvidenceError(f"{label} has unknown or missing fields")


def _int(value: Any, low: int, high: int, label: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise EvidenceError(f"{label} is outside its allowed integer range")
    return value


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if type(value) not in (int, float):
        raise EvidenceError(f"{label} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise EvidenceError(f"{label} must be finite") from exc
    if not math.isfinite(number) or (positive and number <= 0):
        qualifier = "positive and finite" if positive else "finite"
        raise EvidenceError(f"{label} must be {qualifier}")
    return number


def _label(value: Any, label: str) -> str:
    if (type(value) is not str
            or not re.fullmatch(r"[^\s\x00-\x1f\x7f]{1,180}", value)):
        raise EvidenceError(f"{label} is not a valid bounded identifier")
    return value


def _hash(value: Any, label: str, length: int = 64) -> str:
    if type(value) is not str or re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is None:
        raise EvidenceError(f"{label} must be a lowercase SHA-256/SHA-1 digest")
    return value


def _tree(value: Any) -> None:
    stack = [(value, 0)]
    count = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            raise EvidenceError("JSON complexity limit exceeded")
        if type(item) is dict:
            stack.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            stack.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            item.encode("utf-8")
        elif type(item) is float and not math.isfinite(item):
            raise EvidenceError("non-finite JSON number")
        elif type(item) is int and abs(item) > 10**18:
            raise EvidenceError("JSON integer limit exceeded")


def parse_json(data: bytes) -> Any:
    if type(data) is not bytes or len(data) > MAX_FILE_BYTES:
        raise EvidenceError("JSON artifact exceeds the byte limit")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise EvidenceError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise EvidenceError("non-finite JSON number")

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=unique,
            parse_constant=reject_constant,
        )
        _tree(value)
        return value
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise EvidenceError("invalid bounded JSON artifact") from exc


def load_artifact(path: Path) -> tuple[dict[str, Any], str]:
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise EvidenceError("JSON artifact exceeds the byte limit")
    value = parse_json(data)
    if type(value) is not dict:
        raise EvidenceError("top-level artifact must be an object")
    return value, hashlib.sha256(data).hexdigest()


def _validate_model(model: Any) -> dict[str, Any]:
    _keys(model, _MODEL_KEYS, "model identity")
    _label(model["model_id"], "model_id")
    _label(model["revision"], "model revision")
    _hash(model["weights_sha256"], "weights_sha256")
    _hash(model["tokenizer_sha256"], "tokenizer_sha256")
    _label(model["quantization"], "quantization")
    return model


def _validate_identity(identity: Any) -> dict[str, Any]:
    _keys(identity, _IDENTITY_KEYS, "model identity")
    _hash(identity["app_commit"], "app_commit", 40)
    for key in ("source_sha256", "request_builder_sha256", "adapter_sha256"):
        _hash(identity[key], key)
    _label(identity["backend_build"], "backend_build")
    _label(identity["mode"], "mode")
    _validate_model(identity["model"])
    options = identity["options"]
    _keys(
        options,
        {"temperature", "top_p", "max_output_tokens", "seed", "stop", "tools"},
        "generation options",
    )
    for key, low, high in (("temperature", 0.0, 2.0), ("top_p", 0.0, 1.0)):
        if not low <= _number(options[key], key) <= high:
            raise EvidenceError(f"{key} is outside its allowed range")
    _int(options["max_output_tokens"], 16, 512, "max_output_tokens")
    if options["seed"] is not None:
        _int(options["seed"], 0, 2**32 - 1, "generation seed")
    if type(options["stop"]) is not list or len(options["stop"]) > 4 or any(
        type(item) is not str or not 1 <= len(item) <= 80 for item in options["stop"]
    ):
        raise EvidenceError("invalid stop sequences")
    if type(options["tools"]) is not list or options["tools"]:
        raise EvidenceError("quality corpus requires tools to be disabled")
    return identity


def _score_artifact(score: Any) -> dict[str, Any]:
    _keys(score, _SCORE_KEYS, "quality score")
    if (
        type(score["schema_version"]) is not int
        or score["schema_version"] != 1
        or score["kind"] != "general_foundation_scores"
    ):
        raise EvidenceError("unsupported quality score schema")
    for key in ("suite_sha256", "oracle_sha256", "grader_sha256"):
        _hash(score[key], key)
    identity = _validate_identity(score["identity"])
    if score["provenance"] != "operator_declared_not_authenticated":
        raise EvidenceError("quality provenance declaration is not recognized")
    if type(score["scope"]) is not str or "development" not in score["scope"].lower():
        raise EvidenceError("quality evidence must explicitly identify a development corpus")
    repeats = _int(score["repeats"], 1, 3, "quality repeats")
    total = _int(score["total"], 1, 192, "quality total")
    if total > 64 * repeats:
        raise EvidenceError("quality total exceeds the suite bound")
    if type(score["rows"]) is not list or len(score["rows"]) != total:
        raise EvidenceError("quality rows do not cover the declared total")

    status_counts: Counter[str] = Counter()
    category_counts: dict[str, Counter[str]] = {}
    row_keys: list[tuple[str, int, str, str]] = []
    for row in score["rows"]:
        _keys(row, _ROW_KEYS, "quality row")
        task_id = _label(row["task_id"], "task_id")
        attempt = _int(row["attempt"], 1, repeats, "quality attempt")
        request_hash = _hash(row["request_sha256"], "request_sha256")
        _hash(row["response_sha256"], "response_sha256")
        category = _label(row["category"], "quality category")
        status = row["status"]
        if type(status) is not str or status not in STATUSES:
            raise EvidenceError("unknown quality status")
        if row["error_code"] is not None and (
            type(row["error_code"]) is not str or not 1 <= len(row["error_code"]) <= 64
        ):
            raise EvidenceError("invalid quality error code")
        if (status == "transport_error") != (row["error_code"] is not None):
            raise EvidenceError("quality status and error-code presence disagree")
        status_counts[status] += 1
        category_counts.setdefault(category, Counter())[status] += 1
        row_keys.append((task_id, attempt, request_hash, category))

    if len({(task, attempt) for task, attempt, _, _ in row_keys}) != total:
        raise EvidenceError("duplicate quality task attempt")
    supplied_counts = score["counts"]
    if (
        type(supplied_counts) is not dict
        or any(type(value) is not int or value < 0 for value in supplied_counts.values())
        or supplied_counts != dict(status_counts)
    ):
        raise EvidenceError("quality status totals do not match the rows")
    supplied_categories = score["category_counts"]
    normalized_categories = {
        name: dict(sorted(counts.items()))
        for name, counts in sorted(category_counts.items())
    }
    if type(supplied_categories) is not dict:
        raise EvidenceError("quality category totals do not match the rows")
    for values in supplied_categories.values():
        if (
            type(values) is not dict
            or any(type(value) is not int or value < 0 for value in values.values())
        ):
            raise EvidenceError("quality category totals contain invalid counts")
    if supplied_categories != normalized_categories:
        raise EvidenceError("quality category totals do not match the rows")
    return {
        "score": score,
        "identity": identity,
        "rows": row_keys,
        "category_counts": category_counts,
        "status_counts": status_counts,
    }


def _quality_comparison(report: Any, baseline_alias: str, candidate_alias: str) -> dict[str, Any]:
    _keys(report, {"kind", "axis", "provenance", "scope", "comparison_status",
                   "baseline", "candidate", "changes"}, "quality comparison")
    if report["kind"] != "general_foundation_comparison" or report["axis"] != "model":
        raise EvidenceError("quality artifact must be a model-axis general-foundation comparison")
    if report["comparison_status"] != "artifact_consistent":
        raise EvidenceError("quality comparison contains incomplete transport evidence")
    if report["provenance"] != "operator_declared_not_authenticated":
        raise EvidenceError("quality comparison provenance is not recognized")
    if type(report["scope"]) is not str or "development" not in report["scope"].lower():
        raise EvidenceError("quality comparison must be development-only")

    baseline = _score_artifact(report["baseline"])
    candidate = _score_artifact(report["candidate"])
    before, after = baseline["score"], candidate["score"]
    if report["scope"] != before["scope"]:
        raise EvidenceError("comparison scope differs from the scored suite")
    for key in ("suite_sha256", "oracle_sha256", "grader_sha256", "scope", "repeats", "total"):
        if before[key] != after[key]:
            raise EvidenceError(f"baseline/candidate quality {key} differs")
    left_identity = dict(baseline["identity"])
    right_identity = dict(candidate["identity"])
    left_model = left_identity.pop("model")
    right_model = right_identity.pop("model")
    if left_identity != right_identity:
        raise EvidenceError(
            "quality runs do not share the same application/backend/options identity"
        )
    if left_model["model_id"] != baseline_alias or right_model["model_id"] != candidate_alias:
        raise EvidenceError("quality model identities do not match paired latency aliases")
    artifact_identity = ("weights_sha256", "tokenizer_sha256", "quantization")
    if all(left_model[key] == right_model[key] for key in artifact_identity):
        raise EvidenceError("baseline and candidate model artifacts are identical")

    if len(baseline["rows"]) != len(candidate["rows"]):
        raise EvidenceError("quality comparison row counts differ")
    for left, right in zip(baseline["rows"], candidate["rows"]):
        if left != right:
            raise EvidenceError(
                "quality comparisons must use identical task/attempt/request/category rows"
            )

    expected_changes = []
    for row_left, row_right in zip(before["rows"], after["rows"]):
        if row_left["status"] != row_right["status"]:
            expected_changes.append({
                "task_id": row_left["task_id"],
                "category": row_left["category"],
                "attempt": row_left["attempt"],
                "baseline": row_left["status"],
                "candidate": row_right["status"],
            })
    if type(report["changes"]) is not list or report["changes"] != expected_changes:
        raise EvidenceError("quality change list does not match scored rows")

    return {"baseline": baseline, "candidate": candidate}


def _validate_summary(summary: Any, *, expected_samples: int, label: str) -> dict[str, Any]:
    _keys(summary, _COMPARISON_KEYS, label)
    samples = _int(summary["paired_samples"], 0, 64, f"{label} paired_samples")
    incomplete = _int(summary["incomplete_pairs"], 0, 64, f"{label} incomplete_pairs")
    if samples + incomplete != expected_samples:
        raise EvidenceError(f"{label} sample counts do not match the preregistered schedule")
    faster = _int(summary["candidate_faster_pairs"], 0, 64, f"{label} faster")
    tied = _int(summary["candidate_tied_pairs"], 0, 64, f"{label} tied")
    slower = _int(summary["candidate_slower_pairs"], 0, 64, f"{label} slower")
    if faster + tied + slower != samples:
        raise EvidenceError(f"{label} faster/tied/slower counts do not sum to samples")
    _number(summary["tie_threshold_ms"], f"{label} tie threshold", positive=True)
    if samples == 0:
        nullable = (
            "baseline_first_content_p50_ms",
            "candidate_first_content_p50_ms",
            "first_content_delta_p50_ms",
            "first_content_delta_p95_ms",
            "baseline_end_to_end_p50_ms",
            "candidate_end_to_end_p50_ms",
            "end_to_end_delta_p50_ms",
        )
        if incomplete != expected_samples or any(summary[key] is not None for key in nullable):
            raise EvidenceError(f"{label} empty summary is inconsistent")
        return summary
    for key in (
        "baseline_first_content_p50_ms", "candidate_first_content_p50_ms",
        "baseline_end_to_end_p50_ms", "candidate_end_to_end_p50_ms",
    ):
        _number(summary[key], f"{label} {key}", positive=True)
    first_delta = _number(
        summary["first_content_delta_p50_ms"], f"{label} first-content delta"
    )
    first_p95 = _number(
        summary["first_content_delta_p95_ms"], f"{label} first-content p95 delta"
    )
    _number(summary["end_to_end_delta_p50_ms"], f"{label} end-to-end delta")
    if first_p95 < first_delta:
        raise EvidenceError(f"{label} p95 delta is below its median delta")
    return summary


def _paired_report(report: Any) -> tuple[str, list[str], dict[str, Any]]:
    _keys(report, _PAIRED_KEYS, "paired inference report")
    if (
        type(report["schema_version"]) is not int
        or report["schema_version"] != 1
        or report["verdict"] not in {"paired_observations", "no_complete_pairs"}
    ):
        raise EvidenceError("unsupported paired inference report")
    if type(report["note"]) is not str or len(report["note"]) > 4000:
        raise EvidenceError("paired report note is invalid")
    models = report["models"]
    if type(models) is not list or len(models) != 2:
        raise EvidenceError("quality/speed gate requires exactly one baseline and one candidate")
    for model in models:
        _label(model, "paired model alias")
    if len(set(models)) != len(models) or report["baseline_model"] != models[0]:
        raise EvidenceError("paired model order or baseline identity is invalid")
    _int(report["seed"], 0, 2**32 - 1, "paired seed")
    pair_count = _int(report["pair_count"], 1, 64, "pair_count")
    total_requests = _int(report["total_requests"], 1, 192, "total_requests")
    successful = _int(report["successful_requests"], 0, 192, "successful_requests")
    failed = _int(report["failed_requests"], 0, 192, "failed_requests")
    if successful + failed != total_requests or total_requests != pair_count * len(models):
        raise EvidenceError("paired request totals do not match the schedule")
    _number(report["wall_ms"], "paired wall_ms", positive=True)
    _number(report["warmup_ms"], "paired warmup_ms")
    if (
        type(report["warmup_by_model_ms"]) is not dict
        or set(report["warmup_by_model_ms"]) != set(models)
    ):
        raise EvidenceError("warm-up timings do not cover every model")
    for value in report["warmup_by_model_ms"].values():
        _number(value, "warmup model timing")

    schedule = report["pair_schedule"]
    if type(schedule) is not list or len(schedule) != pair_count:
        raise EvidenceError("pair schedule length differs from pair_count")
    category_totals: Counter[str] = Counter()
    order_counts: Counter[tuple[str, ...]] = Counter()
    for index, item in enumerate(schedule):
        _keys(item, {"pair_id", "category", "model_order"}, "pair schedule row")
        if item["pair_id"] != index or type(item["pair_id"]) is not int:
            raise EvidenceError("pair IDs must be contiguous and ordered")
        category = item["category"]
        if type(category) is not str or category not in WORKLOADS:
            raise EvidenceError("unknown paired workload category")
        order = item["model_order"]
        if type(order) is not list or len(order) != len(models) or set(order) != set(models):
            raise EvidenceError("pair order must contain every model exactly once")
        order_counts[tuple(order)] += 1
        category_totals[category] += 1
    if len(order_counts) != 2:
        raise EvidenceError("paired schedule must contain both model-order permutations")
    candidates = report["by_candidate"]
    if type(candidates) is not dict or set(candidates) != set(models[1:]):
        raise EvidenceError("candidate summaries do not match the model list")
    return models[0], models[1:], {
        "verdict": report["verdict"],
        "pair_count": pair_count,
        "total_requests": total_requests,
        "successful": successful,
        "failed": failed,
        "category_totals": category_totals,
        "candidates": candidates,
    }


def _server_metrics(report: Any, alias: str, label: str) -> dict[str, float]:
    _keys(report, _METRIC_KEYS, label)
    if (
        type(report["schema_version"]) is not int
        or report["schema_version"] != 1
        or report["available"] is not True
    ):
        raise EvidenceError(f"{label} is unavailable")
    if report["scope"] != "model_query" or report["model_query"] != alias:
        raise EvidenceError(f"{label} is not scoped to the expected router model")
    _number(report["duration_seconds"], f"{label} duration", positive=True)
    if type(report["counter_resets"]) is not list or report["counter_resets"]:
        raise EvidenceError(f"{label} contains counter resets")
    if type(report["missing_counters"]) is not list:
        raise EvidenceError(f"{label} missing_counters is invalid")
    prompt = _number(
        report["prompt_tokens_per_second_from_counters"],
        f"{label} prompt rate",
        positive=True,
    )
    generation = _number(
        report["generated_tokens_per_second_from_counters"],
        f"{label} generation rate",
        positive=True,
    )
    deltas = report["counter_deltas"]
    if type(deltas) is not dict:
        raise EvidenceError(f"{label} counter deltas are invalid")
    required_counters = (
        "llamacpp:prompt_tokens_total",
        "llamacpp:prompt_seconds_total",
        "llamacpp:tokens_predicted_total",
        "llamacpp:tokens_predicted_seconds_total",
    )
    for name in required_counters:
        if name in report["missing_counters"]:
            raise EvidenceError(f"{label} is missing a required throughput counter")
        _number(deltas.get(name), f"{label} {name} delta", positive=True)
    return {"prompt_tokens_per_second": prompt, "generated_tokens_per_second": generation}


def evaluate_gate(
    paired: dict[str, Any],
    quality: dict[str, Any],
    *,
    baseline_server_metrics: dict[str, Any] | None = None,
    candidate_server_metrics: dict[str, Any] | None = None,
    paired_sha256: str | None = None,
    quality_sha256: str | None = None,
) -> dict[str, Any]:
    baseline_alias, candidate_aliases, paired_meta = _paired_report(paired)
    quality_meta = _quality_comparison(quality, baseline_alias, candidate_aliases[0])
    candidate_alias = candidate_aliases[0]
    overall = paired_meta["candidates"][candidate_alias]
    _keys(overall, {"overall", "by_category"}, "candidate paired summary")
    pair_count = paired_meta["pair_count"]
    overall_summary = _validate_summary(
        overall["overall"], expected_samples=pair_count, label="overall"
    )
    expected_verdict = (
        "paired_observations"
        if overall_summary["paired_samples"] > 0
        else "no_complete_pairs"
    )
    if paired_meta["verdict"] != expected_verdict:
        raise EvidenceError("paired verdict does not match complete-pair coverage")
    by_category = overall["by_category"]
    if type(by_category) is not dict or set(by_category) != set(paired_meta["category_totals"]):
        raise EvidenceError("per-workload summaries do not cover the preregistered workload set")
    category_summaries: dict[str, dict[str, Any]] = {}
    category_summaries_total = 0
    for category, count in paired_meta["category_totals"].items():
        row = by_category[category]
        _validate_summary(row, expected_samples=count, label=category)
        category_summaries[category] = row
        category_summaries_total += row["paired_samples"] + row["incomplete_pairs"]
    if category_summaries_total != pair_count:
        raise EvidenceError("per-workload sample totals do not sum to the overall schedule")

    reasons: list[str] = []
    if paired_meta["failed"] or overall_summary["incomplete_pairs"]:
        reasons.append("incomplete_paired_requests")
    if overall_summary["paired_samples"] < MIN_PAIRED_SAMPLES:
        reasons.append("insufficient_paired_samples")
    if any(
        paired_meta["category_totals"].get(name, 0) < MIN_PAIRS_PER_WORKLOAD
        for name in WORKLOADS
    ):
        reasons.append("insufficient_per_workload_coverage")
    if len(quality_meta["baseline"]["category_counts"]) < 8:
        reasons.append("insufficient_quality_domain_coverage")
    if quality_meta["baseline"]["score"]["total"] < 24:
        reasons.append("insufficient_quality_task_count")
    if (
        quality_meta["baseline"]["status_counts"].get("transport_error", 0)
        or quality_meta["candidate"]["status_counts"].get("transport_error", 0)
    ):
        reasons.append("quality_transport_errors")

    speed_failures: list[str] = []
    if overall_summary["paired_samples"] > 0:
        baseline_first = overall_summary["baseline_first_content_p50_ms"]
        first_delta = overall_summary["first_content_delta_p50_ms"]
        required_gain = max(5.0, baseline_first * 0.05)
        if first_delta > -required_gain:
            speed_failures.append("first_content_gain_below_5_percent_or_5ms")
        p95_allowance = max(5.0, baseline_first * 0.02)
        if overall_summary["first_content_delta_p95_ms"] > p95_allowance:
            speed_failures.append("first_content_p95_regression")
        end_allowance = max(10.0, overall_summary["baseline_end_to_end_p50_ms"] * 0.02)
        if overall_summary["end_to_end_delta_p50_ms"] > end_allowance:
            speed_failures.append("end_to_end_latency_regression")
        if (
            overall_summary["candidate_faster_pairs"]
            <= overall_summary["candidate_slower_pairs"]
        ):
            speed_failures.append("candidate_not_faster_in_more_pairs")
        for category, summary in category_summaries.items():
            if summary["paired_samples"] == 0:
                continue
            allowance = max(10.0, summary["baseline_first_content_p50_ms"] * 0.10)
            if summary["first_content_delta_p50_ms"] > allowance:
                speed_failures.append(f"{category}_latency_regression")
    reasons.extend(speed_failures)

    quality_failures: list[str] = []
    before = quality_meta["baseline"]
    after = quality_meta["candidate"]
    before_pass = before["status_counts"].get("pass", 0)
    after_pass = after["status_counts"].get("pass", 0)
    if after_pass < before_pass:
        quality_failures.append("overall_general_knowledge_regression")
    for category, counts in before["category_counts"].items():
        if after["category_counts"].get(category, Counter()).get("pass", 0) < counts.get("pass", 0):
            quality_failures.append(f"{category}_quality_regression")
    reasons.extend(quality_failures)

    metrics_summary = None
    if (baseline_server_metrics is None) != (candidate_server_metrics is None):
        raise EvidenceError("provide both baseline and candidate server metrics, or neither")
    if baseline_server_metrics is not None and candidate_server_metrics is not None:
        base_metrics = _server_metrics(
            baseline_server_metrics, baseline_alias, "baseline server metrics"
        )
        candidate_metrics = _server_metrics(
            candidate_server_metrics, candidate_alias, "candidate server metrics"
        )
        metrics_summary = {
            "baseline": base_metrics,
            "candidate": candidate_metrics,
            "candidate_to_baseline_prompt_rate_ratio": round(
                candidate_metrics["prompt_tokens_per_second"]
                / base_metrics["prompt_tokens_per_second"],
                4,
            ),
            "candidate_to_baseline_generation_rate_ratio": round(
                candidate_metrics["generated_tokens_per_second"]
                / base_metrics["generated_tokens_per_second"],
                4,
            ),
            "interpretation": (
                "aggregate corroboration only; these counters are not per-request attribution"
            ),
        }

    if reasons:
        if any(reason in reasons for reason in (
            "insufficient_paired_samples", "insufficient_per_workload_coverage",
            "insufficient_quality_domain_coverage", "insufficient_quality_task_count",
            "incomplete_paired_requests", "quality_transport_errors",
        )):
            decision = "inconclusive"
        else:
            decision = "keep_baseline"
    else:
        decision = "manual_review_recommended"

    result = {
        "schema_version": 1,
        "kind": "star_model_quality_speed_gate",
        "decision": decision,
        "baseline_model": baseline_alias,
        "candidate_model": candidate_alias,
        "paired_samples": overall_summary["paired_samples"],
        "workload_categories": sorted(paired_meta["category_totals"]),
        "quality_domains": sorted(before["category_counts"]),
        "quality_tasks": before["score"]["total"],
        "quality_repeats": before["score"]["repeats"],
        "baseline_general_knowledge_passes": before_pass,
        "candidate_general_knowledge_passes": after_pass,
        "baseline_general_knowledge_pass_rate": round(before_pass / before["score"]["total"], 4),
        "candidate_general_knowledge_pass_rate": round(after_pass / after["score"]["total"], 4),
        "first_content_delta_p50_ms": overall_summary["first_content_delta_p50_ms"],
        "first_content_delta_p95_ms": overall_summary["first_content_delta_p95_ms"],
        "end_to_end_delta_p50_ms": overall_summary["end_to_end_delta_p50_ms"],
        "candidate_faster_pairs": overall_summary["candidate_faster_pairs"],
        "candidate_tied_pairs": overall_summary["candidate_tied_pairs"],
        "candidate_slower_pairs": overall_summary["candidate_slower_pairs"],
        "reasons": reasons,
        "server_metrics": metrics_summary,
        "evidence_sha256": {
            "paired": paired_sha256,
            "quality": quality_sha256,
        },
        "evidence_scope": "development_only_not_holdout",
        "automatic_route_change_authorized": False,
        "live_vtuber_rollout_authorized": False,
        "holdout_evaluation_required": True,
        "private_windows_game_obs_audio_avatar_rehearsal_required": True,
        "note": (
            "A passing result recommends human review only. It does not promote a model, "
            "alter STAR's router, prove foundation-model intelligence, establish real-game "
            "mastery, or authorize a livestream. The development knowledge corpus is not a "
            "sealed holdout. Re-run on unseen knowledge, coding, game, voice and tool-use "
            "tasks, then perform a private Windows rehearsal."
        ),
    }
    for key in ("paired", "quality"):
        digest = result["evidence_sha256"][key]
        if digest is not None:
            _hash(digest, f"{key} evidence digest")
    return result


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paired", type=Path, required=True, help="Paired inference JSON report")
    parser.add_argument(
        "--quality",
        type=Path,
        required=True,
        help="General-foundation comparison JSON report",
    )
    parser.add_argument("--baseline-server-metrics", type=Path)
    parser.add_argument("--candidate-server-metrics", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New report path; existing files are never overwritten",
    )
    args = parser.parse_args(arguments)
    try:
        paired, paired_digest = load_artifact(args.paired)
        quality, quality_digest = load_artifact(args.quality)
        baseline_metrics = candidate_metrics = None
        if args.baseline_server_metrics is not None or args.candidate_server_metrics is not None:
            if args.baseline_server_metrics is None or args.candidate_server_metrics is None:
                raise EvidenceError("both server-metrics paths are required together")
            baseline_metrics, _ = load_artifact(args.baseline_server_metrics)
            candidate_metrics, _ = load_artifact(args.candidate_server_metrics)
        result = evaluate_gate(
            paired, quality,
            baseline_server_metrics=baseline_metrics,
            candidate_server_metrics=candidate_metrics,
            paired_sha256=paired_digest,
            quality_sha256=quality_digest,
        )
        encoded = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
    except (OSError, EvidenceError, ValueError, TypeError, RecursionError):
        print("Evidence rejected or output already exists; no model route was changed.")
        return 2
    print(f"{result['decision']}: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
