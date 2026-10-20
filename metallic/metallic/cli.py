"""metallic: the Metallic layer CLI.

    metallic check [--base REF] [--full] [--jobs N] [--no-cache] [--only a,b] [--json] [--ai-review]
    metallic queue add BRANCH... | list | clear
    metallic queue run [--target BRANCH] [--apply] [--no-batch] [BRANCH...]
    metallic status [--out FILE]                 dashboard data (JSON)
    metallic serve [--port 8765] [--dist DIR]    dashboard + live /data.json on 127.0.0.1

Exit status: 0 green, 1 red (a blocking check failed), 2 usage or setup error, 3 queue busy.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from . import cache as cache_mod
from . import engine, gitutil, status
from . import queue as queue_mod
from .config import load

MARK = {"pass": "ok  ", "fail": "FAIL", "warn": "warn", "skip": "skip", "info": "info", "error": "ERR "}


def _printer(quiet: bool):
    def emit(kind, obj, t):
        if quiet:
            return
        if kind == "check":
            print(f"{t:7.1f}s  {MARK.get(obj.status, obj.status):4}  {obj.name:16} {obj.summary}"
                  + ("  [cached]" if obj.cached else ""), file=sys.stderr, flush=True)
            for f in obj.findings[:8]:
                where = f"{f['file']}:{f['line']}" if f["line"] else f["file"]
                print(f"                 {f['severity']:4}  {where}  {f['rule']}: {f['message'][:160]}",
                      file=sys.stderr)
        elif kind == "selection":
            why = f" ({obj['full_reason']})" if obj["full_reason"] else ""
            print(f"{t:7.1f}s  ....  tests            {obj['selected']}/{obj['total_files']} files affected{why}, "
                  f"{obj['cached']} cached, {obj['ran']} to run", file=sys.stderr, flush=True)
        elif kind == "test" and obj.status != "pass":
            print(f"{t:7.1f}s  {MARK.get(obj.status, obj.status):4}  test             {obj.path} "
                  + "; ".join(obj.failures[:2])[:200], file=sys.stderr, flush=True)
        elif kind in ("entry", "batch"):
            text = obj if kind == "batch" else f"{obj['branch']}: {obj['status']} ({obj['reason']})"
            print(f"{t:7.1f}s  queue {kind}: {text}", file=sys.stderr, flush=True)
    return emit


def cmd_check(a) -> int:
    root = gitutil.repo_root(a.repo)
    cfg = load(root)
    cache = cache_mod.Cache(Path(a.cache) if a.cache else engine.default_cache_dir(), enabled=not a.no_cache)
    report = engine.run_check(root, cfg, base=a.base, full=a.full, jobs=a.jobs, cache=cache,
                              only=a.only.split(",") if a.only else None, verdict_file=a.eval_verdict,
                              ai_review=a.ai_review, emit=_printer(a.json))
    path = engine.save_report(root, report)
    if a.json:
        print(json.dumps(report, indent=1))
    else:
        t = report["timings"]
        print(f"\n{report['verdict'].upper()}  {cfg.name}  {report['changed']} changed file(s) vs {report['base'][:10]}"
              f"  first signal {t.get('first_signal', 0):.1f}s, first test {t.get('first_test', 0):.1f}s, "
              f"total {t['total']:.1f}s, cache {report['cache']['hits']}/{report['cache']['hits'] + report['cache']['misses']}"
              f" hits\nreport: {path}")
    return 0 if report["verdict"] == "green" else 1


def cmd_queue(a) -> int:
    root = gitutil.repo_root(a.repo)
    if a.action == "add":
        for b in a.branches:
            gitutil.rev(b, root)
        queue_mod.save_pending(root, queue_mod.pending(root) + [b for b in a.branches
                                                                if b not in queue_mod.pending(root)])
    if a.action == "clear":
        queue_mod.save_pending(root, [])
    if a.action in ("add", "list", "clear"):
        for i, b in enumerate(queue_mod.pending(root), 1):
            print(f"{i}. {b}")
        return 0
    cfg = load(root)
    branches = a.branches or queue_mod.pending(root)
    if not branches:
        print("queue is empty", file=sys.stderr)
        return 2
    cache = cache_mod.Cache(Path(a.cache) if a.cache else engine.default_cache_dir(), enabled=not a.no_cache)
    try:
        report = queue_mod.run(root, a.target or cfg.target, branches, apply=a.apply, jobs=a.jobs, cache=cache,
                               emit=_printer(a.json), batch=not a.no_batch)
    except queue_mod.QueueBusy as e:
        print(str(e), file=sys.stderr)
        return 3
    path = engine.save_report(root, report)
    if not a.branches:
        queue_mod.save_pending(root, [b for b in queue_mod.pending(root) if b not in report["merged"]
                                      and b not in [e["branch"] for e in report["entries"]]])
    if a.json:
        print(json.dumps(report, indent=1))
    else:
        for e in report["entries"]:
            print(f"{e['status']:9} {e['branch']}  {e['reason']}")
        tail = ("applied to " + report["target"]) if report["applied"] else (report.get("apply_error") or "dry run")
        print(f"result {report['result'][:10]} ({len(report['merged'])}/{len(branches)} merged, {tail}), "
              f"{report['seconds']:.1f}s\nreport: {path}")
    return 0 if all(e["status"] == "merged" for e in report["entries"]) else 1


def cmd_status(a) -> int:
    root = None
    try:
        root = gitutil.repo_root(a.repo)
    except gitutil.GitError:
        pass
    data = json.dumps(status.collect(root), indent=1)
    if a.out:
        Path(a.out).write_text(data, encoding="utf-8")
    else:
        print(data)
    return 0


def cmd_serve(a) -> int:
    import http.server
    import functools
    root = gitutil.repo_root(a.repo)
    dist = Path(a.dist) if a.dist else Path(__file__).resolve().parents[1] / "dashboard" / "dist"
    if not (dist / "index.html").exists():
        print(f"no built dashboard in {dist} (npm run build in metallic/dashboard)", file=sys.stderr)
        return 2

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?")[0] == "/data.json":
                body = json.dumps(status.collect(root)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), functools.partial(Handler, directory=str(dist)))
    print(f"metallic dashboard on http://127.0.0.1:{a.port}/", file=sys.stderr)
    server.serve_forever()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="metallic", description="Metallic layer: checks, merge queue, dashboard data")
    p.add_argument("--repo", default=".", help="repository (default: current folder)")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="built-in checks, gates and impact-selected tests on the work tree")
    c.add_argument("--base", help="compare with this commit (default: merge base with the project target)")
    c.add_argument("--full", action="store_true", help="run every test file (cached ones still skip)")
    c.add_argument("--only", help="comma list of check names")
    c.add_argument("--eval-verdict", help="paired eval verdict JSON for eval-sensitive changes")
    c.add_argument("--ai-review", action="store_true", help="ask STAR's brain for review comments (never blocking)")
    q = sub.add_parser("queue", help="local merge queue on the combined tree")
    q.add_argument("action", choices=["add", "list", "clear", "run"])
    q.add_argument("branches", nargs="*")
    q.add_argument("--target", help="target branch (default: [project] target in metallic.toml)")
    q.add_argument("--apply", action="store_true", help="fast-forward the local target branch if green")
    q.add_argument("--no-batch", action="store_true", help="test one branch at a time from the start")
    for sp in (c, q):
        sp.add_argument("--jobs", type=int, default=int(os.environ.get("METALLIC_JOBS", "4")))
        sp.add_argument("--cache", help="cache folder (default ~/.metallic/cache or $METALLIC_CACHE)")
        sp.add_argument("--no-cache", action="store_true")
        sp.add_argument("--json", action="store_true", help="print the report as JSON on stdout")
    s = sub.add_parser("status", help="dashboard data as JSON")
    s.add_argument("--out")
    v = sub.add_parser("serve", help="serve the dashboard with live data on 127.0.0.1")
    v.add_argument("--port", type=int, default=8765)
    v.add_argument("--dist")
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return {"check": cmd_check, "queue": cmd_queue, "status": cmd_status, "serve": cmd_serve}[a.cmd](a)
    except gitutil.GitError as e:
        print(f"metallic: {e}", file=sys.stderr)
        return 2
