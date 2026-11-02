"""Dry simulation of Litha's PR worker pool: the real pr_fixer.main / others loop, fake work that sleeps for the
durations her own log recorded (~/.star/pr-fixer/fixes.jsonl "seconds"), scaled down. Nothing touches GitHub, git,
cargo or her model; her real tried.json and log are not touched either.

    python -m litha.pr_pool_sim [--scale 0.005]

It drains the logged backlog run after run (one run every 10 min; a run longer than 10 min makes the next ones
skip, as the scheduled task does) and prints, per configuration: runs needed, simulated hours, run wall times."""
from __future__ import annotations

import argparse
from contextlib import nullcontext, redirect_stdout
import io
import json
import math
from pathlib import Path
import statistics
import tempfile
import threading
import time

from litha import pr_fixer as F
from litha import pr_merger, rust_fix

TICK = 600                                    # the scheduled task's interval, s


def backlog(log: Path) -> tuple[list[dict], list[dict]]:
    """(STAR rows, other-repo rows) with a duration. The 2026-11-01 loop of "reran 0 run(s)" rows on #700 is left out:
    that bug is fixed (such a PR is a skip now and marked tried)."""
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [r for r in rows if isinstance(r.get("seconds"), (int, float))
            and not (r.get("result") == "rerun" and "reran 0" in str(r.get("why", "")))]
    return [r for r in rows if "repo" not in r], [r for r in rows if "repo" in r]


class Sim:
    def __init__(self, items: list[dict], scale: float):
        self.left = {i + 1: r for i, r in enumerate(items)}
        self.scale, self.lock = scale, threading.Lock()
        self.now = self.peak = self.reruns = 0

    def pr(self, n: int, base: str) -> dict:
        r = self.left[n]
        merge = r.get("kind") == "merge" or ("repo" in r and r.get("result") == "failed" and not r.get("kind"))
        return {"number": n, "headRefOid": f"s{n}", "baseRefName": base, "isDraft": False, "headRefName": f"f/{n}",
                "mergeable": "CONFLICTING" if merge else "MERGEABLE", "title": "sim"}

    def work(self, n: int, rerun: bool, build: bool = False) -> dict:
        r = self.left[n]
        with self.lock:
            self.now += 1
            self.peak = max(self.peak, self.now)
        try:
            with rust_fix.BUILD if build else nullcontext():     # a Rust repair is cargo-bound end to end
                time.sleep(r["seconds"] * self.scale)
            if rerun:
                F.rerun_failed(f"s{n}", n)                         # RerunSpent: the PR stays for the next run
                with self.lock:
                    self.reruns += 1
        finally:
            with self.lock:
                self.now -= 1
        with self.lock:
            self.left.pop(n, None)
        return {k: v for k, v in r.items() if k not in ("ts", "seconds", "repo")}


def drain(items: list[dict], argv: list[str], scale: float, home: bool) -> dict:
    sim = Sim(items, scale)
    saved = {k: getattr(F, k) for k in ("STATE", "LOG", "open_prs", "head_checks", "fix", "resolve", "fix_rust",
                                        "failed_logs", "gh")}
    saved_rf = (rust_fix.away, rust_fix.checks, rust_fix.errors, pr_merger.REPOS, pr_merger.HUNTED)
    tmp = Path(tempfile.mkdtemp(prefix="litha-sim-"))
    (tmp / "clone" / ".git").mkdir(parents=True)
    (tmp / "repos.json").write_text(json.dumps({"repos": [{"repo": "home"}, {"repo": "sim/other", "mode": "merge",
                                                                             "clone": str(tmp / "clone")}]}))
    F.STATE, F.LOG = tmp / "tried.json", tmp / "fixes.jsonl"
    pr_merger.REPOS, pr_merger.HUNTED = tmp / "repos.json", tmp / "hunted.json"
    F.open_prs = lambda number=None: [sim.pr(n, F.BASE) for n in sorted(sim.left)]
    F.head_checks = lambda sha: [{"conclusion": "FAILURE", "status": "completed"}]

    def gh(*a, **_):
        if a[0] == "api":                                         # repos/<repo>/commits/s<n>/check-runs
            return json.dumps({"check_runs": [{"conclusion": "failure",
                                               "details_url": f"/runs/{a[1].split('/')[-2][1:]}/"}]})
        if a[:2] == ("run", "rerun"):                             # others() reruns inline, without fix()
            with sim.lock:
                sim.left.pop(int(a[2]), None)
        return ""
    F.gh = gh
    F.fix = lambda pr, python, dry=False, asker=None, found=None: sim.work(
        pr["number"], sim.left[pr["number"]]["result"] in ("rerun", "flaky-rerun"))
    F.resolve = lambda pr, python, dry=False, asker=None: sim.work(pr["number"], False)
    F.fix_rust = lambda pr, log, dry=False, asker=None: sim.work(pr["number"], False, build=True)
    F.failed_logs = lambda sha: "RUST" if sim.left[int(sha[1:])].get("kind") == "rust" else "FLAKY"
    rust_fix.away = lambda minutes=10: True                       # the night case: the owner is away
    rust_fix.checks = lambda log: [["build"]] if log == "RUST" else []
    rust_fix.errors = lambda log, limit=4: [{"error": "e"}] if log == "RUST" else []
    walls: list[float] = []
    most = 0
    try:
        while sim.left and len(walls) < 500:
            before, reran = len(sim.left), sim.reruns
            t = time.perf_counter()
            with redirect_stdout(io.StringIO()):
                F.main(argv)
            walls.append((time.perf_counter() - t) / scale)
            most = max(most, sim.reruns - reran)
            if len(sim.left) == before and not home:              # others: the rest are not candidates (e.g. rust>2)
                break
    finally:
        for k, v in saved.items():
            setattr(F, k, v)
        rust_fix.away, rust_fix.checks, rust_fix.errors, pr_merger.REPOS, pr_merger.HUNTED = saved_rf
    slots = sum(max(1, math.ceil(w / TICK)) for w in walls)       # a run past 10 min makes the next start(s) skip
    return {"prs": len(items) - len(sim.left), "runs": len(walls), "hours": round(slots * TICK / 3600, 1),
            "mean_run_s": round(statistics.mean(walls)), "max_run_s": round(max(walls)), "peak_workers": sim.peak,
            "max_reruns_per_run": most}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m litha.pr_pool_sim")
    ap.add_argument("--log", type=Path, default=F.LOG)
    ap.add_argument("--scale", type=float, default=0.005, help="simulated seconds per logged second")
    a = ap.parse_args(argv)
    star, other = backlog(a.log)
    out = {"star_rows": len(star), "other_rows": len(other), "scale": a.scale, "star": {}, "other": {}}
    for name, args in (("serial (today: 1 worker, 1 PR/run)", ["--workers", "1", "--max", "1"]),
                       ("3 workers, 3 PRs/run", ["--workers", "3"]), ("4 workers, 4 PRs/run", ["--workers", "4"])):
        out["star"][name] = drain(star, args, a.scale, True)
    for name, args in (("serial (today)", ["--others", "2", "--workers", "1"]),
                       ("3 workers", ["--others", "2", "--workers", "3"]),
                       ("3 workers, --others 3", ["--others", "3", "--workers", "3"])):
        out["other"][name] = drain(other, args, a.scale, False)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
