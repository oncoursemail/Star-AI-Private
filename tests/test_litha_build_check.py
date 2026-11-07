"""Build/test check before a decision, base faults, her own branches (section 4s). No real gh, cargo or Claude."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

import litha.build_check as B
import litha.pr_fixer as F
import litha.pr_merger as M

PY_OK = "def add(a, b):\n    return a + b\n"
TEST = "from star.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"


def _tree(tmp_path, code=PY_OK):
    (tmp_path / "star").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "star" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "star" / "calc.py").write_text(code, encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(TEST, encoding="utf-8")
    (tmp_path / "tests" / "test_other.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    return tmp_path


def test_the_plan_runs_only_what_the_diff_touches(tmp_path):
    t = _tree(tmp_path)
    (t / "tests" / "test_star_research.py").write_text("def test_q():\n    pass\n", encoding="utf-8")
    (t / "frontend" / "src").mkdir(parents=True)
    (t / "frontend" / "package.json").write_text("{}", encoding="utf-8")
    p = B.plan(t, ["star/calc.py"])
    assert p["pytest"] == ["tests/test_calc.py", "tests/test_star_research.py"]   # importer + CI's quick file
    assert not p["tsc"] and not p["cargo"]
    p = B.plan(t, ["frontend/src/SettingsPage.tsx", "docs/x.md"])
    assert p["tsc"] and p["pytest"] == [] and p["vitest"] == []
    assert B.plan(t, ["docs/x.md"]) == {"pytest": [], "tsc": False, "vitest": [], "cargo": []}
    (t / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")
    assert B.plan(t, ["crates/p/src/lib.rs"])["cargo"] == ["crates/p/src/lib.rs"]


def test_a_failing_test_is_named_and_a_passing_tree_passes(tmp_path):
    t = _tree(tmp_path, "def add(a, b):\n    return a - b\n")
    res = B.run(t, ["star/calc.py"], sys.executable)
    assert not res["ok"] and res["failed"].startswith("pytest: tests/test_calc.py::test_add")
    (t / "star" / "calc.py").write_text(PY_OK, encoding="utf-8")
    res = B.run(t, ["star/calc.py"], sys.executable)
    assert res["ok"] and res["ran"] == ["pytest tests/test_calc.py"] and res["seconds"] >= 0


def test_a_test_that_fails_only_after_another_passes_alone_and_a_real_failure_still_holds(tmp_path):
    t = _tree(tmp_path)
    flag = (t / "flag").as_posix()
    (t / "tests" / "test_a.py").write_text(f"def test_first():\n    open({flag!r}, 'w').close()\n", encoding="utf-8")
    (t / "tests" / "test_b.py").write_text(
        f"import os\n\n\ndef test_order():\n    if os.path.exists({flag!r}):\n        os.remove({flag!r})\n"
        "        raise AssertionError('state left by another test')\n", encoding="utf-8")
    res = B.run(t, [], sys.executable, steps={"pytest": ["tests/test_a.py", "tests/test_b.py"]})
    assert res["ok"] and res["ran"][-1] == "passed alone: tests/test_b.py::test_order"
    (t / "star" / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    res = B.run(t, [], sys.executable, steps={"pytest": ["tests/test_calc.py"]})
    assert not res["ok"] and res["failed"] == "pytest: tests/test_calc.py::test_add"


def test_a_check_past_its_time_box_fails(tmp_path, monkeypatch):
    def slow(*a, **k):
        raise subprocess.TimeoutExpired(a[0], 1)
    monkeypatch.setattr(F, "sh", slow)
    res = B.run(_tree(tmp_path), ["star/calc.py"], sys.executable, budget=1)
    assert not res["ok"] and "did not finish within 1 s" in res["failed"]


def test_tsc_errors_are_named_and_a_missing_npm_is_not_a_failure(tmp_path, monkeypatch):
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(B.shutil, "which", lambda name: "npm")
    monkeypatch.setattr(F, "frontend_deps", lambda tree: "")
    out = "src/SettingsPage.tsx(25,2): error TS2300: Duplicate identifier 'appearance'.\n"
    monkeypatch.setattr(F, "sh", lambda *a, **k: subprocess.CompletedProcess(a, 2, out, ""))
    res = B.run(tmp_path, ["frontend/src/SettingsPage.tsx"], sys.executable)
    assert not res["ok"] and "TS2300 Duplicate identifier 'appearance'" in res["failed"]
    assert "SettingsPage.tsx(25)" in res["failed"]                       # #853, named
    monkeypatch.setattr(B.shutil, "which", lambda name: None)
    res = B.run(tmp_path, ["frontend/src/SettingsPage.tsx"], sys.executable)
    assert res["ok"] and res["ran"] == ["tsc not run here: npm is not installed"]


def test_a_crate_test_failure_is_named(tmp_path, monkeypatch):
    (tmp_path / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")
    out = "---- raycast::starts_inside stdout ----\nthread panicked at src/lib.rs:9:5\nhit at distance 0\n"
    monkeypatch.setattr(F.rust_fix, "crate_tests",
                        lambda tree, files: (False, "raycast::starts_inside: hit at distance 0", ["metallic_physics"], out))
    res = B.run(tmp_path, ["crates/metallic_physics/src/lib.rs"], sys.executable)
    assert not res["ok"]
    assert res["failed"] == "cargo test -p metallic_physics: raycast::starts_inside: hit at distance 0"   # #486


def test_ci_that_ran_after_the_bases_tip_covers_the_check():
    green = [{"name": "py", "conclusion": "SUCCESS", "started_at": "2026-11-02T12:00:00Z"},
             {"name": "win", "conclusion": "SKIPPED", "started_at": ""}]
    tip = B._when("2026-11-02T11:00:00Z")
    assert B.ci_covered(green, tip)
    assert not B.ci_covered(green, B._when("2026-11-02T13:00:00Z"))   # the base moved after CI started
    assert not B.ci_covered([{**green[0], "conclusion": "FAILURE"}], tip)
    assert not B.ci_covered([], tip) and not B.ci_covered(green, 0)


def _fake_git(monkeypatch, tip=1700000000):
    calls = []

    def sh(args, cwd=None, timeout=600, env=None):
        calls.append(args)
        if "show" in args:
            return subprocess.CompletedProcess(args, 0, f"{tip}\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(F, "sh", sh)
    return calls


def test_the_merger_check_is_cached_per_head_and_base_and_skipped_when_ci_covered_it(tmp_path, monkeypatch):
    calls = _fake_git(monkeypatch)
    ran = []
    pr = {"number": 7, "headRefOid": "h1", "baseRefOid": "b1"}
    runner = lambda tree, files, python: ran.append(files) or {"ok": False, "ran": ["pytest"],  # noqa: E731
                                                                 "failed": "pytest: tests/test_a.py::t", "seconds": 3}
    cache = tmp_path / "c.json"
    res = B.check(pr, ["star/a.py"], "py", [], cache=cache, runner=runner)
    assert not res["ok"] and ran == [["star/a.py"]] and any("merge" in c for c in calls)
    assert B.check(pr, ["star/a.py"], "py", [], cache=cache, runner=runner)["cached"] and len(ran) == 1
    covered = [{"name": "py", "conclusion": "SUCCESS", "started_at": "2030-01-01T00:00:00Z"}]
    res = B.check({**pr, "headRefOid": "h2"}, ["star/a.py"], "py", covered, cache=cache, runner=runner)
    assert res["ok"] and res["skipped"] and len(ran) == 1


GOOD = {"number": 1, "title": "t", "isDraft": False, "baseRefName": "star/next", "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN", "headRefOid": "abc"}
PASSED = [{"name": "ci", "status": "completed", "conclusion": "SUCCESS", "started_at": "2026-11-02T12:00:00Z"}]
DIFF = "diff --git a/star/a.py b/star/a.py\n--- a/star/a.py\n+++ b/star/a.py\n@@ -1 +1,2 @@\n x = 1\n+y = 2\n"


def test_a_merge_ready_pr_holds_when_its_build_check_fails_with_the_test_named(monkeypatch):
    monkeypatch.setattr(M, "cached_review", lambda pr, files, ask: {"verdict": "merge", "risks": []})
    built = []
    fail = lambda pr, files, checks: built.append((files, checks)) or {  # noqa: E731
        "ok": False, "failed": "pytest: tests/test_a.py::test_y", "ran": ["pytest tests/test_a.py"], "seconds": 4}
    row = M.decide(GOOD, checks_fn=lambda sha: PASSED, diff_fn=lambda pr: DIFF, prove_fn=None, hunt_fn=None,
                   build_fn=fail)
    assert row["action"] == "hold" and row["reasons"] == ["build check: pytest: tests/test_a.py::test_y"]
    assert built == [(["star/a.py"], PASSED)] and row["build"]["seconds"] == 4
    ok = lambda pr, files, checks: {"ok": True, "ran": ["pytest tests/test_a.py"], "seconds": 2}  # noqa: E731
    row = M.decide(GOOD, checks_fn=lambda sha: PASSED, diff_fn=lambda pr: DIFF, prove_fn=None, hunt_fn=None,
                   build_fn=ok)
    assert row["action"] == "merge" and row["build"]["ok"] is True
    blocked = M.decide({**GOOD, "isDraft": True}, checks_fn=lambda sha: PASSED, diff_fn=lambda pr: DIFF,
                       build_fn=lambda *a: pytest.fail("a held PR is never built"))
    assert blocked["action"] == "hold"


HEAD, OLD, NOW = "a" * 40, "b" * 40, "c" * 40
CI_LOG = (f"HEAD is now at 8e5707c Merge {HEAD} into {OLD}\n"
          "FAILED tests/test_litha_pr_fixer.py::test_undoing - AssertionError\n")
BASE_LOG = "FAILED tests/test_litha_pr_fixer.py::test_undoing - AssertionError\n"


def _base_case(monkeypatch, base_log=BASE_LOG, now_checks=()):
    monkeypatch.setattr(F, "failed_logs", lambda sha, every=False: CI_LOG if sha == HEAD else base_log)
    monkeypatch.setattr(F, "head_checks", lambda sha: list(now_checks))
    monkeypatch.setattr(F, "gh", lambda *a, **k: pytest.fail(f"no gh write: {a}"))
    monkeypatch.setattr(F, "repair", lambda *a, **k: pytest.fail("not this PR's failure: no repair"))


def test_a_failure_the_base_had_too_gets_a_fresh_run_on_todays_base_not_a_fix(monkeypatch):
    _base_case(monkeypatch)
    ran = []
    monkeypatch.setattr(F, "on_base", lambda pr, tests, python: ran.append(tests) or (True, "1 passed"))
    pr = {"number": 857, "headRefOid": HEAD, "baseRefOid": NOW, "headRefName": "litha/merge-549-20261031-2111"}
    row = F.fix(pr, "python", dry=True)
    assert row["result"] == "rerun" and row["kind"] == "base" and ran == [["tests/test_litha_pr_fixer.py"]]
    assert "whose own CI failed 1 of its 1 failing test(s)" in row["why"] and OLD[:8] in row["why"]
    fresh = []
    monkeypatch.setattr(F, "fresh_run", lambda sha, n, base: fresh.append((sha, n, base)) or 1)
    row = F.fix({**pr, "headRefName": "star/x"}, "python")
    assert row["result"] == "rerun" and fresh == [(HEAD, 857, NOW)]


def test_a_pr_with_one_test_of_its_own_besides_the_bases_gets_the_fresh_run_only_if_both_pass_today(monkeypatch):
    two = CI_LOG + "FAILED tests/test_litha_pr_fixer.py::test_best_of_k - StopIteration\n"
    _base_case(monkeypatch)
    monkeypatch.setattr(F, "failed_logs", lambda sha, every=False: two if sha == HEAD else BASE_LOG)
    pr = {"number": 899, "headRefOid": HEAD, "baseRefOid": NOW, "headRefName": "star/hunt"}
    monkeypatch.setattr(F, "on_base", lambda pr, tests, python: (True, "2 passed"))
    row = F.fix(pr, "python", dry=True)
    assert row["result"] == "rerun" and "failed 1 of its 2 failing test(s)" in row["why"]
    assert F.base_fault(two, {**pr, "baseRefOid": OLD}, F.failures(two)) == ("", "")   # not all the base's: hers


def test_a_base_that_still_fails_is_not_the_prs_to_fix_and_waits_for_the_base_to_move(monkeypatch):
    _base_case(monkeypatch, now_checks=[{"name": "py", "status": "completed", "conclusion": "FAILURE"}])
    monkeypatch.setattr(F, "on_base", lambda *a: pytest.fail("the base still fails: nothing to try"))
    row = F.fix({"number": 903, "headRefOid": HEAD, "baseRefOid": NOW, "headRefName": "star/w2"}, "python")
    assert row["result"] == "skip" and row["kind"] == "base" and "still fails" in row["why"]
    row = F.fix({"number": 903, "headRefOid": HEAD, "baseRefOid": OLD, "headRefName": "star/w2"}, "python")
    assert row["result"] == "skip" and "has not moved" in row["why"]


def test_a_failure_the_base_never_had_is_the_prs_own(monkeypatch):
    _base_case(monkeypatch, base_log="FAILED tests/test_other.py::test_z - x\n")
    assert F.base_fault(CI_LOG, {"headRefOid": HEAD, "baseRefOid": NOW},
                        [{"test": "tests/test_litha_pr_fixer.py::test_undoing", "section": ""}]) == ("", "")
    assert F.base_fault("no checkout line\n", {"headRefOid": HEAD, "baseRefOid": NOW},
                        [{"test": "tests/a.py::t", "section": ""}]) == ("", "")


def test_a_fresh_run_happens_once_per_head_and_base(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "STATE", tmp_path / "tried.json")
    calls = []
    monkeypatch.setattr(F, "gh", lambda *a, **k: calls.append(a[:2]) or "")
    F.RERUNS.set(5)
    try:
        assert F.fresh_run(HEAD, 9, NOW) == 1 and calls == [("pr", "close"), ("pr", "reopen")]
        assert F.fresh_run(HEAD, 9, NOW) == 0 and len(calls) == 2
        assert F.fresh_run(HEAD, 9, OLD) == 1
    finally:
        F.RERUNS.set(None)


def _remote(tmp_path, ours: str, theirs: str, path: str = "docs/notes.md"):
    """A bare 'origin' with star/next and PR #5 (head branch litha/fix-5-x) that conflict in path; a clone of it."""
    def git(cwd, *a):
        r = subprocess.run(["git", *F.IDENTITY, *a], cwd=cwd, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return r.stdout
    origin, work = tmp_path / "origin.git", tmp_path / "seed"
    git(tmp_path, "init", "-q", "--bare", "-b", "star/next", str(origin))
    git(tmp_path, "init", "-q", "-b", "star/next", str(work))
    git(work, "config", "core.autocrlf", "false")
    (work / path).parent.mkdir(parents=True, exist_ok=True)
    (work / path).write_text("one\ntwo\n", encoding="utf-8")
    git(work, "add", "-A"), git(work, "commit", "-qm", "base")
    git(work, "checkout", "-qb", "litha/fix-5-x")
    (work / path).write_text(ours, encoding="utf-8")
    git(work, "commit", "-qam", "pr")
    git(work, "checkout", "-q", "star/next")
    (work / path).write_text(theirs, encoding="utf-8")
    git(work, "commit", "-qam", "base moves")
    git(work, "push", "-q", str(origin), "star/next", "litha/fix-5-x", "litha/fix-5-x:refs/pull/5/head")
    clone = tmp_path / "Star-AI"
    git(tmp_path, "clone", "-q", str(origin), str(clone))
    return git, origin, clone


def test_her_own_conflicting_pr_is_brought_up_to_date_on_its_own_branch(tmp_path, monkeypatch):
    git, origin, clone = _remote(tmp_path, "one\nmine\ntwo\n", "one\ntheirs\ntwo\n")
    monkeypatch.setattr(F, "CLONE", clone)
    monkeypatch.setattr(F, "WORK", tmp_path / "wt")
    (tmp_path / "wt").mkdir()
    monkeypatch.setattr(F, "gh", lambda *a, **k: pytest.fail("her own PR: no new PR, no comment"))
    monkeypatch.setattr(F, "merge_file", lambda tree, path, raw, title, asker: ("one\nmine\ntheirs\ntwo\n", ""))
    pr = {"number": 5, "headRefName": "litha/fix-5-x", "headRefOid": "", "title": "fix"}
    row = F.resolve(pr, sys.executable)
    assert row["result"] == "fixed" and row["fix_pr"] == "#5" and "on her own branch" in row["why"]
    log = git(origin, "log", "--format=%s", "-1", "litha/fix-5-x")
    assert log.startswith("[litha] merge star/next into #5")
    assert git(origin, "show", "litha/fix-5-x:docs/notes.md") == "one\nmine\ntheirs\ntwo\n"
    assert "litha/merge-5" not in git(origin, "branch", "--list")                  # no second branch, no PR


def test_a_frontend_merge_that_does_not_typecheck_is_never_pushed(tmp_path, monkeypatch):
    git, origin, clone = _remote(tmp_path, "one\nmine\ntwo\n", "one\ntheirs\ntwo\n", "frontend/src/Settings.tsx")
    (clone / "frontend" / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(F, "CLONE", clone)
    monkeypatch.setattr(F, "WORK", tmp_path / "wt")
    (tmp_path / "wt").mkdir()
    monkeypatch.setattr(F, "gh", lambda *a, **k: pytest.fail("nothing is pushed or opened"))
    monkeypatch.setattr(F, "merge_file", lambda tree, path, raw, title, asker: ("one\nmine\nmine\ntwo\n", ""))
    seen = []

    def tsc(tree, files, python, steps=None, cargo=True):
        seen.append(steps)
        return {"ok": False, "ran": ["tsc"], "failed": "tsc: frontend/src/Settings.tsx(3): TS2300 Duplicate "
                "identifier 'mine'", "seconds": 1}
    monkeypatch.setattr(F.build_check, "run", tsc)
    monkeypatch.setattr(F.build_check, "plan", lambda tree, files: {"pytest": [], "tsc": True, "vitest": [],
                                                                     "cargo": []})
    before = git(origin, "rev-parse", "litha/fix-5-x")
    row = F.resolve({"number": 5, "headRefName": "litha/fix-5-x", "headRefOid": "", "title": "x"}, sys.executable)
    assert row["result"] == "failed" and "TS2300 Duplicate identifier" in row["why"] and seen
    assert git(origin, "rev-parse", "litha/fix-5-x") == before                   # #853 would have stayed local


def test_her_fix_is_not_pushed_when_what_it_touches_fails(monkeypatch):
    monkeypatch.setattr(F, "failed_logs", lambda sha, every=False: "FAILED tests/test_a.py::t - x\n")
    monkeypatch.setattr(F, "sh", lambda *a, **k: subprocess.CompletedProcess(a, 0, " M star/a.py\n", ""))
    monkeypatch.setattr(F, "gh", lambda *a, **k: "star/a.py\n")
    monkeypatch.setattr(F, "run_tests", lambda *a, **k: (False, "FAILED tests/test_a.py::t - x"))
    monkeypatch.setattr(F, "repair", lambda *a, **k: (True, "fixed a", 1))
    monkeypatch.setattr(F.build_check, "run", lambda tree, files, python: {
        "ok": False, "ran": ["pytest tests/test_b.py"], "failed": "pytest: tests/test_b.py::u", "seconds": 2})
    row = F.fix({"number": 3, "headRefOid": "h", "headRefName": "star/x"}, "python")
    assert row["result"] == "failed" and row["why"] == "fixed a; but then pytest: tests/test_b.py::u"


def test_a_base_fault_is_remembered_with_its_base_so_a_moved_base_is_looked_at_again(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "STATE", tmp_path / "tried.json")
    monkeypatch.setattr(F, "LOG", tmp_path / "fixes.jsonl")
    monkeypatch.setattr(M, "HUNTED", tmp_path / "hunted.json")
    pr = {"number": 4, "headRefOid": HEAD, "baseRefOid": OLD, "isDraft": False, "baseRefName": F.BASE,
          "mergeable": "MERGEABLE", "headRefName": "star/x"}
    monkeypatch.setattr(F, "open_prs", lambda n=None: [pr])
    monkeypatch.setattr(F, "head_checks", lambda sha: [{"name": "py", "status": "completed",
                                                        "conclusion": "FAILURE"}])
    rows = []
    monkeypatch.setattr(F, "fix", lambda pr, python, dry=False: rows.append(pr["baseRefOid"]) or {
        "pr": 4, "result": "skip", "kind": "base", "why": "base"})
    monkeypatch.setattr("litha.learn_loop.after_fix", lambda row: None)
    F.main(["--python", "py"])
    assert json.loads(F.STATE.read_text(encoding="utf-8"))["4"] == f"{HEAD}^{OLD}"
    F.main(["--python", "py"])
    assert rows == [OLD]                                     # same head, same base: not again
    pr["baseRefOid"] = NOW
    F.main(["--python", "py"])
    assert rows == [OLD, NOW]                                # the base moved: looked at again
