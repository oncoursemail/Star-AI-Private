"""`metallic check`: built-in checks, configured gates and impact-selected tests on one tree, with the result cache.

Order is chosen for time to first signal: the sub-second built-in checks print first, then gates and test batches
run side by side. The report (JSON) records when the first verdict and the first test verdict arrived.
"""
from __future__ import annotations

from dataclasses import asdict
import datetime as dt
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import threading
import time

from . import cache as cache_mod
from . import checks, gitutil, impact, review, testrun
from .config import Config, Gate, interpreter, matches, private_names


def default_cache_dir() -> Path:
    return Path(os.environ.get("METALLIC_CACHE") or Path.home() / ".metallic" / "cache")


def resolve_base(root: Path, cfg: Config, base: str | None) -> str:
    """The commit to compare with: --base, else the merge base of HEAD and the project's target, else HEAD."""
    if base:
        return gitutil.rev(base, root)
    if gitutil.ok(["rev-parse", "--verify", cfg.target], root):
        mb = gitutil.git(["merge-base", "HEAD", cfg.target], root, check=False).strip()
        if mb:
            return mb
    return gitutil.rev("HEAD", root)


def _run_gate(root: Path, gate: Gate, python: str, files: dict[str, str], cache: cache_mod.Cache,
              toolchain: str) -> checks.CheckResult:
    started = time.monotonic()
    missing = [r for r in gate.requires if not (root / r).exists()]
    if missing:
        return checks.CheckResult(gate.name, checks.SKIP, "requires " + ", ".join(missing), blocking=gate.blocking)
    inputs = sorted((p, b) for p, b in files.items() if matches(p, gate.inputs))
    k = cache_mod.key("gate", gate.name, gate.cmd, toolchain, inputs)
    rec = cache.get(k)
    if rec:
        return checks.CheckResult(gate.name, checks.PASS, rec.get("summary", "cached pass"), cached=True,
                                  blocking=gate.blocking)
    with tempfile.TemporaryDirectory(prefix="metallic-gate-") as tmp:
        cmd = [c.replace("{python}", python).replace("{tmp}", tmp) for c in gate.cmd]
        cmd[0] = shutil.which(cmd[0]) or cmd[0]          # npm is npm.cmd on Windows
        try:
            proc = subprocess.run(cmd, cwd=str(root), capture_output=True, timeout=gate.timeout, shell=False)
            code, out = proc.returncode, (proc.stdout + proc.stderr).decode("utf-8", "replace")
        except (OSError, subprocess.TimeoutExpired) as e:
            code, out = -1, f"{type(e).__name__}: {e}"
    seconds = round(time.monotonic() - started, 2)
    tail = "\n".join(out.strip().splitlines()[-30:])
    if code == 0:
        summary = (out.strip().splitlines() or ["ok"])[-1][:200]
        cache.put(k, {"summary": summary, "seconds": seconds})
        return checks.CheckResult(gate.name, checks.PASS, summary, seconds=seconds, blocking=gate.blocking)
    status = checks.FAIL if gate.blocking else checks.WARN
    return checks.CheckResult(gate.name, status, f"exit {code}", [checks.finding("", 0, gate.name, tail, status)],
                              seconds=seconds, blocking=gate.blocking)


def run_check(root: Path, cfg: Config, *, base: str | None = None, tree: str | None = None, branch: str | None = None,
              full: bool = False, jobs: int = 4, cache: cache_mod.Cache | None = None, only: list[str] | None = None,
              verdict_file: str | None = None, ai_review: bool = False, emit=None,
              test_cache_scope: str = "closure", fail_fast: bool = False) -> dict:
    """test_cache_scope "closure": a test file's cached pass is reused while its dependency closure is unchanged
    (fast local signal); "tree": only for the identical tree (the queue: inferred dependencies are never trusted)."""
    t0 = time.monotonic()
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    emit = emit or (lambda *_: None)
    cache = cache or cache_mod.Cache(default_cache_dir())
    state = gitutil.state_dir(root)
    base_sha = resolve_base(root, cfg, base)
    base_tree = gitutil.tree_of(base_sha, root)
    tree = tree or gitutil.worktree_tree(root)
    branch = branch or gitutil.current_branch(root)
    files = gitutil.blobs(tree, root)
    changed = gitutil.changed(base_tree, tree, root)
    timings: dict[str, float] = {"snapshot": round(time.monotonic() - t0, 3)}
    results: list[checks.CheckResult] = []
    lock = threading.Lock()

    def record(r: checks.CheckResult):
        with lock:
            results.append(r)
            timings.setdefault("first_signal", round(time.monotonic() - t0, 3))
        emit("check", r, time.monotonic() - t0)

    ctx = checks.Context(root=root, cfg=cfg, base_tree=base_tree, tree=tree, files=files, changed=changed,
                         branch=branch)
    names = [n for n in checks.ALL if not only or n in only]
    for r in checks.run_builtin(ctx, names, verdict_file=verdict_file, state=state, private_names=private_names()):
        record(r)

    python = interpreter(cfg)
    toolchain = cache_mod.toolchain(python)
    config_changed = "metallic.toml" in changed

    def gates_job():
        for g in cfg.gates:
            if only and g.name not in only:
                continue
            if not (full or config_changed or any(matches(f, g.inputs) for f in changed)):
                record(checks.CheckResult(g.name, checks.SKIP, "inputs unchanged", blocking=g.blocking))
                continue
            record(_run_gate(root, g, python, files, cache, toolchain))

    gate_thread = threading.Thread(target=gates_job, daemon=True)
    gate_thread.start()

    tests_info: dict = {"selected": 0, "total_files": 0, "cached": 0, "ran": 0, "failed": [], "full_reason": "",
                        "untested": [], "direct": []}
    if cfg.test_cmd and (not only or "tests" in only):
        tg = time.monotonic()
        graph = impact.build(root, files, cfg, cache)
        timings["graph"] = round(time.monotonic() - tg, 3)
        sel = impact.select(graph, changed, cfg)
        if full and not sel.full_reason:
            sel = impact.Selection(list(graph.tests), sel.direct, full_reason="--full", untested=sel.untested,
                                   distance=sel.distance)
        extra = [tree] if test_cache_scope == "tree" else []
        keys = {t: impact.test_key(graph, t, cfg, toolchain, extra) for t in sel.tests}
        to_run, cached = [], []
        for t in sel.tests:
            (cached if cache.get(keys[t]) else to_run).append(t)
        near = {t for t in to_run if sel.distance.get(t, 99) <= 1}
        tests_info.update(selected=len(sel.tests), total_files=len(graph.tests), cached=len(cached),
                          ran=len(to_run), full_reason=sel.full_reason, untested=sel.untested, direct=sel.direct,
                          near=len(near))
        emit("selection", tests_info, time.monotonic() - t0)
        durations = testrun.Durations(state / "durations.json")
        file_results: list[testrun.FileResult] = []

        def on_result(r: testrun.FileResult):
            with lock:
                file_results.append(r)
                timings.setdefault("first_test", round(time.monotonic() - t0, 3))
                timings.setdefault("first_signal", round(time.monotonic() - t0, 3))
                near.discard(r.path)
                if not near:            # the changed tests and their direct importers have all answered
                    timings.setdefault("near_done", round(time.monotonic() - t0, 3))
            if r.status == "pass":
                cache.put(keys[r.path], {"tests": r.tests, "seconds": r.seconds})
            emit("test", r, time.monotonic() - t0)

        if to_run:
            testrun.run_files(root, to_run, cfg.test_cmd, python, cfg.test_env, jobs=jobs, durations=durations,
                              priority=sel.distance, on_result=on_result, fail_fast=fail_fast)
            durations.save()
        timings["tests_done"] = round(time.monotonic() - t0, 3)
        bad = [r for r in file_results if r.status != "pass"]
        tests_info["failed"] = [{"file": r.path, "status": r.status, "failures": r.failures, "output": r.output[-3000:]}
                                for r in bad]
        tests_info["tests_run"] = sum(r.tests for r in file_results)
        status = checks.FAIL if bad else checks.PASS
        skipped = len(to_run) - len(file_results)
        tests_info["not_run"] = skipped
        summary = (f"{len(sel.tests)}/{len(graph.tests)} test files selected"
                   + (f" ({sel.full_reason})" if sel.full_reason else "")
                   + f", {len(cached)} cached, {len(file_results)} ran, {len(bad)} failed"
                   + (f", {skipped} not run (fail fast)" if skipped else ""))
        record(checks.CheckResult("tests", status, summary,
                                  [checks.finding(r.path, 0, "test", "; ".join(r.failures[:3]) or r.status)
                                   for r in bad]))
    elif not only or "tests" in only:
        record(checks.CheckResult("tests", checks.SKIP, "no [tests] in metallic.toml"))

    gate_thread.join()
    if ai_review:
        r = review.review(gitutil.git(["diff", "--no-color", base_tree, tree], root))
        record(r)
    timings["total"] = round(time.monotonic() - t0, 3)
    red = [r.name for r in results if r.status == checks.FAIL and r.blocking]
    report = {
        "kind": "check", "project": cfg.name, "runner": os.environ.get("METALLIC_RUNNER", "local"), "branch": branch,
        "base": base_sha, "tree": tree, "started": started, "changed": len(changed), "verdict": "red" if red else "green", "red": red,
        "timings": timings, "tests": tests_info, "checks": [asdict(r) for r in results],
        "cache": {"hits": cache.hits, "misses": cache.misses,
                  "hit_rate": round(cache.hits / max(1, cache.hits + cache.misses), 3)},
    }
    return report


def save_report(root: Path, report: dict) -> Path:
    runs = gitutil.state_dir(root) / "runs"
    runs.mkdir(exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = runs / f"{report['kind']}-{stamp}.json"
    path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return path
