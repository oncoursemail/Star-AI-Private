"""Blind judge packets: per task the distinct answers of the arms (B = live first try, BV = B + verifier fix, F = engine facts
note, FV = F + verifier fix) under random labels, tasks shuffled, one packet file per judge-pass. Each answer carries the
objective evidence (hidden tests / rules / checker messages) but never its arm. The key is written to judge/key.json.

    python packets2.py K B=ans_B.jsonl:res_B.jsonl F=ans_F.jsonl:res_F.jsonl
"""
import json
import os
import random
import sys

rng = random.Random(20261029)
K = int(sys.argv[1])
tasks = {t["id"]: t for t in json.load(open("tasks_all.json", encoding="utf-8"))}
texts = {}                   # tid -> {text: {"arms": [...], "evidence": {...}}}


def evidence(task, d):
    ev = []
    t = (d or {}).get("tests") or {}
    if t and t.get("total"):
        ev.append(f"hidden tests: {t['passed']}/{t['total']} pass" + (f" (first failure: {t['err'][:220]})" if t.get("err") else ""))
    if d and d.get("rules_ok") is not None:
        ev.append("automatic rules (obsolete/invented API patterns the task forbids, required ones): "
                  + ("all satisfied" if d["rules_ok"] else "VIOLATED: " + "; ".join(d["rule_why"][:3])))
    if d and d.get("msgs"):
        ev.append("checker: " + " | ".join(d["msgs"][:4]))
    elif d is not None:
        ev.append("checker: no problems")
    return ev


for spec in sys.argv[2:]:
    arm, files = spec.split("=")
    ans_p, _, res_p = files.partition(":")
    ans = {json.loads(l)["id"]: json.loads(l)["answer"] for l in open(ans_p, encoding="utf-8") if l.strip()}
    rows = {}
    if res_p:
        rows = {json.loads(l)["id"]: json.loads(l) for l in open(res_p, encoding="utf-8") if l.strip()}
    for tid, a in ans.items():
        r = rows.get(tid) or {}
        for name, text, d in ((arm, a, r.get("before")), (arm + "V", r.get("fixed_answer") or a,
                                                          r.get("after") if r.get("fixed_answer") else r.get("before"))):
            slot = texts.setdefault(tid, {}).setdefault(text, {"arms": [], "evidence": evidence(tasks[tid], d)})
            slot["arms"].append(name)
ids = sorted(texts)
rng.shuffle(ids)
os.makedirs("judge", exist_ok=True)
key, packets = {}, [[] for _ in range(K)]
for n, tid in enumerate(ids):
    t = tasks[tid]
    items = list(texts[tid].items())
    rng.shuffle(items)
    labels = []
    for k, (text, slot) in enumerate(items):
        label = f"{tid}#{chr(65 + k)}"
        key[label] = slot["arms"]
        labels.append({"label": label, "answer": text, "evidence": slot["evidence"]})
    packets[n % K].append({"task": tid, "engine": {"unity": "Unity 6 (C#)", "godot": "Godot 4.x (GDScript)",
                                                   "unreal": "Unreal Engine 5.x (C++)", "love": "LOVE 11.5 (Lua, LuaJIT)",
                                                   "lua": "plain Lua 5.4"}[t["family"]],
                           "question": t["question"], "judge_notes": t.get("notes", ""), "answers": labels})
for k, p in enumerate(packets):
    json.dump(p, open(f"judge/packet{k + 1}.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
json.dump(key, open("judge/key.json", "w", encoding="utf-8"), indent=1)
print({f"packet{k + 1}": (len(p), sum(len(x["answers"]) for x in p)) for k, p in enumerate(packets)})
