"""A/B of diff-only edit answers (star/edit_format.py) against full rewrites on evals/roblox/edit-tasks-v1.json.

  bundle (PC)     python benchmarks/edit_format_bench.py bundle --suite evals/roblox/edit-tasks-v1.json --out b.json
  gen    (server) python3 edit_format_bench.py gen --bundle b.json --out r.json --server http://127.0.0.1:8099
                  --knowledge http://127.0.0.1:8091 --key-file FILE [--budget-s 420]
  score  (PC)     python benchmarks/edit_format_bench.py score --suite evals/roblox/edit-tasks-v1.json --results r.json
                  --server http://<server>:8080/v1 --ssh <user>@<lxd-host>

`gen` needs only the standard library and a `star` directory next to it holding edit_format.py, edit_match.py and
luau_lint.py, so it runs on the model server itself (inside the quiet lock). Greedy (temperature 0), no prompt cache,
one request at a time; even tasks ask the full rewrite first, odd tasks the diff first. Per task and arm it records
the tokens the server generated, the wall seconds (requests + checks + the fallback request) and the answer STAR
would show; `gen` resumes from its result file and stops starting new tasks after --budget-s seconds. `score` grades
the shown answers with the suite's own checks (star/eval_checks.py: Luau check, unit tests in the server's Luau VM).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
MAX_TOKENS = 2000


def post(url: str, body: dict, key: str = "", timeout: float = 900) -> dict:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    request = urllib.request.Request(url, json.dumps(body).encode("utf-8"), headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def ask(server: str, system: str, prompt: str) -> dict:
    started = time.monotonic()
    data = post(server + "/v1/chat/completions", {
        "model": "star-fast", "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "temperature": 0, "top_k": 1, "seed": 42, "max_tokens": MAX_TOKENS, "cache_prompt": False})
    timings = data.get("timings") or {}
    return {"text": data["choices"][0]["message"].get("content") or "", "seconds": round(time.monotonic() - started, 2),
            "tokens": timings.get("predicted_n"), "prompt_tokens": timings.get("prompt_n"),
            "gen_tps": timings.get("predicted_per_second"), "draft_n": timings.get("draft_n"),
            "draft_accepted": timings.get("draft_n_accepted"), "finish": data["choices"][0].get("finish_reason")}


def knowledge_check(base: str, key: str):
    """The knowledge service's /luau/check reduced to what star.edit_format needs (as KnowledgeClient.luau_check)."""
    def check(code: str) -> dict:
        try:
            data = post(base + "/luau/check", {"code": code}, key, timeout=30)
        except OSError as exc:
            raise OSError("knowledge service unavailable") from exc
        errors = data.get("errors") or []
        if data.get("executed") is not False or (not data.get("ok") and not errors):
            raise ValueError("no verdict")
        return {"ran": True, "ok": bool(data.get("ok")) and not errors,
                "error_count": data.get("error_count") or len(errors)}
    return check


def run_full(server, system, task):
    first = ask(server, system, task["prompt"])
    return {"answer": first["text"], "seconds": first["seconds"], "tokens": first["tokens"] or 0, "requests": [first]}


def run_diff(server, system, task, check):
    from star import edit_format
    edit = edit_format.find_edit(task["prompt"])
    if edit is None:
        return {"skipped": "not an edit request"}
    started = time.monotonic()
    first = ask(server, system, edit.prompt)
    done = edit_format.finish(edit, first["text"], check=check)
    requests = [first]
    answer = done.answer
    if not done.ok:
        second = ask(server, system, task["prompt"])
        requests.append(second)
        answer = second["text"]
    return {"answer": answer, "seconds": round(time.monotonic() - started, 2),
            "tokens": sum(r["tokens"] or 0 for r in requests), "requests": requests,
            "outcome": done.reason, "edits": done.edits, "fallback": not done.ok}


def gen(args) -> int:
    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    out = Path(args.out)
    results = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"tasks": {}}
    key = Path(args.key_file).read_text(encoding="utf-8").splitlines()[0].strip() if args.key_file else ""
    check = knowledge_check(args.knowledge, key) if args.knowledge else None
    started = time.monotonic()
    for index, task in enumerate(bundle["tasks"]):
        if task["id"] in results["tasks"]:
            continue
        if time.monotonic() - started > args.budget_s:
            print("budget used; stopping before", task["id"], flush=True)
            break
        arms = ("full", "diff") if index % 2 == 0 else ("diff", "full")
        row = {}
        for arm in arms:
            row[arm] = (run_full(args.server, bundle["system"], task) if arm == "full"
                        else run_diff(args.server, bundle["system"], task, check))
        results["tasks"][task["id"]] = row
        out.write_text(json.dumps(results, indent=1), encoding="utf-8")
        d, f = row["diff"], row["full"]
        print(f"{task['id']} full {f['tokens']} tok {f['seconds']} s | diff {d.get('tokens')} tok {d.get('seconds')} s "
              f"{d.get('outcome')}", flush=True)
    print("done" if len(results["tasks"]) == len(bundle["tasks"]) else "partial", len(results["tasks"]), flush=True)
    return 0


def bundle(args) -> int:
    from star.agent import make_system_message
    tasks = json.loads(Path(args.suite).read_text(encoding="utf-8"))
    data = {"system": make_system_message("", tools_attached=False)["content"],
            "tasks": [{"id": t["id"], "prompt": t["prompt"]} for t in tasks]}
    Path(args.out).write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(len(data["tasks"]), "tasks")
    return 0


def score(args) -> int:
    from star import eval_checks
    from star.desktop_core import Settings
    from star.doc_knowledge import client_for
    from star.eval_runner import load_suite, read_key, DEFAULT_KEY_FILE
    from star.eval_sandbox import ContainerSandbox
    os.environ["STAR_SERVER_API_KEY"] = read_key(Path(args.key_file or DEFAULT_KEY_FILE))
    suite = load_suite(Path(args.suite))
    knowledge = client_for(Settings(provider="star_server", server_endpoint=args.server, model="star-fast",
                                    project="edit-bench"))
    sandbox = ContainerSandbox(args.ssh)
    results = json.loads(Path(args.results).read_text(encoding="utf-8"))
    rows = []
    for task in suite.tasks:
        row = results["tasks"].get(task["id"])
        if row is None:
            continue
        line = {"id": task["id"], "lines": task.get("source_lines")}
        for arm in ("full", "diff"):
            graded = eval_checks.score_answer(task, row[arm]["answer"], luau_check=knowledge.luau_check,
                                              sandbox=sandbox, prelude=suite.prelude, test_body=suite.test_body(task))
            line[arm] = {"passed": graded.passed, "tokens": row[arm]["tokens"], "seconds": row[arm]["seconds"],
                         "why": "; ".join(graded.reasons)[:160]}
        line["diff"].update(outcome=row["diff"].get("outcome"), fallback=row["diff"].get("fallback"))
        rows.append(line)
        print(f"{line['id']:8} full {'PASS' if line['full']['passed'] else 'fail'} {line['full']['tokens']:5} tok "
              f"{line['full']['seconds']:7.1f} s | diff {'PASS' if line['diff']['passed'] else 'fail'} "
              f"{line['diff']['tokens']:5} tok {line['diff']['seconds']:7.1f} s  {line['diff']['outcome']}", flush=True)
    summary = {}
    for arm in ("full", "diff"):
        summary[arm] = {"passed": sum(r[arm]["passed"] for r in rows), "tasks": len(rows),
                        "tokens": sum(r[arm]["tokens"] for r in rows), "seconds": round(sum(r[arm]["seconds"] for r in rows), 1),
                        "median_seconds": statistics.median(r[arm]["seconds"] for r in rows) if rows else None}
    summary["diff"]["applied"] = sum(r["diff"]["outcome"] == "applied" for r in rows)
    summary["diff"]["fallbacks"] = sum(bool(r["diff"]["fallback"]) for r in rows)
    print("SUMMARY", json.dumps(summary))
    if args.out:
        Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="edit_format_bench")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("bundle")
    b.add_argument("--suite", required=True)
    b.add_argument("--out", required=True)
    g = sub.add_parser("gen")
    g.add_argument("--bundle", required=True)
    g.add_argument("--out", required=True)
    g.add_argument("--server", required=True)
    g.add_argument("--knowledge", default="")
    g.add_argument("--key-file", default="")
    g.add_argument("--budget-s", type=float, default=420)
    s = sub.add_parser("score")
    s.add_argument("--suite", required=True)
    s.add_argument("--results", required=True)
    s.add_argument("--server", required=True)
    s.add_argument("--ssh", required=True)
    s.add_argument("--key-file", default="")
    s.add_argument("--out", default="")
    args = parser.parse_args(argv)
    return {"bundle": bundle, "gen": gen, "score": score}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
