"""Calibration: how an L2 margin change maps to a real pass-rate change, fitted on past A/Bs, and the back-test.

Registry (JSON list, paths relative to the registry file):
    {"name": "ft20 sft vs base", "kinds": ["model"],
     "base": [result files of the baseline arm], "cand": [result files of the candidate arm],
      "probe": "probe-v1.jsonl", "base_scores": "runs/v1/q3-base.scores.jsonl",
     "cand_scores": "runs/v1/q3-sft.scores.jsonl",
     "eval_hours": 5.7, "oracle_hours": 0.2}
An entry without scores (or whose kinds include "loop"/"app") has no L0-L2 prediction: the oracle escalates it.

Model: observed delta (candidate pass rate - baseline pass rate on the tasks both arms scored) = slope * L2 delta,
through the origin (no margin change -> no expected pass change). The prediction interval is the usual OLS one with a
Student t quantile, so it widens with few A/Bs and with noisy ones; the oracle decides only when it excludes zero.

Back-test (the spec's success test): leave-one-out over the A/Bs with a prediction; an entry agrees when the oracle's
L0-L2 verdict matches the full eval's verdict, or the full eval was INCONCLUSIVE. Also reported: how often the
prediction is decided at all, and how often the predicted sign matches the observed delta.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .. import eval_stats
from . import irt, probe, score

# One-sided 95 % Student t quantiles (two-sided 90 % interval), df 1..30; larger df use the normal 1.645.
_T95 = [6.314, 2.920, 2.353, 2.132, 2.015, 1.943, 1.895, 1.860, 1.833, 1.812, 1.796, 1.782, 1.771, 1.761, 1.753,
        1.746, 1.740, 1.734, 1.729, 1.725, 1.721, 1.717, 1.714, 1.711, 1.708, 1.706, 1.703, 1.701, 1.699, 1.697]
NO_PREDICTION_KINDS = frozenset({"loop", "app"})


def t95(df: int) -> float:
    return _T95[df - 1] if 1 <= df <= len(_T95) else 1.645


def full_eval(entry: dict, base_dir: Path) -> dict:
    """Paired verdict and observed delta from the stored result files (k = 1 per file set)."""
    base = irt._arm_outcomes(entry["base"], base_dir)
    cand = irt._arm_outcomes(entry["cand"], base_dir)
    common = sorted(set(base) & set(cand))
    rep = eval_stats.paired_decision({t: [base[t]] for t in common}, {t: [cand[t]] for t in common})
    n = len(common)
    return {"tasks": n, "base_pass": rep.baseline_pass, "cand_pass": rep.candidate_pass,
            "delta": round((rep.candidate_pass - rep.baseline_pass) / n, 4) if n else 0.0,
            "wins": rep.wins, "losses": rep.losses, "decision": rep.decision}


def l2_delta(entry: dict, base_dir: Path) -> dict | None:
    if not entry.get("base_scores") or NO_PREDICTION_KINDS & set(entry.get("kinds", ())):
        return None
    pairs = probe.read(base_dir / entry["probe"])
    rows = lambda key: [json.loads(x) for x in (base_dir / entry[key]).read_text(encoding="utf-8").splitlines() if x]
    return score.l2_report(pairs, rows("base_scores"), rows("cand_scores"), kinds=entry.get("probe_kinds"))


def fit(points: list[tuple[float, float]]) -> dict | None:
    """Through-origin OLS of y on x; None with fewer than 2 points or no spread in x."""
    if len(points) < 2:
        return None
    sxx = sum(x * x for x, _ in points)
    if sxx <= 0:
        return None
    slope = sum(x * y for x, y in points) / sxx
    df = len(points) - 1
    resid = sum((y - slope * x) ** 2 for x, y in points) / df
    return {"slope": slope, "sigma": math.sqrt(resid), "sxx": sxx, "n": len(points), "df": df}


def predict(model: dict | None, x: float) -> dict:
    """Predicted pass-rate delta and its 90 % prediction interval; verdict BETTER / WORSE / ESCALATE."""
    if model is None:
        return {"delta": None, "interval": None, "verdict": "ESCALATE", "why": "no calibration yet"}
    centre = model["slope"] * x
    half = t95(model["df"]) * model["sigma"] * math.sqrt(1 + x * x / model["sxx"])
    lo, hi = centre - half, centre + half
    verdict = "BETTER" if lo > 0 else "WORSE" if hi < 0 else "ESCALATE"
    return {"delta": round(centre, 4), "interval": [round(lo, 4), round(hi, 4)], "verdict": verdict}


def _agrees(verdict: str, full: str) -> bool:
    return (full in ("INCONCLUSIVE", "UNDERPOWERED") or (verdict == "BETTER" and full == "PROMOTE")
            or (verdict == "WORSE" and full == "REJECT"))


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    rank = lambda v: {i: r for r, i in enumerate(sorted(range(len(v)), key=lambda i: v[i]))}
    rx, ry = rank(xs), rank(ys)
    n = len(xs)
    d2 = sum((rx[i] - ry[i]) ** 2 for i in range(n))
    return round(1 - 6 * d2 / (n * (n * n - 1)), 3)


def run(registry: list[dict], *, base_dir: Path) -> dict:
    rows = []
    for entry in registry:
        rows.append({"name": entry["name"], "kinds": entry.get("kinds", []), "full": full_eval(entry, base_dir),
                     "l2": l2_delta(entry, base_dir), "eval_hours": entry.get("eval_hours"),
                     "oracle_hours": entry.get("oracle_hours")})
    with_l2 = [r for r in rows if r["l2"] is not None]
    points = [(r["l2"]["delta"], r["full"]["delta"]) for r in with_l2]
    model = fit(points)
    for r in rows:
        if r["l2"] is None:
            r["loo"] = {"verdict": "ESCALATE", "why": "no L0-L2 signal for this kind of change"}
            continue
        others = [(o["l2"]["delta"], o["full"]["delta"]) for o in with_l2 if o is not r]
        r["loo"] = predict(fit(others), r["l2"]["delta"])
    decided = [r for r in rows if r["loo"]["verdict"] != "ESCALATE"]
    # Strict reading: an escalated entry has no L0-L2 verdict, so it agrees only when the full eval was inconclusive.
    agree_all = sum(_agrees(r["loo"]["verdict"], r["full"]["decision"]) for r in rows)
    sign_rows = [r for r in with_l2 if r["full"]["delta"] != 0 and r["loo"].get("delta") not in (None, 0)]
    sign_ok = sum((r["loo"]["delta"] > 0) == (r["full"]["delta"] > 0) for r in sign_rows)
    hours = [(r["oracle_hours"], r["eval_hours"]) for r in rows if r["oracle_hours"] and r["eval_hours"]]
    return {
        "model": {k: round(v, 6) if isinstance(v, float) else v for k, v in (model or {}).items()},
        "entries": rows,
        "summary": {
            "abs": len(rows), "with_l2": len(with_l2), "decided_at_l0_l2": len(decided),
            "decided_agree": sum(_agrees(r["loo"]["verdict"], r["full"]["decision"]) for r in decided),
            "agree_or_inconclusive": agree_all,
            "full_inconclusive": sum(r["full"]["decision"] in ("INCONCLUSIVE", "UNDERPOWERED") for r in rows),
            "sign_match": f"{sign_ok}/{len(sign_rows)}",
            "spearman_l2_vs_observed": _spearman([p[0] for p in points], [p[1] for p in points]),
            # Other candidate predictors, reported (not used for the verdict) so a later fit can switch on evidence.
            "spearman_pref_acc_vs_observed": _spearman(
                [r["l2"]["cand_pref_acc"] - r["l2"]["base_pref_acc"] for r in with_l2],
                [r["full"]["delta"] for r in with_l2]),
            "spearman_slop_vs_observed": _spearman(
                [r["l2"]["per_kind"].get("slop", {}).get("delta", 0.0) for r in with_l2],
                [r["full"]["delta"] for r in with_l2]),
            "time_ratio": round(sum(o for o, _ in hours) / sum(e for _, e in hours), 4) if hours else None,
        },
    }


def load(path) -> dict | None:
    """The stored calibration (data/oracle/calibration.json) or None."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data.get("model") or None


def markdown(result: dict) -> str:
    lines = ["| A/B | kinds | full eval (W/L, delta) | L2 delta [90%] | LOO prediction | verdict |",
             "|---|---|---|---|---|---|"]
    for r in result["entries"]:
        f, l2, loo = r["full"], r["l2"], r["loo"]
        l2s = f"{l2['delta']:+.3f} [{l2['delta_ci90'][0]:+.3f}, {l2['delta_ci90'][1]:+.3f}]" if l2 else "-"
        pred = (f"{loo['delta']:+.3f} [{loo['interval'][0]:+.3f}, {loo['interval'][1]:+.3f}]"
                if loo.get("interval") else loo.get("why", "-"))
        lines.append(f"| {r['name']} | {','.join(r['kinds'])} | {f['decision']} ({f['wins']}/{f['losses']}, "
                     f"{f['delta']:+.3f}) | {l2s} | {pred} | {loo['verdict']} |")
    s = result["summary"]
    lines.append(f"\n{s['abs']} A/Bs, {s['with_l2']} with an L2 score; decided at L0-L2: {s['decided_at_l0_l2']} "
                 f"({s['decided_agree']} agree); agree-or-full-inconclusive: {s['agree_or_inconclusive']}/{s['abs']} "
                 f"(full eval inconclusive in {s['full_inconclusive']}); predicted sign = observed sign: "
                 f"{s['sign_match']}; Spearman(L2, observed) = {s['spearman_l2_vs_observed']}; "
                 f"oracle/eval time = {s['time_ratio']}")
    return "\n".join(lines)
