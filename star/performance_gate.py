"""Compare recorded STAR brain benchmarks without inventing speed or quality gains.

Offline-only: no model calls, machine changes or agent permissions. This is a
candidate regression screen, NOT the independent answer-quality/release gate.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

MAX_REPORT_BYTES = 256_000
_METRICS = ("p95_ttft_ms", "p95_total_ms", "requests_per_second")


def _number(value: object, *, positive: bool = True) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("Invalid or non-finite benchmark measurement")
    number = float(value)
    if not math.isfinite(number) or (number <= 0 if positive else number < 0):
        raise ValueError("Invalid or non-finite benchmark measurement")
    return number


def _p95(values: list[float]) -> float:
    return round(sorted(values)[math.ceil(.95 * len(values)) - 1], 1)


def validate_report(value: object) -> dict:
    """Validate a measured STAR brain benchmark JSON report and its summary."""
    if not isinstance(value, dict):
        raise ValueError("Benchmark report must be a JSON object")
    for key in ("model", "scenario", "target", "endpoint"):
        if not isinstance(value.get(key), str) or not 1 <= len(value[key]) <= 256:
            raise ValueError(f"Missing benchmark identity: {key}")
    if value["scenario"] not in {"chat", "coding", "roblox"} or value["target"] not in {"local", "star_server"}:
        raise ValueError("Unsupported benchmark scenario or target")
    samples, summary = value.get("measurements"), value.get("summary")
    if not isinstance(samples, list) or not 3 <= len(samples) <= 10 or not isinstance(summary, dict):
        raise ValueError("Benchmark requires 3 to 10 measured requests and a summary")
    if type(summary.get("runs")) is not int or summary["runs"] != len(samples):
        raise ValueError("Benchmark sample count disagrees with summary")
    parallel = summary.get("parallel")
    if type(parallel) is not int or not 1 <= parallel <= min(4, len(samples)):
        raise ValueError("Missing or invalid actual benchmark parallelism")
    wall_ms = _number(summary.get("wall_ms"))
    by_key = {k: [] for k in ("ttft_ms", "total_ms")}
    for row in samples:
        if not isinstance(row, dict):
            raise ValueError("Invalid benchmark measurement row")
        ttft, total = _number(row.get("ttft_ms")), _number(row.get("total_ms"))
        if total + 0.15 < ttft:
            raise ValueError("Benchmark total time cannot be below first-token time")
        by_key["ttft_ms"].append(ttft)
        by_key["total_ms"].append(total)
    observed = {
        "p95_ttft_ms": _p95(by_key["ttft_ms"]),
        "p95_total_ms": _p95(by_key["total_ms"]),
        "requests_per_second": round(len(samples) * 1000 / wall_ms, 3),
    }
    for key in _METRICS:
        reported = _number(summary.get(key))
        tolerance = .11 if key != "requests_per_second" else .002
        if abs(reported - observed[key]) > tolerance:
            raise ValueError(f"Benchmark {key} does not match recorded measurements")
    return value


def compare_reports(baseline: object, candidate: object, *, regression_pct: float = 10.0) -> dict:
    """Positive change is better. No result implies correctness or reproducibility."""
    if type(regression_pct) not in (int, float) or not math.isfinite(regression_pct) or not 0 <= regression_pct <= 50:
        raise ValueError("Regression threshold must be between 0 and 50 percent")
    old = validate_report(baseline)
    new = validate_report(candidate)
    for key in ("model", "scenario", "target", "endpoint"):
        if old[key] != new[key]:
            raise ValueError(f"Cannot compare changed benchmark identity: {key}")
    if old["summary"]["parallel"] != new["summary"]["parallel"]:
        raise ValueError("Cannot compare different concurrency settings as an A/B performance gate")
    delta = {}
    for key in _METRICS:
        before = float(old["summary"][key])
        after = float(new["summary"][key])
        delta[key] = round(100 * ((after / before - 1) if key == "requests_per_second" else (1 - after / before)), 2)
    # P95 from fewer than 10 samples is effectively a worst-case observation,
    # not strong enough to promote a tuning result. Make that explicit.
    enough = len(old["measurements"]) >= 10 and len(new["measurements"]) >= 10
    regression = any(v < -regression_pct for v in delta.values())
    if not enough:
        status = "insufficient_samples"
    elif regression:
        status = "candidate_regression"
    elif delta["p95_ttft_ms"] >= 5 and delta["requests_per_second"] >= -5 and delta["p95_total_ms"] >= -5:
        status = "candidate_improvement"
    else:
        status = "no_clear_improvement"
    return {
        "status": status,
        "changes_pct_positive_is_better": delta,
        "baseline_samples": len(old["measurements"]),
        "candidate_samples": len(new["measurements"]),
        "parallel": old["summary"]["parallel"],
        "regression_threshold_pct": regression_pct,
        "quality_verified": False,
        "release_ready": False,
        "note": "Candidate speed evidence only. Match hardware, model binary/quantization, prompts, workload and cache state; run independent task-quality and safety gates before changing any routing.",
    }


def _load(path: Path) -> object:
    if path.stat().st_size > MAX_REPORT_BYTES:
        raise ValueError("Benchmark report exceeds size limit")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare two local STAR brain benchmark JSON files")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--regression-pct", type=float, default=10.0)
    args = parser.parse_args(argv)
    try:
        result = compare_reports(_load(args.baseline), _load(args.candidate), regression_pct=args.regression_pct)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["status"] == "candidate_regression" else 2 if result["status"] == "insufficient_samples" else 0


if __name__ == "__main__":
    raise SystemExit(main())
