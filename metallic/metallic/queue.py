"""`metallic queue`: a local merge queue that tests the COMBINED state before anything lands.

For a target branch and an ordered list of branches it
1. takes the queue lock (one integrator at a time, per clone);
2. checks out the target in a scratch worktree inside the clone's state dir (the user's worktrees are never touched);
3. optimistic batch: merges every branch in order and runs the full checks once on the combined tree; green means all
   of them land together;
4. otherwise one by one: merges branch k onto the last green state, runs the full checks on that combined tree, keeps
   it only if green; a merge conflict or a red check drops the branch with the reason, and the queue moves on;
5. fast-forwards the target to the last green state only with --apply, and only if the target has not moved since
   the run started (compare-and-swap on the ref). Nothing is pushed.

The tests in the queue are the FULL suite (selection only orders them); a tree tested green before is a cache hit.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import shutil
import time

from . import cache as cache_mod
from . import engine, gitutil
from .config import fnmatch_any, load

LOCK_STALE_SECONDS = 2 * 3600


class QueueBusy(RuntimeError):
    pass


class Lock:
    def __init__(self, path: Path, holder: str):
        self.path, self.holder = path, holder

    def __enter__(self):
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            age = time.time() - self.path.stat().st_mtime
            if age < LOCK_STALE_SECONDS:
                raise QueueBusy(f"queue lock held: {self.path.read_text(encoding='utf-8', errors='replace')[:200]}")
            self.path.unlink()
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"{self.holder} pid {os.getpid()} since {dt.datetime.now(dt.timezone.utc).isoformat()}")
        return self

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def _queue_file(root: Path) -> Path:
    return gitutil.state_dir(root) / "queue.json"


def pending(root: Path) -> list[str]:
    try:
        return json.loads(_queue_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def save_pending(root: Path, branches: list[str]) -> None:
    _queue_file(root).write_text(json.dumps(branches), encoding="utf-8")


def _merge(scratch: Path, sha: str, label: str, identity: tuple[str, str]) -> list[str]:
    """Merge sha into the scratch HEAD. Returns the conflicted files ([] = merged)."""
    try:
        gitutil.git(["merge", "--no-ff", "--no-edit", "-m", f"metallic queue: merge {label}", sha], scratch,
                    identity=identity)
        return []
    except gitutil.GitError:
        conflicted = [p for p in gitutil.git(["diff", "--name-only", "--diff-filter=U"], scratch, check=False)
                      .splitlines() if p] or ["(merge failed)"]
        gitutil.git(["merge", "--abort"], scratch, check=False)
        return conflicted


def _check(scratch: Path, base: str, branch: str, jobs: int, cache: cache_mod.Cache, emit, *,
           source_branches: tuple[str, ...] = ()) -> dict:
    cfg = load(scratch)                     # the combined tree's own config: a gate added by a branch is enforced
    # A synthetic batch label must not erase generator restrictions. A mixed batch
    # can fail conservatively here; the existing individual fallback attributes each change.
    guard_branch = next((b for b in source_branches if fnmatch_any(b, cfg.generator_branches)), branch)
    head = gitutil.rev("HEAD", scratch)
    return engine.run_check(scratch, cfg, base=base, tree=gitutil.tree_of(head, scratch), branch=guard_branch, full=True,
                            jobs=jobs, cache=cache, emit=emit, test_cache_scope="tree",
                            fail_fast=True)


def run(root: Path, target: str, branches: list[str], *, apply: bool = False, jobs: int = 4,
        cache: cache_mod.Cache | None = None, emit=None, batch: bool = True) -> dict:
    emit = emit or (lambda *_: None)
    cache = cache or cache_mod.Cache(engine.default_cache_dir())
    cfg = load(root)
    state = gitutil.state_dir(root)
    t0 = time.monotonic()
    report: dict = {"kind": "queue", "project": cfg.name, "target": target,
                    "started": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "entries": [],
                    "batch": None, "applied": False}
    with Lock(state / "queue.lock", "metallic queue"):
        target_sha = gitutil.rev(target, root)
        report["target_before"] = target_sha
        shas = {b: gitutil.rev(b, root) for b in branches}
        scratch = state / f"scratch-{os.getpid()}"
        if scratch.exists():
            shutil.rmtree(scratch, ignore_errors=True)
            gitutil.git(["worktree", "prune"], root, check=False)
        gitutil.git(["worktree", "add", "--detach", "--force", str(scratch), target_sha], root)
        try:
            green = target_sha
            remaining = list(branches)
            if batch and len(branches) > 1:
                conflicts = {}
                for b in branches:
                    c = _merge(scratch, shas[b], b, cfg.queue_identity)
                    if c:
                        conflicts[b] = c
                        break
                if not conflicts:
                    emit("batch", branches, time.monotonic() - t0)
                    rep = _check(scratch, target_sha, "metallic-queue", jobs, cache, emit,
                                 source_branches=tuple(branches))
                    report["batch"] = {"branches": branches, "verdict": rep["verdict"], "red": rep["red"],
                                       "seconds": rep["timings"]["total"]}
                    if rep["verdict"] == "green":
                        green = gitutil.rev("HEAD", scratch)
                        for b in branches:
                            report["entries"].append({"branch": b, "head": shas[b], "status": "merged",
                                                      "reason": "batch green", "check": _brief(rep)})
                        remaining = []
                gitutil.git(["checkout", "--detach", "--force", green], scratch)
            for b in remaining:
                started = time.monotonic()
                conflicted = _merge(scratch, shas[b], b, cfg.queue_identity)
                if conflicted:
                    report["entries"].append({"branch": b, "head": shas[b], "status": "conflict",
                                              "reason": "conflicts with the queue state in " + ", ".join(conflicted[:10]),
                                              "seconds": round(time.monotonic() - started, 2)})
                    emit("entry", report["entries"][-1], time.monotonic() - t0)
                    continue
                rep = _check(scratch, green, b, jobs, cache, emit)
                entry = {"branch": b, "head": shas[b], "check": _brief(rep),
                         "seconds": round(time.monotonic() - started, 2)}
                if rep["verdict"] == "green":
                    green = gitutil.rev("HEAD", scratch)
                    entry.update(status="merged", reason="green on the combined tree")
                else:
                    entry.update(status="rejected", reason="red on the combined tree: " + ", ".join(rep["red"]))
                    gitutil.git(["checkout", "--detach", "--force", green], scratch)
                report["entries"].append(entry)
                emit("entry", entry, time.monotonic() - t0)
            report["result"] = green
            report["merged"] = [e["branch"] for e in report["entries"] if e["status"] == "merged"]
            if apply and green != target_sha:
                ref = target if target.startswith("refs/") else "refs/heads/" + target
                if not gitutil.ok(["show-ref", "--verify", "--quiet", ref], root):
                    report["apply_error"] = f"{target} is not a local branch; result kept as metallic/queue-result"
                    gitutil.git(["update-ref", "refs/heads/metallic/queue-result", green], root)
                elif gitutil.ok(["update-ref", ref, green, target_sha], root):
                    report["applied"] = True
                else:
                    report["apply_error"] = f"{target} moved during the run; nothing applied"
        finally:
            gitutil.git(["worktree", "remove", "--force", str(scratch)], root, check=False)
            shutil.rmtree(scratch, ignore_errors=True)
            gitutil.git(["worktree", "prune"], root, check=False)
    report["seconds"] = round(time.monotonic() - t0, 2)
    return report


def _brief(rep: dict) -> dict:
    return {"verdict": rep["verdict"], "red": rep["red"], "tree": rep["tree"], "timings": rep["timings"],
            "tests": {k: rep["tests"].get(k) for k in ("selected", "total_files", "cached", "ran", "tests_run")},
            "failed": [f["file"] for f in rep["tests"].get("failed", [])],
            "checks": [{"name": c["name"], "status": c["status"], "summary": c["summary"]} for c in rep["checks"]]}
