"""Descriptive experiment review; never an official evaluation or deployment gate.

Use independently checked, paired runs. This tool trusts supplied verification
flags: it cannot verify answers, prove significance, or authorize deployment.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

MAX_FILE_BYTES = 8_000_000
MAX_ROWS = 10_000
META_KEYS = ("workload_id", "environment_id", "quality_gate_id", "mode")
ROOT_KEYS = {"schema_version", "variant", "rows", *META_KEYS}
ROW_KEYS = {"case_id", "trial", "elapsed_ms", "verified", "authorization_violations", "timed_out"}


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _integer(value: Any, name: str, upper: int) -> int:
    if type(value) is not int or not 0 <= value <= upper:
        raise ValueError(f"{name} must be an integer in 0..{upper}")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"{name} must be a nonempty string of at most 256 characters")
    return value


def validate(run: Any) -> dict:
    if not isinstance(run, dict) or set(run) != ROOT_KEYS:
        raise ValueError("run has missing or unexpected fields")
    if type(run["schema_version"]) is not int or run["schema_version"] != 1:
        raise ValueError("unsupported schema_version")
    for key in META_KEYS:
        _text(run[key], key)
    if run["mode"] not in ("cold", "warm"):
        raise ValueError("mode must be cold or warm")
    if run["variant"] not in ("baseline", "candidate"):
        raise ValueError("variant must be baseline or candidate")
    rows = run["rows"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError(f"rows must contain 1..{MAX_ROWS} measurements")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != ROW_KEYS:
            raise ValueError("row has missing or unexpected fields")
        case = _text(row["case_id"], "case_id")
        trial = _integer(row["trial"], "trial", 1_000_000)
        if (case, trial) in seen:
            raise ValueError("duplicate case_id/trial pair")
        seen.add((case, trial))
        elapsed = _number(row["elapsed_ms"], "elapsed_ms")
        if not 0 < elapsed <= 86_400_000:
            raise ValueError("elapsed_ms must be positive and at most one day")
        if type(row["verified"]) is not bool or type(row["timed_out"]) is not bool:
            raise ValueError("verified and timed_out must be booleans")
        violations = _integer(row["authorization_violations"], "authorization_violations", 1_000_000)
        if row["verified"] and (row["timed_out"] or violations):
            raise ValueError("a timed-out or unauthorized row cannot be verified")
    return run


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValueError("nonfinite JSON constant")


def load_run(path: Path) -> dict:
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("run file exceeds the input limit")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
        return validate(data)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("invalid JSON run") from exc


def _summary(rows: list[dict]) -> dict:
    times = sorted(float(row["elapsed_ms"]) for row in rows)
    # Nearest-rank empirical percentile; descriptive, not a confidence bound.
    return {"count": len(rows), "median_ms": statistics.median(times),
            "p95_ms": times[math.ceil(0.95 * len(times)) - 1],
            "verified_count": sum(row["verified"] for row in rows),
            "timeout_count": sum(row["timed_out"] for row in rows),
            "authorization_violations": sum(row["authorization_violations"] for row in rows)}


def compare(baseline: dict, candidate: dict, *, min_cases: int = 30,
            min_p95_improvement: float = 0.10) -> dict:
    validate(baseline)
    validate(candidate)
    _integer(min_cases, "min_cases", MAX_ROWS)
    if min_cases < 2:
        raise ValueError("min_cases must be at least two")
    threshold = _number(min_p95_improvement, "min_p95_improvement")
    if not 0 < threshold < 1:
        raise ValueError("min_p95_improvement must be between zero and one")
    if baseline["variant"] != "baseline" or candidate["variant"] != "candidate":
        raise ValueError("expected baseline then candidate")
    for key in META_KEYS:
        if baseline[key] != candidate[key]:
            raise ValueError(f"incomparable {key}")
    left = {(r["case_id"], r["trial"]): r for r in baseline["rows"]}
    right = {(r["case_id"], r["trial"]): r for r in candidate["rows"]}
    if left.keys() != right.keys():
        raise ValueError("paired case/trial coverage differs")
    a, b = _summary(baseline["rows"]), _summary(candidate["rows"])
    regressions = sorted(key for key, row in left.items() if row["verified"] and not right[key]["verified"])
    newly_timed_out = sorted(key for key, row in left.items() if not row["timed_out"] and right[key]["timed_out"])
    distinct_cases = len({key[0] for key in left})
    improvement = 1 - b["p95_ms"] / a["p95_ms"]
    reasons = []
    if a["authorization_violations"] or b["authorization_violations"]:
        reasons.append("authorization_violation_observed")
    if regressions:
        reasons.append("paired_correctness_regression")
    if newly_timed_out:
        reasons.append("new_timeout_observed")
    if reasons:
        status = "reject"
    elif distinct_cases < min_cases:
        status = "inconclusive"
        reasons.append("insufficient_distinct_cases")
    elif not b["verified_count"]:
        status = "inconclusive"
        reasons.append("no_verified_results")
    elif improvement < threshold:
        status = "inconclusive"
        reasons.append("descriptive_p95_target_not_met")
    else:
        status = "review_candidate"
        reasons.append("descriptive_thresholds_met_only")
    return {"schema_version": 1, "status": status, "reasons": reasons,
            "distinct_cases": distinct_cases, "paired_observations": len(left),
            "baseline": a, "candidate": b, "p95_fractional_improvement": improvement,
            "correctness_regressions": [list(x) for x in regressions],
            "new_timeouts": [list(x) for x in newly_timed_out],
            "deployment_authorized": False, "statistical_significance_established": False,
            "warning": "Descriptive only. Verification flags and environment identity require independent evidence; repeated trials are not independent cases."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--min-cases", type=int, default=30)
    parser.add_argument("--min-p95-improvement", type=float, default=0.10)
    args = parser.parse_args()
    try:
        report = compare(load_run(args.baseline), load_run(args.candidate),
                         min_cases=args.min_cases, min_p95_improvement=args.min_p95_improvement)
    except (OSError, ValueError) as exc:
        print(f"Invalid experiment input: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, allow_nan=False))
    # Exit zero means the report was produced, NOT promotion approval.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
