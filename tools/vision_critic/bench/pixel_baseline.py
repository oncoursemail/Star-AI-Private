"""No-model baselines: prefer the arm with more content / more detail (pixel statistics only)."""
import json, re, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # repo root
from star import vision_critic as vc  # noqa: E402

import os
B = Path(os.environ.get("VC_WORK", Path(__file__).parent)) / "bench"
pairs = [p for p in json.loads((B / "pairs.json").read_text(encoding="utf-8")) if p["clear"]]


def feats(imgs):
    f = vc.pixel_facts([B / x for x in imgs])
    c = [float(x) for x in re.findall(r"content (\d+)%", f)]; d = [float(x) for x in re.findall(r"detail ([\d.]+)", f)]
    return sum(c) / len(c), sum(d) / len(d)


res = defaultdict(lambda: defaultdict(lambda: [0, 0]))
for p in pairs:
    (ca, da), (cb, db) = feats(p["A"]), feats(p["B"])
    for name, a, b in (("content", ca, cb), ("detail", da, db), ("content*detail", ca * da, cb * db)):
        if a == b:
            continue
        pick = "A" if a > b else "B"
        for g in (f"{p['split']}:ALL", f"{p['split']}:{p['domain']}"):
            res[name][g][0] += pick == p["pref"]; res[name][g][1] += 1
for name, gs in res.items():
    print(name, {g: f"{k}/{n}" for g, (k, n) in sorted(gs.items())})
