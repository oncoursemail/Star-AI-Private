"""Per-family table of the automatic measures (hidden tests / rules + checker) and, when verdicts exist, the blind judging.
    python summ2.py B=res_B.jsonl F=res_F.jsonl [--judged]
"""
import json
import sys
from collections import defaultdict

tasks = {t["id"]: t for t in json.load(open("tasks_all.json", encoding="utf-8"))}
FAMS = ["unity", "godot", "unreal", "love", "lua"]


def auto_ok(task, d):
    """Automatic pass of one answer: hidden tests when the task has them; else the rules + a clean checker."""
    if d is None:
        return None
    clean = d["checker_errors"] == 0 and d["checker_warnings"] == 0
    if d.get("tests_ok") is not None:
        return bool(d["tests_ok"])
    if d["rules_ok"] is not None:
        return bool(d["rules_ok"]) and clean
    return clean


def load(path):
    return {json.loads(l)["id"]: json.loads(l) for l in open(path, encoding="utf-8") if l.strip()}


arms = {}
for spec in sys.argv[1:]:
    if "=" not in spec:
        continue
    name, path = spec.split("=")
    rows = load(path)
    arms[name] = rows
    arms[name + "V"] = {k: {**r, "before": r.get("after") if r.get("fixed_answer") and r.get("after") else r["before"]}
                        for k, r in rows.items()}


def table(kind):
    hdr = "| family | n | " + " | ".join(arms) + " |"
    print(hdr)
    print("|" + "---|" * (hdr.count("|") - 1))
    tot = defaultdict(int)
    for fam in FAMS:
        ids = [t for t in tasks if tasks[t]["family"] == fam and kind(tasks[t])]
        common = [i for i in ids if all(i in rows for rows in arms.values())]
        cells = []
        for a, rows in arms.items():
            ok = sum(bool(auto_ok(tasks[i], rows[i]["before"])) for i in common)
            tot[a] += ok
            cells.append(f"{ok}/{len(common)}")
        tot["n"] += len(common)
        print(f"| {fam} | {len(common)} | " + " | ".join(cells) + " |")
    print(f"| all | {tot['n']} | " + " | ".join(f"{tot[a]}/{tot['n']}" for a in arms) + " |")


print("hidden tests (io, gd_func, gd_scene, love driver):")
table(lambda t: t["kind"] in ("io", "gd_func", "gd_scene") or (t["kind"] == "love" and t.get("driver")))
print("\nrules + checker (unity/unreal/old engine tasks):")
table(lambda t: t["kind"] == "engine" or (t["kind"] == "love" and not t.get("driver")))
print("\nall tasks:")
table(lambda t: True)
for a, rows in arms.items():
    if a.endswith("V"):
        continue
    fl = sum(1 for r in rows.values() if r["before"]["flagged"])
    fx = sum(1 for r in rows.values() if r.get("fixed_answer"))
    print(f"{a}: flagged {fl}/{len(rows)}, fix changed {fx}")
