"""Innovation review: the eval gate's paired quality verdict plus a paired per-task time check.

Reads the result files `python -m star.evals run` already writes (one per sample, both arms in one session, as for
`gate --paired-session`). Quality is decided by star/eval_gate.compare_paired unchanged; time uses each task's
recorded `seconds` (median over the arm's samples) and the exact sign test from star/eval_stats.py.

    python -m star.evals innovation --objective speed --baseline b1.json b2.json --candidate c1.json c2.json

Recommendations (exit code): review_candidate (0), reject_regression (1), invalid_evidence (2),
needs_more_evidence (4). Even review_candidate changes nothing; it is a recommendation for the owner.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics

from . import eval_gate, eval_stats

REVIEW, REJECT, INVALID, MORE = "review_candidate", "reject_regression", "invalid_evidence", "needs_more_evidence"
EXIT = {REVIEW: 0, REJECT: 1, INVALID: 2, MORE: 4}
MAX_SLOWDOWN = 0.15       # a quality gain may cost at most 15 % more total time
MIN_SPEEDUP = 0.10        # a speed change must save at least 10 % total time


def task_seconds(runs: list[dict]) -> dict[str, float]:
    """Median recorded seconds per scored task (pass or fail) over an arm's runs; rows without time are skipped."""
    times: dict[str, list[float]] = {}
    for run in runs:
        for tid, row in run.get("tasks", {}).items():
            seconds = row.get("seconds") if isinstance(row, dict) else None
            if (row.get("status") in ("pass", "fail") and isinstance(seconds, (int, float))
                    and not isinstance(seconds, bool) and seconds > 0):
                times.setdefault(tid, []).append(float(seconds))
    return {tid: statistics.median(values) for tid, values in times.items()}


def time_report(baseline_runs: list[dict], candidate_runs: list[dict], *, alpha: float = eval_stats.DEFAULT_ALPHA) -> dict:
    base, cand = task_seconds(baseline_runs), task_seconds(candidate_runs)
    common = sorted(set(base) & set(cand))
    wins = sum(cand[t] < base[t] for t in common)
    losses = sum(cand[t] > base[t] for t in common)
    test = eval_stats.sign_test(wins, losses)
    before, after = sum(base[t] for t in common), sum(cand[t] for t in common)
    return {"tasks": len(common), "faster": wins, "slower": losses, "same": len(common) - wins - losses,
            "p_faster": round(test["p_better"], 6), "p_slower": round(test["p_worse"], 6), "alpha": alpha,
            "baseline_seconds": round(before, 1), "candidate_seconds": round(after, 1),
            "change": round(after / before - 1, 4) if before else None}


def review(baseline_runs: list[dict], candidate_runs: list[dict], *, objective: str = "quality",
           alpha: float = eval_stats.DEFAULT_ALPHA, **gate_options) -> dict:
    if objective not in ("quality", "speed"):
        raise ValueError("objective must be 'quality' or 'speed'")
    verdict = eval_gate.compare_paired(baseline_runs, candidate_runs, alpha=alpha, **gate_options)
    timing = time_report(baseline_runs, candidate_runs, alpha=alpha) if verdict.code != eval_gate.UNUSABLE else None
    if verdict.code == eval_gate.UNUSABLE:
        recommendation, reason = INVALID, "the eval gate cannot compare these runs"
    elif verdict.code == eval_gate.BLOCKED:
        recommendation, reason = REJECT, "the eval gate found a quality regression"
    elif verdict.code == eval_gate.INCOMPLETE:
        recommendation, reason = MORE, "tasks are missing or errored in the candidate runs"
    elif timing is None or timing["change"] is None:
        recommendation, reason = MORE, "no recorded task times to compare"
    elif objective == "quality":
        if timing["p_slower"] <= alpha and timing["change"] > MAX_SLOWDOWN:
            recommendation, reason = REJECT, f"tasks got significantly slower (+{timing['change']:.0%} total time)"
        elif verdict.code == eval_gate.ALLOWED:
            recommendation, reason = REVIEW, "significant quality gain without a significant slowdown over 15 %"
        else:
            recommendation, reason = MORE, "no significant quality gain"
    elif timing["p_slower"] <= alpha:
        recommendation, reason = REJECT, "tasks got significantly slower"
    elif timing["p_faster"] <= alpha and timing["change"] <= -MIN_SPEEDUP:
        recommendation, reason = REVIEW, f"significantly faster ({timing['change']:.0%} total time), no quality regression"
    else:
        recommendation, reason = MORE, "no significant speed-up of at least 10 %"
    return {"recommendation": recommendation, "reason": reason, "objective": objective,
            "quality": verdict.to_dict(), "quality_text": verdict.text(), "time": timing}


def text(report: dict) -> str:
    lines = [f"innovation review ({report['objective']}): {report['recommendation']} - {report['reason']}",
             report["quality_text"]]
    timing = report["time"]
    if timing and timing["tasks"]:
        lines.append(f"time on {timing['tasks']} tasks: {timing['baseline_seconds']} s -> {timing['candidate_seconds']} s"
                     f" ({timing['change']:+.1%}); {timing['faster']} faster, {timing['slower']} slower; sign test "
                     f"p(faster)={timing['p_faster']:.4f}, p(slower)={timing['p_slower']:.4f}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m star.evals innovation")
    parser.add_argument("--baseline", required=True, type=Path, nargs="+", help="baseline result files, one per sample")
    parser.add_argument("--candidate", required=True, type=Path, nargs="+", help="candidate result files, one per sample")
    parser.add_argument("--objective", choices=["quality", "speed"], default="quality")
    parser.add_argument("--alpha", type=float, default=eval_stats.DEFAULT_ALPHA)
    parser.add_argument("--allow-model-change", action="store_true", help="the candidate arm uses another model")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    try:
        base = [eval_gate.load_result(path) for path in args.baseline]
        cand = [eval_gate.load_result(path) for path in args.candidate]
    except (OSError, ValueError) as exc:
        print(f"innovation review: invalid_evidence - cannot read results: {exc}")
        return EXIT[INVALID]
    report = review(base, cand, objective=args.objective, alpha=args.alpha, allow_model_change=args.allow_model_change)
    print(json.dumps(report, indent=2) if args.json else text(report))
    return EXIT[report["recommendation"]]
