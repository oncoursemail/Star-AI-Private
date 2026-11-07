"""Litha's deploy lane: the live checkout follows a green star/next (litha.self_update), the merger's gates run
cheapest first with fewer gh calls (same action as before), one CI rerun per head, run.log step lines."""
from __future__ import annotations

import itertools
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import litha.pr_fixer as F
import litha.pr_merger as M
from litha import self_update as U

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------- pr_merger.decide: same action, fewer calls

CLEAN = "diff --git a/star/a.py b/star/a.py\n--- a/star/a.py\n+++ b/star/a.py\n@@ -1,1 +1,2 @@\n x = 1\n+y = 2\n"
LOCK = "diff --git a/pnpm-lock.yaml b/pnpm-lock.yaml\n@@ -0,0 +1 @@\n+lock\n"
GOOD = {"number": 7, "title": "t", "isDraft": False, "baseRefName": "star/next", "baseRefOid": "b1",
        "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN", "headRefOid": "h1"}
LISTS = {"good": {}, "draft": {"isDraft": True}, "main": {"baseRefName": "main"},
         "dirty": {"mergeable": "CONFLICTING", "mergeStateStatus": "DIRTY"}, "no-base-sha": {"baseRefOid": None}}
CHECKS = {"none": [], "pass": [{"name": "ci", "status": "completed", "conclusion": "SUCCESS"}],
          "fail": [{"name": "ci", "status": "completed", "conclusion": "FAILURE"}],
          "running": [{"name": "ci", "status": "in_progress", "conclusion": ""}],
          "skipped": [{"name": "ci", "status": "completed", "conclusion": "SKIPPED"}]}
DIFFS = {"clean": CLEAN, "lock": CLEAN + LOCK}


def old_decide(pr, review_verdict, checks, diff, hunt_blocks):
    """The decide() before this change: diff and checks always fetched, then every gate at once."""
    files = M.parse_diff(diff)
    gates = M.gate_failures(pr, checks, files)
    verdict = review_verdict if not gates else None
    if verdict == "merge" and hunt_blocks:
        verdict = "hold"
    return "merge" if not gates and verdict == "merge" else "hold"


@pytest.fixture
def merger(tmp_path, monkeypatch):
    """gh and her model replaced by counters: (calls, set_review, set_diff)."""
    calls = {"checks": 0, "diff": 0, "review": 0}
    state = {"verdict": "merge", "diff": CLEAN, "checks": CHECKS["pass"]}

    def gh(*args, **kw):
        assert args[:2] == ("pr", "diff"), args
        calls["diff"] += 1
        return state["diff"]

    def review(pr, files, ask):
        calls["review"] += 1
        high = [{"file": "star/a.py", "line": 2, "severity": "high", "why": "breaks"}] if state["verdict"] == "hold" else []
        return {"verdict": state["verdict"], "risks": high, "not_json": 0, "summary": "stub"}

    def checks(sha):
        calls["checks"] += 1
        return state["checks"]

    monkeypatch.setattr(M, "gh", gh)
    monkeypatch.setattr(M, "review", review)
    monkeypatch.setattr(M, "REVIEWS", tmp_path / "reviews.json")
    monkeypatch.setattr(M, "DIFF_GATES", tmp_path / "diff_gates.json")
    return calls, state, checks


def test_decide_takes_the_same_action_as_the_full_gate_list_over_every_combination(merger, tmp_path):
    calls, state, checks = merger
    n = 0
    for (lk, lv), (ck, cv), (dk, dv), verdict, hunt_blocks, use_hunt in itertools.product(
            LISTS.items(), CHECKS.items(), DIFFS.items(), ("merge", "hold"), (False, True), (False, True)):
        if hunt_blocks and not use_hunt:
            continue
        n += 1
        pr = {**GOOD, **lv, "number": n, "headRefOid": f"h{n}"}
        state.update(verdict=verdict, diff=dv, checks=cv)

        def hunt(pr, files, rev, blocks=hunt_blocks):
            assert files, "the hunt always gets the real diff"
            if blocks:
                rev["risks"].append({"file": "star/a.py", "line": 2, "severity": "high", "why": "hunt: bug"})
                rev["verdict"] = "hold"

        want = old_decide(pr, verdict, cv, dv, hunt_blocks)
        for run in ("first", "again"):                      # "again": the memo and the review cache are warm
            before = dict(calls)
            row = M.decide(pr, checks_fn=checks, prove_fn=None, hunt_fn=hunt if use_hunt else None)
            assert row["action"] == want, (lk, ck, dk, verdict, hunt_blocks, use_hunt, run, row)
            spent = {k: calls[k] - before[k] for k in calls}
            if lk != "good" and lk != "no-base-sha":
                assert spent == {"checks": 0, "diff": 0, "review": 0}       # list data alone: no gh call at all
            elif ck != "pass":
                assert spent["diff"] == 0 and spent["review"] == 0           # the checks block: no diff fetched
            elif run == "again" and lk == "good" and (dk == "lock" or not use_hunt):
                assert spent["diff"] == 0 and spent["review"] == 0           # same head and base within 6 h
            else:
                assert spent["diff"] == 1
    assert n == 5 * 5 * 2 * 2 * 3


def test_a_review_that_expired_meanwhile_fetches_the_diff_again(merger):
    calls, state, checks = merger
    M.decide(GOOD, checks_fn=checks, prove_fn=None, hunt_fn=None)
    M.REVIEWS.unlink()                                       # the review left the cache: it needs the real diff
    row = M.decide(GOOD, checks_fn=checks, prove_fn=None, hunt_fn=None)
    assert calls["diff"] == 2 and calls["review"] == 2 and row["action"] == "merge" and row["files"] == 1


def test_the_diff_memo_is_per_base_and_expires(merger, monkeypatch):
    calls, state, checks = merger
    state["diff"] = CLEAN + LOCK
    assert M.decide(GOOD, checks_fn=checks, prove_fn=None, hunt_fn=None)["reasons"] == ["forbidden file pnpm-lock.yaml"]
    row = M.decide(GOOD, checks_fn=checks, prove_fn=None, hunt_fn=None)
    assert calls["diff"] == 1 and row["reasons"] == ["forbidden file pnpm-lock.yaml"] and "skipped" in row
    M.decide({**GOOD, "baseRefOid": "b2"}, checks_fn=checks, prove_fn=None, hunt_fn=None)   # the base moved
    assert calls["diff"] == 2
    monkeypatch.setattr(M, "DIFF_TTL", -1)                   # stamps are rounded: 0 can still look fresh
    M.decide(GOOD, checks_fn=checks, prove_fn=None, hunt_fn=None)
    assert calls["diff"] == 3


def test_each_gh_call_is_counted_and_each_run_prints_the_count(monkeypatch, capsys, tmp_path):
    M.GH_CALLS.clear()

    class Done:
        returncode, stderr = 0, ""
        stdout = json.dumps([{**GOOD, "isDraft": True}])

    monkeypatch.setattr(M.subprocess, "run", lambda *a, **k: Done())
    monkeypatch.setattr(M, "LOG", tmp_path / "decisions.jsonl")
    assert M.main([]) == 0
    assert M.GH_CALLS == {"pr list": 1}                      # a draft: decided from the list alone
    assert "gh calls: 1 {'pr list': 1}" in capsys.readouterr().out
    M.GH_CALLS.clear()


# ---------------------------------------------------------------- pr_fixer: one CI rerun per head

RUNS = [{"name": "ci", "status": "completed", "conclusion": "failure", "started_at": "2026-10-27T12:00:00Z",
         "details_url": "https://x/actions/runs/1/job/11"},
        {"name": "ci", "status": "completed", "conclusion": "failure", "started_at": "2026-11-01T09:00:00Z",
         "details_url": "https://x/actions/runs/2/job/22"},
        {"name": "lint", "status": "completed", "conclusion": "success", "started_at": "2026-11-01T09:00:00Z",
         "details_url": "https://x/actions/runs/3/job/33"}]


def test_a_head_gets_one_ci_rerun_ever_of_its_newest_failed_run(monkeypatch, tmp_path):
    asked = []

    def gh(*args, **kw):
        asked.append(args)
        return json.dumps({"check_runs": RUNS}) if args[0] == "api" else ""

    monkeypatch.setattr(F, "gh", gh)
    monkeypatch.setattr(F, "RERAN", tmp_path / "reran.json")
    F.RERUNS.set(None)
    assert F.rerun_failed("abc", 700) == 1
    assert [a for a in asked if a[0] == "run"] == [("run", "rerun", "2", "--failed", "--repo", F.REPO)]  # newest only
    assert list(json.loads((tmp_path / "reran.json").read_text(encoding="utf-8"))) == [f"{F.REPO}@abc"]
    asked.clear()
    assert F.rerun_failed("abc", 700) == 0 and asked == []                # a later run: no gh call, no rerun
    assert F.reran("abc") and not F.reran("def")
    F.RERUNS.set(1)                                                       # main()'s per-run budget is untouched
    assert F.rerun_failed("abc", 700) == 0 and F.RERUNS.take()
    F.RERUNS.set(None)


def test_expired_logs_on_a_head_that_had_its_rerun_are_a_skip(monkeypatch, tmp_path):
    monkeypatch.setattr(F, "RERAN", tmp_path / "reran.json")
    (tmp_path / "reran.json").write_text(json.dumps({f"{F.REPO}@abc": 1}), encoding="utf-8")
    monkeypatch.setattr(F, "failed_logs", lambda sha: "")
    monkeypatch.setattr(F, "rerun_failed", lambda *a: pytest.fail("this head already had its one rerun"))
    row = F.fix({"headRefOid": "abc", "number": 700, "headRefName": "x"}, "python")
    assert row["result"] == "skip" and "one CI rerun" in row["why"]


def test_a_broken_reran_file_counts_as_empty_and_is_rewritten(monkeypatch, tmp_path):
    monkeypatch.setattr(F, "RERAN", tmp_path / "reran.json")
    (tmp_path / "reran.json").write_text("{not json", encoding="utf-8")
    assert not F.reran("abc")
    F._note_rerun("abc")
    assert F.reran("abc")


# ---------------------------------------------------------------- self_update

def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


def commit(repo, path, text, msg="c"):
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text, encoding="utf-8")
    git(repo, "add", path)
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def live(tmp_path):
    """(origin work clone, live checkout on star/next, home): the live one is a clone at the same head."""
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "star/next")
    commit(origin, "litha/pr_merger_run.cmd", "@echo off\n")
    commit(origin, "litha/a.py", "X = 1\n")
    bare = tmp_path / "bare.git"
    git(tmp_path, "clone", "-q", "--bare", str(origin), str(bare))
    git(origin, "remote", "add", "origin", str(bare))
    git(tmp_path, "clone", "-q", "-b", "star/next", str(bare), str(tmp_path / "live"))
    home = tmp_path / "home"
    home.mkdir()
    return origin, tmp_path / "live", home


def push(origin, path, text):
    sha = commit(origin, path, text)
    git(origin, "push", "-q", "origin", "star/next")
    return sha


PASS = lambda sha: CHECKS["pass"]  # noqa: E731


def run(live_dir, home, **kw):
    kw = {"checks_fn": PASS, "bench_fn": lambda: "", "health_fn": lambda root, py: "", **kw}
    return U.update(live_dir, sys.executable, home=home, **kw)


def test_the_live_checkout_fast_forwards_to_a_green_star_next(live):
    origin, live_dir, home = live
    assert run(live_dir, home).startswith("up to date")
    new = push(origin, "litha/a.py", "X = 2\n")
    asked = []
    line = run(live_dir, home, checks_fn=lambda sha: asked.append(sha) or CHECKS["pass"])
    assert "updated" in line and asked == [new]
    assert git(live_dir, "rev-parse", "HEAD") == new and (live_dir / "litha" / "a.py").read_text() == "X = 2\n"


@pytest.mark.parametrize("why, kw, expect", [
    ("checks", {"checks_fn": lambda sha: CHECKS["fail"]}, "not every check passed"),
    ("running", {"checks_fn": lambda sha: CHECKS["running"]}, "not every check passed"),
    ("bench", {"bench_fn": lambda: "a litha.bug_bench process is running"}, "bug_bench process is running"),
])
def test_no_update_unless_every_condition_holds(live, why, kw, expect):
    origin, live_dir, home = live
    old = git(live_dir, "rev-parse", "HEAD")
    push(origin, "litha/a.py", "X = 2\n")
    assert expect in run(live_dir, home, **kw)
    assert git(live_dir, "rev-parse", "HEAD") == old


def test_no_update_when_off_dirty_or_not_descending(live):
    origin, live_dir, home = live
    old = git(live_dir, "rev-parse", "HEAD")
    push(origin, "litha/a.py", "X = 2\n")
    (home / "OFF").write_text("", encoding="utf-8")
    assert "OFF" in run(live_dir, home)
    (home / "OFF").unlink()
    (live_dir / "litha" / "a.py").write_text("X = 9\n", encoding="utf-8")
    assert "uncommitted" in run(live_dir, home)
    git(live_dir, "checkout", "-q", "--", ".")
    commit(live_dir, "litha/b.py", "Y = 1\n")                  # a local commit star/next does not have
    assert "does not descend" in run(live_dir, home)
    git(live_dir, "reset", "-q", "--hard", old)
    assert "updated" in run(live_dir, home)


def test_not_on_star_next_does_nothing_but_a_detached_ancestor_follows(live):
    origin, live_dir, home = live
    git(live_dir, "checkout", "-q", "-b", "star/litha-claude-20261102")
    push(origin, "litha/a.py", "X = 2\n")
    old = git(live_dir, "rev-parse", "HEAD")
    line = run(live_dir, home, checks_fn=lambda sha: pytest.fail("no gh call off star/next"))
    assert line.startswith("not on star/next, skipped") and git(live_dir, "rev-parse", "HEAD") == old
    git(live_dir, "checkout", "-q", "--detach", old)
    assert "updated" in run(live_dir, home)
    assert git(live_dir, "rev-parse", "HEAD") == git(origin, "rev-parse", "HEAD")


def test_a_failed_self_check_rolls_back_and_that_head_is_not_tried_again(live):
    origin, live_dir, home = live
    old = git(live_dir, "rev-parse", "HEAD")
    new = push(origin, "litha/a.py", "X = (\n")
    line = run(live_dir, home, health_fn=U.healthy)
    assert "self-check failed" in line and f"rolled back to {old[:9]}" in line
    assert git(live_dir, "rev-parse", "HEAD") == old and (live_dir / "litha" / "a.py").read_text() == "X = 1\n"
    assert new in json.loads((home / U.BAD).read_text(encoding="utf-8"))
    assert "failed its self-check before" in run(live_dir, home)


def test_a_canary_that_gets_through_the_new_code_rolls_the_update_back(live):
    origin, live_dir, home = live
    old = git(live_dir, "rev-parse", "HEAD")
    new = push(origin, "litha/a.py", "X = 2\n")
    seen = []
    line = run(live_dir, home, canary_fn=lambda root, py: seen.append(root) or "canary gate failed: PASSED pr-x")
    assert "canary gate failed" in line and f"rolled back to {old[:9]}" in line and seen == [live_dir]
    assert git(live_dir, "rev-parse", "HEAD") == old and new in json.loads((home / U.BAD).read_text(encoding="utf-8"))
    assert "failed its self-check before" in run(live_dir, home, canary_fn=lambda root, py: "")


def test_main_runs_the_canary_gate(monkeypatch):
    got = {}
    monkeypatch.setattr(U, "update", lambda **kw: got.update(kw) or "")
    assert U.main([]) == 0 and got["canary_fn"] is U.canary_gate


def test_the_self_check_imports_every_module_the_run_script_starts(tmp_path):
    (tmp_path / "litha").mkdir()
    (tmp_path / "litha" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "litha" / "ok.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "litha" / "pr_merger_run.cmd").write_text('"%~1" -m litha.ok\n"%~1" -m litha.gone\n', encoding="utf-8")
    assert U.modules(tmp_path) == ["litha.ok", "litha.gone"]
    assert "No module named 'litha.gone'" in U.healthy(tmp_path, sys.executable)
    (tmp_path / "litha" / "gone.py").write_text("", encoding="utf-8")
    assert U.healthy(tmp_path, sys.executable) == ""


def test_a_change_to_the_run_script_waits_for_its_last_line(live):
    origin, live_dir, home = live
    old = git(live_dir, "rev-parse", "HEAD")
    new = push(origin, "litha/pr_merger_run.cmd", "@echo off\necho new\n")
    assert run(live_dir, home, last=True) == ""                 # nothing pending: the last line costs nothing
    assert "left for the script's last line" in run(live_dir, home)
    assert git(live_dir, "rev-parse", "HEAD") == old and (home / U.PENDING).exists()
    assert "updated" in run(live_dir, home, last=True)
    assert git(live_dir, "rev-parse", "HEAD") == new and not (home / U.PENDING).exists()


def test_main_logs_and_never_fails_the_scheduled_run(monkeypatch, capsys):
    monkeypatch.setattr(U, "update", lambda **kw: (_ for _ in ()).throw(RuntimeError("git fetch: offline")))
    assert U.main([]) == 0
    assert capsys.readouterr().out == "self_update: error: git fetch: offline\n"


# ---------------------------------------------------------------- the run script under cmd.exe

STUB = '''import pathlib, sys
name = pathlib.Path(__file__).stem
print("stub", name, *sys.argv[1:])
if name == "self_update" and "--last" in sys.argv:
    p = pathlib.Path("litha/pr_merger_run.cmd")
    p.write_text("@echo off\\n" + "".join(f'echo GARBAGE {i} {"x" * (i * 7 % 40)}>> "%USERPROFILE%\\\\garbage.txt"\\n'
                                         for i in range(60)), encoding="utf-8")
sys.exit(3 if name == "pr_fixer" else 0)
'''


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe")
def test_the_run_script_logs_each_step_and_survives_rewriting_itself_on_its_last_line(tmp_path):
    (tmp_path / "litha").mkdir()
    (tmp_path / "litha" / "pr_merger_run.cmd").write_bytes((ROOT / "litha" / "pr_merger_run.cmd").read_bytes())
    (tmp_path / "litha" / "__init__.py").write_text("", encoding="utf-8")
    for m in ("self_update", "self_check", "pr_fixer", "pr_merger", "pr_promote", "forge_sync"):
        (tmp_path / "litha" / f"{m}.py").write_text(STUB, encoding="utf-8")
    env = {**os.environ, "USERPROFILE": str(tmp_path)}
    r = subprocess.run(["cmd", "/c", str(tmp_path / "litha" / "pr_merger_run.cmd"), sys.executable], env=env,
                       capture_output=True, text=True, timeout=120)
    log = (tmp_path / ".star" / "pr-merger" / "run.log").read_text(encoding="utf-8", errors="replace")
    assert "GARBAGE" in (tmp_path / "litha" / "pr_merger_run.cmd").read_text(encoding="utf-8")   # it was rewritten
    assert not (tmp_path / "garbage.txt").exists() and "not recognized" not in r.stderr + r.stdout + log
    lines = [ln.rstrip() for ln in log.splitlines()]               # echo keeps the space before >>
    assert lines[0].endswith(" start") and lines[1] == "stub self_update"
    assert any(ln.endswith("step pr_merger (previous rc=3)") for ln in lines)       # pr_fixer's rc, timestamped
    assert any(ln.endswith("step pr_fixer (previous rc=0)") for ln in lines)
    assert any(ln.endswith(" end rc=0") for ln in lines) and lines[-1] == "stub self_update --last"
