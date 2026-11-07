"""Polyglot eval harness (PC side). Talks to star-polyglot through the SSH tunnel on 127.0.0.1:18110.

    python harness.py validate tasks.json        reference solutions: must pass their tests and get 0 checker errors
    python harness.py check LANG FILE            /check one file (prints the reply)
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ.get("REPO_SERVER", "server"))
from mesh.verify.core import extract_blocks  # noqa: E402

URL = os.environ.get("PG_URL", "http://127.0.0.1:18110")
TOKEN = open(os.path.join(HERE, "token"), encoding="utf-8").read().strip()
FILE = {"python": "main.py", "javascript": "main.js", "typescript": "main.ts", "cpp": "main.cpp", "c": "main.c",
        "rust": "main.rs", "go": "main.go", "csharp": "main.cs", "lua": "main.lua", "shell": "main.sh"}


def post(path: str, payload: dict, timeout: float = 180) -> dict:
    req = urllib.request.Request(URL + path, json.dumps(payload).encode(),
                                 {"Content-Type": "application/json", "Authorization": "Bearer " + TOKEN})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def check(lang: str, code: str, context: str = "") -> dict:
    return post("/check", {"language": lang, "code": code, "context": context}, 60)


def pick_code(answer: str, lang: str) -> str | None:
    """The answer's code for this task: the longest block in the task language (untagged blocks count)."""
    blocks = extract_blocks(answer)
    want = {lang} | ({"luau", "lua"} if lang == "lua" else set())
    cands = [b for b in blocks if b["language"] in want or not b["info"]]
    if lang == "sql":
        cands = [b for b in blocks if b["language"] == "sql" or not b["info"]]
    if not cands:
        return None
    return max(cands, key=lambda b: len(b["code"]))["code"]


def norm(text: str) -> str:
    return "\n".join(ln.rstrip() for ln in (text or "").strip().splitlines())


SQL_RUNNER = r'''
import json, sqlite3, sys
setup, answer = json.load(open("job.json"))
db = sqlite3.connect(":memory:")
db.executescript(setup)
rows, buf = None, ""
for line in answer.splitlines(True):
    buf += line
    if sqlite3.complete_statement(buf):
        cur = db.execute(buf)
        if cur.description:
            rows = cur.fetchall()
        buf = ""
if buf.strip():
    cur = db.execute(buf)
    if cur.description:
        rows = cur.fetchall()
print(json.dumps(rows))
'''


def run_task(task: dict, code: str | None) -> dict:
    """{"ran": bool, "compiled": bool, "passed": int, "total": int, "err": str}"""
    lang, kind = task["language"], task["kind"]
    tests = task.get("tests") or []
    out = {"ran": False, "compiled": False, "passed": 0, "total": len(tests), "err": ""}
    if code is None:
        out["err"] = "no code block"
        return out
    if kind == "io":
        files, job = {FILE.get(lang, "main.txt"): code}, {"language": lang, "run_s": 10}
        if lang == "java":
            m = re.search(r"public\s+(?:final\s+)?class\s+(\w+)", code)
            name = m.group(1) if m else "Main"
            mains = [] if ("static void main" in code and m) else \
                re.findall(r"class\s+(\w+)[^{]*\{(?:(?!\bclass\b).)*?static\s+void\s+main", code, re.S)
            files = {name + ".java": code}
            job["main_class"] = mains[0] if mains else name
        files.update(task.get("files") or {})
        job["files"] = files
        job["inputs"] = [t.get("stdin", "") for t in tests]
        r = post("/run", job)
        out["ran"] = True
        out["compiled"] = r.get("phase") == "run"
        if not out["compiled"]:
            out["err"] = ((r.get("steps") or [{}])[-1].get("stderr") or r.get("error") or "")[:600]
            return out
        for t, run in zip(tests, r.get("runs") or []):
            if not run["timed_out"] and norm(run["stdout"]) == norm(t["stdout"]):
                out["passed"] += 1
            elif not out["err"]:
                out["err"] = f"stdin={t.get('stdin','')[:80]!r} want={t['stdout'][:80]!r} got={run['stdout'][:120]!r} rc={run['rc']} {run['stderr'][:200]}"
        return out
    if kind == "sql":
        r = post("/run", {"language": "python", "run_s": 10,
                          "files": {"main.py": SQL_RUNNER, "job.json": json.dumps([task["setup"], code])}})
        out["ran"] = True
        out["compiled"] = r.get("ok", False)
        out["total"] = 1
        if not r.get("ok"):
            out["err"] = ((r.get("steps") or [{}])[-1].get("stderr") or "")[-400:]
            return out
        got = json.loads(r["stdout"] or "null")
        want = task["expected"]
        same = (got == want) if task.get("ordered") else (sorted(map(json.dumps, got or [])) == sorted(map(json.dumps, want)))
        out["passed"] = int(bool(same))
        if not same:
            out["err"] = f"want={json.dumps(want)[:200]} got={json.dumps(got)[:200]}"
        return out
    if kind == "gd_func":
        lines = ["extends SceneTree", "func _init():", '\tvar A = load("res://answer.gd")',
                 "\tif A == null:", '\t\tprint("LOAD_FAILED")', "\t\tquit(1)", "\t\treturn",
                 "\tvar obj = A.new()"]
        for t in tests:
            lines.append("\tprint(str(" + t["expr"].replace("Answer.", "obj.") + "))")
        lines += ["\tquit()", ""]
        r = post("/run", {"language": "gdscript", "run_s": 15, "files": {"answer.gd": code, "test.gd": "\n".join(lines)}})
        out["ran"] = True
        stdout = r.get("stdout") or ""
        body = [ln for ln in stdout.splitlines() if ln.strip() and not ln.startswith(("Godot Engine", "WARNING", "   at:", "SCRIPT ERROR", "ERROR"))]
        out["compiled"] = "LOAD_FAILED" not in stdout and "Parse Error" not in (stdout + ((r.get("steps") or [{}])[-1].get("stderr") or ""))
        for t, got in zip(tests, body):
            if got.strip() == t["expect"].strip():
                out["passed"] += 1
            elif not out["err"]:
                out["err"] = f"{t['expr']} want={t['expect']!r} got={got!r}"
        if not out["compiled"]:
            out["err"] = (stdout + ((r.get("steps") or [{}])[-1].get("stderr") or ""))[-600:]
        return out
    return out          # engine tasks: judged, compile = checker only


def validate(path: str):
    tasks = json.load(open(path, encoding="utf-8"))
    def one(t):
        res = run_task(t, t["reference"]) if t["kind"] != "engine" else {"total": 0, "passed": 0, "compiled": None, "err": ""}
        chk = check("gdscript" if t["kind"] == "gd_func" else t["language"], t["reference"]) \
            if t["language"] not in ("html", "css", "unreal") else {"checked": False, "problems": []}
        errs = [p["message"] for p in chk.get("problems", []) if p["severity"] in ("error", "warning")]
        return t["id"], res, chk.get("checked"), errs
    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(one, tasks))
    bad = 0
    for tid, res, checked, errs in rows:
        ok = (res["passed"] == res["total"]) and not errs
        bad += not ok
        print(("OK  " if ok else "FAIL"), tid, f"tests {res['passed']}/{res['total']}", f"checked={checked}",
              ("checker: " + " | ".join(errs)[:300]) if errs else "", res.get("err", "")[:300])
    print(f"{len(rows) - bad}/{len(rows)} references OK")


if __name__ == "__main__":
    if sys.argv[1] == "validate":
        validate(sys.argv[2])
    elif sys.argv[1] == "check":
        print(json.dumps(check(sys.argv[2], open(sys.argv[3], encoding="utf-8").read()), indent=1))
