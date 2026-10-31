"""Both arms per task, one request at a time (the router is shared): B = live first try, F = engine facts note."""
import json, os, sys, time
os.environ.setdefault("MAX_TOKENS", "1500")
import gen
tasks = json.load(open("tasks_all.json", encoding="utf-8"))
files = {"B": "ans_B.jsonl", "F": "ans_F.jsonl"}
done = {a: {json.loads(l)["id"] for l in open(f, encoding="utf-8") if l.strip()} if os.path.exists(f) else set() for a, f in files.items()}
for round_ in range(40):
    todo = [(t, a) for t in tasks for a in ("B", "F") if t["id"] not in done[a]]
    if not todo:
        break
    for t, arm in todo:
        if arm == "F":
            os.environ["NOTE"] = "engine"
        else:
            os.environ.pop("NOTE", None)
        try:
            text, meta = gen.ask(t["question"])
        except Exception as e:
            print(t["id"], arm, "ERROR", e, flush=True)
            time.sleep(4)
            continue
        with open(files[arm], "a", encoding="utf-8") as out:
            out.write(json.dumps({"id": t["id"], "answer": text, **meta}) + "\n")
        done[arm].add(t["id"])
        print(t["id"], arm, meta, flush=True)
