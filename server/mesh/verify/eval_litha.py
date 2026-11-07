"""Litha eval for the verifier: problem rates of Litha answers before and after the fix loop.

    python -m mesh.verify.eval_litha --index roblox-api-index.json [--analyzer luau-analyze] \
        --questions docs/agents/litha-eval/questions.json --answers a.jsonl [--answers b.jsonl ...] \
        [--fresh N --system prompt.txt --save-fresh f.jsonl] [--fix] [--url http://<mesh>:8101]
        [--router http://<mesh>:8100] [--out result.json]

--answers: jsonl files with {"id", "content"} (the bench lane's answer sets). --fresh N: also ask `litha` through the
router for new answers to the first N code questions (system prompt from --system). --fix: send every answer that
needs a fix to the live POST /mesh/verify?fix=1 and verify the result. The brain key is read from
~/.star/server_api_key (never printed). Code questions = areas roblox, unity, minecraft, kids (code ones only count
when they contain a code block).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

from .apidump import ApiIndex
from .core import Verifier

WRONG_API = {"unknown_api", "unknown_class", "unknown_enum", "unknown_service", "not_creatable", "wrong_call",
             "not_accessible", "roblox_rule", "unity_message", "mc_unknown_command", "mc_selector", "mc_datapack", "mc_function"}
SYNTAX = {"syntax", "type", "mc_syntax"}
AREAS = {"roblox", "unity", "minecraft", "kids"}


def key() -> str:
    return (Path.home() / ".star" / "server_api_key").read_text(encoding="utf-8").split()[0]


def post(url: str, body: dict, timeout=600) -> tuple[dict, float]:
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": "Bearer " + key()})
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return data, (time.perf_counter() - t) * 1000


def stats(report: dict) -> dict:
    probs = [p for b in report["blocks"] for p in b["problems"]] + report["problems"]
    return {"blocks": len(report["blocks"]), "checked": sum(b["checked"] for b in report["blocks"]),
            "wrong_api": sum(p["kind"] in WRONG_API for p in probs),
            "syntax": sum(p["kind"] in SYNTAX for p in probs),
            "deprecated": sum(p["kind"] == "deprecated" for p in probs),
            "ok": report["ok"], "needs_fix": report["needs_fix"],
            "problems": [f"{p['kind']}: {p['message']}" + (f" (use {p['suggestion']})" if p.get("suggestion") else "")
                         for p in probs if p["severity"] != "info"]}


def summarize(rows: list[dict], key_: str) -> dict:
    with_code = [r for r in rows if r[key_]["checked"]]
    n = len(with_code) or 1
    return {"answers_with_checked_code": len(with_code),
            "answers_with_wrong_api": sum(r[key_]["wrong_api"] > 0 for r in with_code),
            "answers_with_syntax_error": sum(r[key_]["syntax"] > 0 for r in with_code),
            "answers_with_deprecated": sum(r[key_]["deprecated"] > 0 for r in with_code),
            "answers_failing": sum(not r[key_]["ok"] for r in with_code),
            "wrong_api_rate": round(sum(r[key_]["wrong_api"] > 0 for r in with_code) / n, 3),
            "syntax_rate": round(sum(r[key_]["syntax"] > 0 for r in with_code) / n, 3),
            "fail_rate": round(sum(not r[key_]["ok"] for r in with_code) / n, 3)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--analyzer")
    ap.add_argument("--questions", required=True)
    ap.add_argument("--answers", action="append", default=[])
    ap.add_argument("--fresh", type=int, default=0)
    ap.add_argument("--system")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--url", default="")
    ap.add_argument("--router", default="")
    ap.add_argument("--save-fresh")
    ap.add_argument("--ids", help="comma-separated question ids (default: all code questions)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    verifier = Verifier(ApiIndex.load(a.index), a.analyzer)
    qs = [q for q in json.loads(Path(a.questions).read_text(encoding="utf-8"))["questions"] if q["area"] in AREAS]
    if a.ids:
        qs = [q for q in qs if q["id"] in a.ids.split(",")]
    sets = {}
    for path in a.answers:
        by_id = {}
        for ln in Path(path).read_text(encoding="utf-8").splitlines():
            if ln.strip():
                d = json.loads(ln)
                by_id[d["id"]] = {"content": d["content"], "answer_ms": (d.get("total") or 0) * 1000}
        sets[Path(path).stem] = by_id
    if a.fresh:
        system = Path(a.system).read_text(encoding="utf-8") if a.system else ""
        fresh = {}
        for q in qs[:a.fresh]:
            msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": q["prompt"]}]
            d, ms = post(a.router.rstrip("/") + "/v1/chat/completions",
                         {"model": "litha", "messages": msgs, "temperature": 0.4, "max_tokens": 900, "stream": False,
                          "chat_template_kwargs": {"enable_thinking": False}})
            fresh[q["id"]] = {"content": d["choices"][0]["message"].get("content") or "", "answer_ms": ms}
            print(f"fresh {q['id']}: {ms / 1000:.1f} s", flush=True)
        sets["fresh-litha"] = fresh
        if a.save_fresh:
            Path(a.save_fresh).write_text("".join(json.dumps({"id": k, "content": v["content"],
                                                              "total": v["answer_ms"] / 1000}) + "\n"
                                                  for k, v in fresh.items()), encoding="utf-8")
    result = {"dump": verifier.api.meta, "sets": {}}
    for name, by_id in sets.items():
        rows = []
        for q in qs:
            if q["id"] not in by_id:
                continue
            text = by_id[q["id"]]["content"]
            rep = verifier.verify(text)
            row = {"id": q["id"], "answer_ms": round(by_id[q["id"]]["answer_ms"]), "verify_ms": rep["ms"],
                   "before": stats(rep)}
            if a.fix and rep["needs_fix"] and a.url:
                d, ms = post(a.url.rstrip("/") + "/mesh/verify?fix=1", {"answer": text})
                after = verifier.verify(d["answer"])
                row.update(fix_ms=round(ms), fix_rounds=d["rounds"], model_ms=d["model_ms"], after=stats(after),
                           fixed_answer=d["answer"])
                print(f"{name} {q['id']}: fixed in {ms / 1000:.1f} s, rounds {d['rounds']}, ok {after['ok']}",
                      flush=True)
            else:
                row["after"] = row["before"]
            rows.append(row)
        fixed = [r for r in rows if "fix_ms" in r]
        result["sets"][name] = {"before": summarize(rows, "before"), "after": summarize(rows, "after"),
                                "verify_ms_median": sorted(r["verify_ms"] for r in rows)[len(rows) // 2] if rows else 0,
                                "fix_ms_median": sorted(r["fix_ms"] for r in fixed)[len(fixed) // 2] if fixed else 0,
                                "fixed_answers": len(fixed), "rows": rows}
        print(name, json.dumps({k: v for k, v in result["sets"][name].items() if k != "rows"}), flush=True)
    if a.out:
        Path(a.out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
