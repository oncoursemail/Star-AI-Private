"""Offline synthetic performance fixtures; not measurements of real STAR hardware."""
from __future__ import annotations

import copy
import json

import pytest

from star.performance_gate import compare_reports, main, validate_report


def report(ttft: float = 100, total: float = 500, wall_ms: int = 5000, *, runs: int = 10, parallel: int = 1) -> dict:
    return {
        "model": "star-fast", "scenario": "chat", "target": "local", "endpoint": "http://127.0.0.1:8080/v1",
        "measurements": [{"ttft_ms": ttft, "total_ms": total} for _ in range(runs)],
        "summary": {"runs": runs, "parallel": parallel, "wall_ms": wall_ms,
                    "p95_ttft_ms": ttft, "p95_total_ms": total,
                    "requests_per_second": round(runs * 1000 / wall_ms, 3)},
    }


def test_comparison_flags_candidate_speedup_but_does_not_promote_it():
    old, new = report(), report(ttft=70, total=460, wall_ms=4000)
    result = compare_reports(old, new)
    assert result["status"] == "candidate_improvement"
    assert result["changes_pct_positive_is_better"]["p95_ttft_ms"] == 30.0
    assert result["quality_verified"] is False
    assert result["release_ready"] is False


def test_comparison_flags_regression_and_unchanged():
    assert compare_reports(report(), report(ttft=120))["status"] == "candidate_regression"
    assert compare_reports(report(), report())["status"] == "no_clear_improvement"
    assert compare_reports(report(runs=3), report(runs=3))["status"] == "insufficient_samples"


def test_reject_modified_or_incompatible_measurements():
    good = report()
    changed = copy.deepcopy(good)
    changed["summary"]["p95_ttft_ms"] = 42
    with pytest.raises(ValueError, match="does not match"):
        validate_report(changed)
    changed = copy.deepcopy(good)
    changed["measurements"][0]["ttft_ms"] = float("inf")
    with pytest.raises(ValueError, match="non-finite"):
        validate_report(changed)
    changed = copy.deepcopy(good)
    changed["endpoint"] = "http://localhost:9999/v1"
    with pytest.raises(ValueError, match="identity"):
        compare_reports(good, changed)
    changed = report(parallel=2)
    with pytest.raises(ValueError, match="concurrency"):
        compare_reports(good, changed)
    with pytest.raises(ValueError, match="threshold"):
        compare_reports(good, good, regression_pct=-1)


def test_cli_uses_local_report_files_and_exits_nonzero_for_regression(tmp_path, capsys):
    a, b = tmp_path / "before.json", tmp_path / "after.json"
    a.write_text(json.dumps(report()), encoding="utf-8")
    b.write_text(json.dumps(report(ttft=120)), encoding="utf-8")
    assert main([str(a), str(b)]) == 1
    assert "candidate_regression" in capsys.readouterr().out
