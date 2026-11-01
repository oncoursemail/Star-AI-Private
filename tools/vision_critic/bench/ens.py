"""abs-EV vs pairwise-swap vs their average on one split.  usage: ens.py dev|test [model]"""
import json, math, os, sys
os.chdir(os.environ.get("VC_WORK", os.path.dirname(os.path.abspath(__file__))))
from collections import defaultdict
split = sys.argv[1]; model = sys.argv[2] if len(sys.argv) > 2 else "q4b-i384"
pairs = {p["id"]: p for p in json.loads(open("bench/pairs.json", encoding="utf-8").read())}
c = defaultdict(dict)
for l in open("results/calls.jsonl", encoding="utf-8"):
    d = json.loads(l)
    if d["model"] == model: c[(d["variant"], d["pair"])][d["order"]] = d
for k in (0.5, 1, 2, 4):
    res = defaultdict(lambda: [0, 0])
    for pid, p in pairs.items():
        if not p["clear"] or p["split"] != split: continue
        a = c.get(("abs", pid), {}); s = c.get(("sep_chk", pid), {})
        if len(a) < 2 or len(s) < 2: continue
        pab = 1 / (1 + math.exp(-k * (a["A"]["score"] - a["B"]["score"])))
        psw = (s[0]["p_a"] + s[1]["p_a"]) / 2
        for name, v in (("abs", pab), ("swap", psw), ("ens", (pab + psw) / 2)):
            for g in ("ALL", p["domain"]):
                res[(name, g)][0] += (("A" if v > 0.5 else "B") == p["pref"]); res[(name, g)][1] += 1
    print("k", k, {f"{n}:{g}": f"{x}/{y}" for (n, g), (x, y) in sorted(res.items()) if g == "ALL" or n == "ens"})
