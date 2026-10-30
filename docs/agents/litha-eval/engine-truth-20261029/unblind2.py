import json, sys
from collections import defaultdict
key = json.load(open("judge/key.json", encoding="utf-8"))
tasks = {t["id"]: t for t in json.load(open("tasks_all.json", encoding="utf-8"))}
V = [json.load(open(f"judge/verdicts_{x}.json", encoding="utf-8")) for x in "ABC"]
miss = [(i, l) for i, v in enumerate(V) for l in key if l not in v]
print("labels", len(key), "missing", len(miss))
def maj(label):
    p = [v[label]["pass"] for v in V if label in v]
    return sum(p) >= 2, sum(p)
def mean_score(label):
    s = [v[label]["score"] for v in V if label in v]
    return sum(s) / len(s)
arm = defaultdict(dict)
for label, arms in key.items():
    tid = label.split("#")[0]
    for a in arms:
        arm[a][tid] = (maj(label)[0], mean_score(label), [v[label]["pass"] for v in V])
ARMS = ["B", "BV", "F", "FV"]
agree = sum(1 for l in key if len({v[l]["pass"] for v in V}) == 1)
print(f"judges agree on pass/fail for {agree}/{len(key)} labels")
print("| arm | pass (majority of 3) | judge A | judge B | judge C | mean score |")
print("|---|---|---|---|---|---|")
for a in ARMS:
    d = arm[a]
    per = [sum(x[2][k] for x in d.values()) for k in range(3)]
    print(f"| {a} | {sum(x[0] for x in d.values())}/{len(d)} | {per[0]} | {per[1]} | {per[2]} | {sum(x[1] for x in d.values())/len(d):.2f} |")
fams = ["unity", "godot", "unreal", "love", "lua"]
print("| family | n | " + " | ".join(ARMS) + " |")
print("|---|---|" + "---|" * len(ARMS))
for f in fams:
    ids = [t for t in tasks if tasks[t]["family"] == f]
    print(f"| {f} | {len(ids)} | " + " | ".join(str(sum(arm[a][t][0] for t in ids)) for a in ARMS) + " |")
from math import comb
def sign(a, b):
    up = [t for t in arm[a] if not arm[a][t][0] and arm[b][t][0]]
    dn = [t for t in arm[a] if arm[a][t][0] and not arm[b][t][0]]
    n = len(up) + len(dn)
    p = 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, k) for k in range(0, min(len(up), len(dn)) + 1)) / 2 ** n)
    return len(up), len(dn), p, up, dn
for a, b in (("B", "BV"), ("B", "F"), ("B", "FV"), ("F", "FV"), ("BV", "FV")):
    u, d, p, up, dn = sign(a, b)
    print(f"{a} -> {b}: +{u}/-{d} sign-test p={p:.3f}  up={up}  down={dn}")
json.dump({a: {t: x[0] for t, x in d.items()} for a, d in arm.items()}, open("judged.json", "w"))
