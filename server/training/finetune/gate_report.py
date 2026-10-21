"""Paired verdict of a candidate arm against a control arm over several suites (gate_run.py result files).

    python gate_report.py --control work/ft20/gate/bank-v2.json work/ft20/gate/bank-creation.json \
        --candidate work/ft20/gate/sft-v2.json work/ft20/gate/sft-creation.json

Per suite: star.eval_gate.compare_paired (the app's gate, model change allowed). Combined: star.eval_stats.paired_decision
over the union of tasks (ids prefixed by suite file). PROMOTE only on a significant improvement; anything below the
minimum detectable effect is INCONCLUSIVE. Also prints pass counts and median seconds per answer.

--product-errors REGEX (default: CompactionLimitError): an "error" whose text matches is the model's own failure
inside STAR (e.g. the 4B's history summary ran past its token limit, so STAR gave no answer) and is counted as a
fail, like eval_runner's product_failure rows; other errors (server down) still make the verdict INCOMPLETE.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAMPLE = {"pass": True, "fail": False}


def seconds(result: dict) -> float | None:
    values = [row.get("seconds") for row in result["tasks"].values()
              if isinstance(row, dict) and isinstance(row.get("seconds"), (int, float))]
    return round(statistics.median(values), 1) if values else None


def product_errors_as_fail(result: dict, pattern: str) -> int:
    """Turn matching error rows into fail rows (in place); returns how many."""
    changed = 0
    for row in result["tasks"].values():
        if isinstance(row, dict) and row.get("status") == "error" and pattern and re.search(pattern, row.get("error", "")):
            row.update(status="fail", passed=False, reasons=["STAR gave no answer: " + row.get("error", "")[:200]],
                       checks=[], product_failure=row.get("error", "")[:200])
            changed += 1
    return changed


def report(control_files: list[Path], candidate_files: list[Path], alpha: float = 0.05,
           product_errors: str = "CompactionLimitError") -> dict:
    from star import eval_gate, eval_stats
    if len(control_files) != len(candidate_files):
        raise SystemExit("give one control and one candidate file per suite, in the same order")
    out = {"suites": [], "alpha": alpha}
    base_all: dict[str, list] = {}
    cand_all: dict[str, list] = {}
    for c_path, k_path in zip(control_files, candidate_files):
        control, candidate = eval_gate.load_result(c_path), eval_gate.load_result(k_path)
        converted = product_errors_as_fail(control, product_errors) + product_errors_as_fail(candidate, product_errors)
        verdict = eval_gate.compare_paired([control], [candidate], alpha=alpha, allow_model_change=True)
        suite = Path(control["suite"]["file"]).stem
        out["suites"].append({"suite": suite, "verdict": verdict.to_dict(), "head": verdict.text().splitlines()[0],
                              "control_pass": verdict.baseline_pass, "candidate_pass": verdict.candidate_pass,
                              "compared": verdict.compared, "control_median_s": seconds(control),
                              "candidate_median_s": seconds(candidate), "product_errors_as_fail": converted})
        for tid, row in control["tasks"].items():
            status = row.get("status") if isinstance(row, dict) else None
            if status in SAMPLE:
                other = candidate["tasks"].get(tid, {})
                base_all[f"{suite}:{tid}"] = [SAMPLE[status]]
                cand_all[f"{suite}:{tid}"] = [SAMPLE.get(other.get("status") if isinstance(other, dict) else None)]
    combined = eval_stats.paired_decision(base_all, cand_all, alpha=alpha, method="sign")
    out["combined"] = combined.to_dict()
    out["combined_text"] = combined.text()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", type=Path, nargs="+", required=True)
    ap.add_argument("--candidate", type=Path, nargs="+", required=True)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--product-errors", default="CompactionLimitError")
    args = ap.parse_args(argv)
    result = report(args.control, args.candidate, args.alpha, args.product_errors)
    for s in result["suites"]:
        print(f"{s['suite']}: control {s['control_pass']}/{s['compared']} ({s['control_median_s']} s), candidate "
              f"{s['candidate_pass']}/{s['compared']} ({s['candidate_median_s']} s) -> {s['head']}")
    print("combined:", result["combined_text"])
    if args.json:
        args.json.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
