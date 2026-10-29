"""Agreement tables from results/calls.jsonl.  usage: score.py [split] [--by-domain]"""
import json, math, sys
from collections import defaultdict
from pathlib import Path

import os
HERE = Path(os.environ.get("VC_WORK", Path(__file__).parent))
pairs = {p["id"]: p for p in json.loads((HERE / "bench/pairs.json").read_text(encoding="utf-8"))}
split = sys.argv[1] if len(sys.argv) > 1 else "test"
by_dom = "--by-domain" in sys.argv
calls = defaultdict(dict)
for line in (HERE / "results/calls.jsonl").read_text(encoding="utf-8").splitlines():
    d = json.loads(line); calls[(d["model"], d["variant"])].setdefault(d["pair"], {})[d["order"]] = d


def wilson(k, n, z=1.96):
    if not n:
        return (0, 0)
    p = k / n; den = 1 + z * z / n; c = (p + z * z / (2 * n)) / den; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (c - h, c + h)


def dom_of(p):
    return p["domain"].split(":")[0] if not by_dom else p["domain"]


rows = []
for (model, var), per in sorted(calls.items()):
    stats = defaultdict(lambda: defaultdict(list))
    for pid, o in per.items():
        p = pairs[pid]
        if not p["clear"] or (split != "all" and p["split"] != split):
            continue
        truth = p["pref"]
        groups = ["ALL", p["domain"]]
        if var == "abs":
            if "A" not in o or "B" not in o:
                continue
            d = o["A"]["score"] - o["B"]["score"]
            pick = None if abs(d) < 1e-9 else ("A" if d > 0 else "B")
            for g in groups:
                stats["abs"][g].append((pick == truth, True, o["A"]["sec"] + o["B"]["sec"]))
            continue
        if 0 in o:
            pick = "A" if o[0]["p_a"] > 0.5 else "B"
            for g in groups:
                stats["first"][g].append((pick == truth, True, o[0]["sec"]))
                stats["_firstpos"][g].append((o[0]["p_a"] > 0.5, True, 0))
        if 0 in o and 1 in o:
            pa = (o[0]["p_a"] + o[1]["p_a"]) / 2
            cons = (o[0]["p_a"] - 0.5) * (o[1]["p_a"] - 0.5) > 0
            pick = "A" if pa > 0.5 else "B"
            for g in groups:
                stats["swap"][g].append((pick == truth, cons, o[0]["sec"] + o[1]["sec"]))
                if cons:
                    stats["swap-consistent"][g].append((pick == truth, True, 0))
    for design, gs in stats.items():
        if design.startswith("_"):
            continue
        for g, v in gs.items():
            k = sum(x[0] for x in v); n = len(v)
            lo, hi = wilson(k, n)
            n_all = len(stats["swap"][g]) if design == "swap-consistent" else n
            rows.append((model, var, design, g, k, n, lo, hi, sum(x[1] for x in v) / n if design == "swap" else None,
                         sum(x[2] for x in v) / n, n_all))

print(f"split={split}, clear pairs only")
print(f"{'model':14s} {'variant':15s} {'design':16s} {'group':18s} agree      95% CI       consist  sec/pair")
for m, var, des, g, k, n, lo, hi, cons, sec, nall in rows:
    if g != "ALL" and not by_dom and "--domains" not in sys.argv:
        continue
    cov = f" cov {n}/{nall}" if des == "swap-consistent" else ""
    print(f"{m:14s} {var:15s} {des:16s} {g:18s} {k:3d}/{n:<3d} {k/n:5.0%}  [{lo:.0%}-{hi:.0%}]  "
          f"{'' if cons is None else f'{cons:5.0%}':7s}  {sec:6.1f}{cov}")
if "--domains" in sys.argv or by_dom:
    pass
