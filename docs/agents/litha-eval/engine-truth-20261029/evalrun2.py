"""Engine-truth eval: tests/rules on the first-try answer, the NEW verifier on it, and its fix loop through the live router.

    python evalrun2.py tasks_all.json answers.jsonl results.jsonl [--nofix]

Dev polyglot instance (new checks) at PG_URL (default http://127.0.0.1:18111). Per task kind: io / gd_func (hidden tests),
gd_scene (a SceneTree test script in the real engine), love (driver.lua in the real engine), unity/unreal (regex rules +
the checker: `auto_ok`). The fix loop = Verifier.fix (2 rounds) with the router's `litha` as in the launcher's ?fix=1.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("PG_URL", "http://127.0.0.1:18111")
import harness  # noqa: E402
from gen import KEY, ROUTER  # noqa: E402

sys.path.insert(0, os.environ.get("REPO_SERVER", "server"))
from mesh.polyglot.client import Polyglot  # noqa: E402
from mesh.verify.apidump import ApiIndex  # noqa: E402
from mesh.verify.core import Verifier, extract_blocks  # noqa: E402
from mesh.verify.service import model_caller  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PG = Polyglot(harness.URL, harness.TOKEN, timeout_s=float(os.environ.get("PG_TIMEOUT", "8.0")))
VER = Verifier(ApiIndex.load(os.path.join(HERE, "roblox-api-index.json")), None, polyglot=PG)
CFG = {"router_url": ROUTER, "fix_model": "litha", "fix_max_tokens": 2048, "fix_timeout_s": 500}
CALL = model_caller(CFG, "Bearer " + KEY)
ENGINE_LANG = {"love": "lua", "lua": "lua", "godot": "gdscript", "unity": "csharp", "unreal": "cpp"}


def code_of(task: dict, answer: str) -> str | None:
    lang = ENGINE_LANG.get(task["family"], task["language"])
    want = {lang} | ({"luau", "lua", "love"} if lang == "lua" else set())
    blocks = extract_blocks(answer)
    cands = [b for b in blocks if b["language"] in want or not b["info"]]
    if task["family"] == "unreal":
        cands = [b for b in blocks if b["language"] in ("cpp", "c") or not b["info"]]
    if not cands:
        return None
    return max(cands, key=lambda b: len(b["code"]))["code"]


def rules_ok(task: dict, answer: str) -> tuple[bool | None, list[str]]:
    rules = task.get("rules")
    if not rules:
        return None, []
    code = "\n".join(b["code"] for b in extract_blocks(answer)) or answer
    miss = [r["re"] for r in rules.get("must", []) if r.get("auto") and not re.search(r["re"], code)]
    hit = [r["re"] for r in rules.get("forbid", []) if r.get("auto") and re.search(r["re"], code)]
    return (not miss and not hit), [f"missing {x}" for x in miss] + [f"forbidden {x}" for x in hit]


def run_scene(task: dict, code: str | None) -> dict:
    out = {"ran": False, "passed": 0, "total": task["tests"]["n"], "err": "", "compiled": False}
    if code is None:
        out["err"] = "no code block"
        return out
    r = harness.post("/run", {"language": "gdscript", "run_s": 25,
                              "files": {"answer.gd": code, "test.gd": task["tests"]["script"]}})
    so = r.get("stdout") or ""
    se = " ".join(s.get("stderr", "") for s in r.get("steps", []))
    out["ran"] = True
    out["passed"] = len(re.findall(r"^PASS ", so, re.M))
    fails = re.findall(r"^FAIL .*$", so, re.M)
    out["compiled"] = "Parse Error" not in (so + se) and "Compile Error" not in (so + se) and "LOAD" not in so
    errs = re.findall(r"SCRIPT ERROR: [^\n]*|Parse Error[^\n]*", so + "\n" + se)
    if fails or errs or out["passed"] != out["total"]:
        out["err"] = ("; ".join(fails[:2] + errs[:2]) or f"{out['passed']} PASS lines of {out['total']}")[:400]
        if errs:
            out["passed"] = min(out["passed"], out["total"] - 1)
    return out


def run_love(task: dict, code: str | None) -> dict:
    out = {"ran": False, "passed": 0, "total": task.get("n_pass") or 0, "err": "", "compiled": False}
    if code is None:
        out["err"] = "no code block"
        return out
    r = harness.post("/run", {"language": "love", "run_s": 25, "files": {"main.lua": code, "driver.lua": task["driver"]}})
    so = r.get("stdout") or ""
    se = " ".join(s.get("stderr", "") for s in r.get("steps", []))
    out["ran"] = True
    out["passed"] = len(re.findall(r"^PASS ", so, re.M))
    m = re.search(r"LOVE_ERROR: (.*)", se)
    out["compiled"] = not m
    fails = re.findall(r"^FAIL .*$", so, re.M)
    if m or fails or out["passed"] != out["total"]:
        out["err"] = ((m.group(0) if m else "") + "; ".join(fails[:2]) or f"{out['passed']} PASS of {out['total']}")[:400]
    return out


def tests(task: dict, answer: str) -> dict | None:
    kind, fam = task["kind"], task["family"]
    code = code_of(task, answer)
    if kind in ("io", "gd_func"):
        t = dict(task)
        t["language"] = "lua" if kind == "io" else t["language"]
        return harness.run_task(t, code)
    if kind == "gd_scene":
        return run_scene(task, code)
    if kind == "love" and task.get("driver"):
        return run_love(task, code)
    return None


def summary(rep: dict) -> dict:
    probs = [p for b in rep["blocks"] for p in b["problems"]] + rep["problems"]
    return {"errors": sum(p["severity"] == "error" for p in probs), "warnings": sum(p["severity"] == "warning" for p in probs),
            "langs": sorted({b["language"] or "?" for b in rep["blocks"]}),
            "msgs": [p["message"][:170] for p in probs if p["severity"] in ("error", "warning")][:8]}


def judge(task: dict, answer: str, res: dict | None) -> dict:
    """The automatic verdict of one answer: tests/rules and the checker (an instrument, not the blind judge)."""
    rep = VER.verify(answer, None, task["question"])
    s = summary(rep)
    ok_rules, why = rules_ok(task, answer)
    d = {"checker_errors": s["errors"], "checker_warnings": s["warnings"], "rules_ok": ok_rules, "rule_why": why[:4],
         "tests": res}
    if res is not None:
        d["tests_ok"] = res["total"] > 0 and res["passed"] == res["total"] and not res.get("err")
    d["flagged"] = bool(rep["needs_fix"])
    d["msgs"] = s["msgs"]
    return d, rep


def one(task: dict, a: dict, do_fix: bool) -> dict:
    row = {"id": task["id"], "family": task["family"], "kind": task["kind"]}
    ans = a["answer"]
    t0 = time.perf_counter()
    try:
        res = tests(task, ans)
    except Exception as e:                         # a harness problem must not stop the run
        res = {"ran": False, "passed": 0, "total": 1, "err": f"harness: {e}", "compiled": False}
    d, rep = judge(task, ans, res)
    row["before"] = d
    row["verify_ms"] = round((time.perf_counter() - t0) * 1000)
    row["finish"] = a.get("finish")
    row["fixed_answer"] = None
    if do_fix and rep["needs_fix"]:
        t1 = time.perf_counter()
        docs = None
        if os.environ.get("FIXFACTS"):             # the engine's core facts go into the fix prompt as reference text
            from mesh.engine import facts as _facts
            ref = _facts.core_text(task["question"])
            docs = (lambda names, ref=ref: ref) if ref else None
        fx = VER.fix(ans, CALL, None, 2, docs=docs, question=task["question"])
        row["fix_s"] = round(time.perf_counter() - t1, 1)
        row["fix_changes"] = fx["changes"]
        if fx["answer"] != ans:
            row["fixed_answer"] = fx["answer"]
            try:
                res2 = tests(task, fx["answer"])
            except Exception as e:
                res2 = {"ran": False, "passed": 0, "total": 1, "err": f"harness: {e}", "compiled": False}
            row["after"], _ = judge(task, fx["answer"], res2)
    return row


def main(tasks_path: str, answers_path: str, out_path: str, do_fix: bool = True):
    tasks = {t["id"]: t for t in json.load(open(tasks_path, encoding="utf-8"))}
    answers = [json.loads(l) for l in open(answers_path, encoding="utf-8") if l.strip()]
    done = set()
    if os.path.exists(out_path):
        done = {json.loads(l)["id"] for l in open(out_path, encoding="utf-8") if l.strip()}
    todo = [a for a in answers if a["id"] not in done and a["id"] in tasks]
    with open(out_path, "a", encoding="utf-8") as out, ThreadPoolExecutor(int(os.environ.get("WORKERS", "1"))) as ex:
        for row in ex.map(lambda a: one(tasks[a["id"]], a, do_fix), todo):
            out.write(json.dumps(row) + "\n")
            out.flush()
            b = row["before"]
            t = b["tests"] or {}
            print(row["id"], f"tests {t.get('passed')}/{t.get('total')}", f"rules={b['rules_ok']}", f"chk e{b['checker_errors']} w{b['checker_warnings']}",
                  "flag" if b["flagged"] else "", ("-> fixed " + str((row.get('after') or {}).get('tests_ok'))) if row.get("fixed_answer") else "",
                  "|", "; ".join(b["msgs"])[:150], flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], "--nofix" not in sys.argv)
