"""Litha works on several PRs at once (litha.pr_fixer.main / pool): fake fix/resolve functions, real pool, real
tried.json and fixes.jsonl handling. What must hold: no PR handled twice, one CI rerun per run, the state files stay
consistent, the worker count is capped."""
from __future__ import annotations

import json
import random
import threading
import time

import pytest

import litha.pr_fixer as F
from litha import pr_merger, rust_fix


class Probe:
    def __init__(self):
        self.lock = threading.Lock()
        self.now = self.peak = 0
        self.handled: list[int] = []
        self.reruns: list[str] = []

    def enter(self, number: int) -> None:
        with self.lock:
            self.handled.append(number)
            self.now += 1
            self.peak = max(self.peak, self.now)

    def leave(self) -> None:
        with self.lock:
            self.now -= 1


def pr(n: int, mergeable: str = "MERGEABLE") -> dict:
    return {"number": n, "headRefOid": f"sha{n}", "baseRefName": F.BASE, "mergeable": mergeable,
            "headRefName": f"feature/{n}", "isDraft": False, "title": f"PR {n}"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    probe = Probe()
    monkeypatch.setattr(F, "STATE", tmp_path / "tried.json")
    monkeypatch.setattr(F, "LOG", tmp_path / "fixes.jsonl")
    monkeypatch.setattr(pr_merger, "HUNTED", tmp_path / "hunted.json")
    monkeypatch.setattr(F, "head_checks", lambda sha: [{"conclusion": "FAILURE", "status": "completed"}])

    def gh(*args, **_):
        if args[0] == "api":
            return json.dumps({"check_runs": [{"conclusion": "failure",
                                               "details_url": f"https://x/actions/runs/{args[1].split('/')[-2][3:]}/job/1"}]})
        if args[:2] == ("run", "rerun"):
            with probe.lock:
                probe.reruns.append(args[2])
        return ""
    monkeypatch.setattr(F, "gh", gh)
    return probe


def fake_fix(probe: Probe, rerun_every: int = 3, seconds: float = 0.03):
    """Every rerun_every-th PR needs a CI rerun (expired logs), the rest are worked on and fixed or failed."""
    def fix(p, python, dry=False, asker=None, found=None):
        probe.enter(p["number"])
        try:
            time.sleep(seconds * random.uniform(0.5, 1.5))
            if p["number"] % rerun_every == 0:
                n = F.rerun_failed(p["headRefOid"], p["number"])
                return {"pr": p["number"], "result": "rerun", "why": f"failed logs expired; reran {n} run(s)"}
            return {"pr": p["number"], "result": "fixed" if p["number"] % 2 else "failed", "why": "x" * 3000}
        finally:
            probe.leave()
    return fix


def rows(world_log) -> list[dict]:
    return [json.loads(line) for line in world_log.read_text(encoding="utf-8").splitlines()]


def test_parallel_run_handles_each_pr_once_with_one_rerun_and_consistent_state(world, monkeypatch):
    prs = [pr(n) for n in range(1, 25)] + [pr(30, "CONFLICTING"), pr(31, "CONFLICTING")]
    monkeypatch.setattr(F, "open_prs", lambda number=None: prs)
    monkeypatch.setattr(F, "fix", fake_fix(world))

    def resolve(p, python, dry=False, asker=None):
        world.enter(p["number"])
        time.sleep(0.03)
        world.leave()
        return {"pr": p["number"], "result": "fixed", "kind": "merge"}
    monkeypatch.setattr(F, "resolve", resolve)
    assert F.main(["--workers", "4", "--max", "12"]) == 0

    assert len(world.handled) == len(set(world.handled))                 # no PR twice
    assert 1 < world.peak <= 4                                           # really parallel, never above the cap
    assert len(world.reruns) == 1                                        # one CI runner: one rerun per run
    log = rows(F.LOG)                                                    # every line whole JSON: no interleaving
    assert len(log) == len({r["pr"] for r in log})
    assert sum(r["result"] == "rerun" for r in log) == 1
    assert len(log) <= 12                                                # --max still caps the run
    tried = json.loads(F.STATE.read_text(encoding="utf-8"))
    assert tried == {str(r["pr"]): f"sha{r['pr']}" for r in log if r["result"] != "rerun"}
    deferred = {n for n in world.handled if n % 3 == 0} - {r["pr"] for r in log}
    assert deferred and not deferred & {int(k) for k in tried}           # a deferred PR stays for the next run
    assert F.RERUNS.left is None                                         # the cap is per run, not left behind


def test_the_next_run_gets_the_deferred_rerun(world, monkeypatch):
    prs = [pr(3), pr(6), pr(9)]
    monkeypatch.setattr(F, "open_prs", lambda number=None: prs)
    monkeypatch.setattr(F, "fix", fake_fix(world))
    F.main(["--workers", "3", "--max", "3"])
    assert len(world.reruns) == 1
    F.main(["--workers", "3", "--max", "3"])                             # reruns are not marked: looked at again
    assert len(world.reruns) == 2


def test_one_worker_is_the_old_serial_loop(world, monkeypatch):
    prs = [pr(n) for n in range(1, 8)]
    monkeypatch.setattr(F, "open_prs", lambda number=None: prs)
    fix = fake_fix(world, rerun_every=100, seconds=0.001)

    def skipping(p, python, dry=False, asker=None, found=None):          # a skip does not use up the run's PR
        return {"pr": p["number"], "result": "skip", "why": "-"} if p["number"] < 3 else fix(p, python, dry)
    monkeypatch.setattr(F, "fix", skipping)
    monkeypatch.setattr(rust_fix, "away", lambda minutes=10: False)
    F.main([])                                                           # owner at the PC: 1 worker, 1 PR
    assert world.peak == 1 and world.handled == [3]
    assert [r["pr"] for r in rows(F.LOG)] == [1, 2, 3]


def test_workers_follow_the_owner(monkeypatch):
    monkeypatch.setattr(rust_fix, "away", lambda minutes=10: True)
    assert F.workers() == F.WORKERS_AWAY == 3
    monkeypatch.setattr(rust_fix, "away", lambda minutes=10: False)
    assert F.workers() == F.WORKERS_ACTIVE == 1


def test_a_hunted_pr_is_not_worked_on_twice(world, monkeypatch):
    prs = [pr(5), pr(7)]
    monkeypatch.setattr(F, "open_prs", lambda number=None: prs)
    pr_merger.HUNTED.write_text(json.dumps({"5": {"head": "sha5", "test": "def test_x(): assert 0\n"},
                                            "7": {"head": "old", "test": "t"}}), encoding="utf-8")
    monkeypatch.setattr(F, "fix", fake_fix(world, rerun_every=100))
    F.main(["--workers", "3", "--max", "5"])
    assert sorted(world.handled) == [5, 7]
    assert json.loads(pr_merger.HUNTED.read_text(encoding="utf-8")) == {}
    assert {r["pr"]: r.get("kind") for r in rows(F.LOG)} == {5: "hunted", 7: None}


def test_marks_from_many_threads_all_land(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "STATE", tmp_path / "tried.json")
    F.STATE.write_text(json.dumps({"requeued": "keep"}), encoding="utf-8")
    threads = [threading.Thread(target=F.mark, args=(f"k{i}", f"s{i}")) for i in range(40)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    tried = json.loads(F.STATE.read_text(encoding="utf-8"))
    assert tried == {"requeued": "keep", **{f"k{i}": f"s{i}" for i in range(40)}}
    assert not list(tmp_path.glob("*.tmp")) and not (tmp_path / "tried.lock").exists()


def test_a_rerun_that_restarted_nothing_gives_the_runner_back(world, monkeypatch):
    monkeypatch.setattr(F, "gh", lambda *a, **k: json.dumps({"check_runs": []}))
    F.RERUNS.set(1)
    try:
        assert F.rerun_failed("sha") == 0
        assert F.RERUNS.left == 1
    finally:
        F.RERUNS.set(None)


def test_cargo_runs_one_build_at_a_time(tmp_path, monkeypatch):
    probe = Probe()

    def run(cmd, **_):
        probe.enter(0)
        time.sleep(0.05)
        probe.leave()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    monkeypatch.setattr(rust_fix.subprocess, "run", run)
    monkeypatch.setattr(F.subprocess, "run", run)
    jobs = [lambda: rust_fix.run(tmp_path, ["build"]) for _ in range(3)] + \
        [lambda: F.sh(["C:/x/.cargo/bin/cargo.exe", "metadata"]) for _ in range(2)]
    threads = [threading.Thread(target=j) for j in jobs]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert probe.peak == 1 and len(probe.handled) == 5


def test_other_repos_resolve_in_parallel_under_their_own_repo(world, tmp_path, monkeypatch):
    clone = tmp_path / "studio"
    (clone / ".git").mkdir(parents=True)
    repos = tmp_path / "repos.json"
    repos.write_text(json.dumps({"repos": [{"repo": "home"}, {"repo": "o/studio", "clone": str(clone),
                                                              "mode": "merge"}]}), encoding="utf-8")
    monkeypatch.setattr(pr_merger, "REPOS", repos)
    monkeypatch.setattr(rust_fix, "away", lambda minutes=10: False)
    monkeypatch.setattr(F, "open_prs", lambda number=None: [pr(n, "CONFLICTING") for n in range(1, 6)])
    seen = []

    def resolve(p, python, dry=False, asker=None):
        world.enter(p["number"])
        seen.append(F.REPO)
        time.sleep(0.05)
        world.leave()
        return {"pr": p["number"], "result": "fixed", "kind": "merge"}
    monkeypatch.setattr(F, "resolve", resolve)
    home = F.REPO
    F.main(["--others", "3", "--workers", "3"])
    assert sorted(world.handled) == [1, 2, 3] and world.peak == 3       # --others N still caps; 3 at once
    assert seen == ["o/studio"] * 3 and F.REPO == home
    assert set(json.loads(F.STATE.read_text(encoding="utf-8"))) == {"o/studio#1", "o/studio#2", "o/studio#3"}
    assert {r["repo"] for r in rows(F.LOG)} == {"o/studio"}
