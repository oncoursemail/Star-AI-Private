from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

import litha.autonomy as A
import litha.pr_fixer as F

HOME_REPO, OTHER = "o/home", "o/studio"
# The base head moved a day ago, relative to now: a fixed date made the "failure older than the base move but within
# RETRY_DAYS" case stop being true a week after it was written.
NEW = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 86400))
OLD = "2026-10-01T00:00:00Z"
FIX_LOG = """____________________________ test_add ____________________________

    def test_add():
>       assert add(1, 2) == 3
E       assert -1 == 3

tests/test_calc.py:5: AssertionError
FAILED tests/test_calc.py::test_add - assert -1 == 3
"""


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    home = tmp_path / "auto"
    monkeypatch.setattr(A, "HOME", home)
    for name in ("OFF", "APPLY"):
        monkeypatch.setattr(A, name, home / name)
    for name, file in (("STATE", "state.json"), ("QUEUE", "queue.json"), ("LOG", "runs.jsonl")):
        monkeypatch.setattr(A, name, home / file)
    monkeypatch.setattr(F, "STATE", tmp_path / "tried.json")
    monkeypatch.setattr(F, "LOG", tmp_path / "fixes.jsonl")
    monkeypatch.setattr(A.claude, "ready", lambda: False)
    return home


class FakeGh:
    """Answers the read calls from a small world; records every call (writes included)."""

    def __init__(self, world: dict):
        self.world, self.calls = world, []

    def __call__(self, *args, **kw):
        self.calls.append(args)
        w = self.world
        if args[0] == "api" and "/check-runs" in args[1]:
            repo = args[1].split("/commits/")[0].removeprefix("repos/")
            return json.dumps({"check_runs": w["checks"].get(repo, [])})
        if args[0] == "api" and "/commits/" in args[1]:
            repo, base = args[1].removeprefix("repos/").split("/commits/")
            if repo not in w["heads"]:
                raise RuntimeError("gh: Git Repository is empty. (HTTP 409)")
            sha, date = w["heads"][repo]
            return json.dumps({"sha": sha, "commit": {"committer": {"date": date}}})
        if args[:2] == ("pr", "list"):
            return json.dumps(w["prs"].get(args[args.index("--repo") + 1], []))
        if args[:2] == ("issue", "list"):
            repo, label = args[args.index("--repo") + 1], args[args.index("--label") + 1]
            return json.dumps([i for i in w["issues"].get(repo, []) if label in [lb["name"] for lb in i["labels"]]])
        if args[:2] == ("pr", "create"):
            return "https://example.invalid/pull/99\n"
        if args[:2] == ("issue", "comment"):
            return ""
        raise AssertionError(f"unexpected gh call {args}")


def ents(tmp_path, clone=None):
    return [{"repo": HOME_REPO, "base": "star/next", "home": True, "clone": None, "work": None},
            {"repo": OTHER, "base": "main", "home": False, "clone": clone, "work": tmp_path / "wt"}]


def check(name, conclusion, status="completed"):
    return {"name": name, "status": status, "conclusion": conclusion, "started_at": "2026-11-02T20:00:00Z"}


def world(**over):
    w = {"heads": {HOME_REPO: ("a" * 40, NEW), OTHER: ("b" * 40, NEW)},
         "checks": {HOME_REPO: [check("tests", "success")], OTHER: [check("ci", "failure"), check("deny", "success")]},
         "prs": {HOME_REPO: [{"number": 7, "headRefName": "dep/x", "headRefOid": "h7", "baseRefName": "star/next",
                              "mergeable": "MERGEABLE", "body": ""}]},
         "issues": {HOME_REPO: [
             {"number": 5, "title": "plain idea", "body": "make it nicer", "labels": [{"name": "litha:ready"}]},
             {"number": 6, "title": "crash", "body": "tests/test_calc.py::test_add fails",
              "labels": [{"name": "litha:ready"}, {"name": "litha:found"}]}]}}
    w.update(over)
    return w


def failed_row(pr, ts, result="failed", repo=None):
    row = {"ts": ts, "pr": pr, "result": result, "why": "still failing"}
    return {**row, "repo": repo} if repo else row


def write_rows(*rows):
    F.LOG.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_dry_run_builds_ranked_queue_with_read_only_calls(tmp_path, monkeypatch):
    fake = FakeGh(world())
    monkeypatch.setattr(A, "gh", fake)
    F.STATE.write_text(json.dumps({"7": "h7"}), encoding="utf-8")
    write_rows(failed_row(7, time.time() - 2 * 86400))                 # base moved after this failure
    out = A.run("dry", sys.executable, ents(tmp_path))
    kinds = [(t["kind"], t["repo"]) for t in out["queue"]["tasks"]]
    assert kinds == [("ci-repair", OTHER), ("issue", HOME_REPO), ("issue", HOME_REPO), ("retry", HOME_REPO)]
    assert [t.get("number") for t in out["queue"]["tasks"][1:3]] == [6, 5]          # a named test ranks higher
    assert out["queue"]["tasks"][1]["test"] == "tests/test_calc.py::test_add"
    writes = [c for c in fake.calls if c[:2] in {("pr", "create"), ("issue", "comment")} or "-X" in c]
    assert writes == [] and all(c[0] in ("api", "pr", "issue") for c in fake.calls)
    assert [r["result"] for r in out["rows"]] == ["would", "limit", "would", "would"]  # one PR task per run
    assert "litha/auto-1-" in out["rows"][0]["why"]
    assert not A.STATE.exists() and json.loads(F.STATE.read_text(encoding="utf-8")) == {"7": "h7"}
    assert json.loads(A.QUEUE.read_text(encoding="utf-8"))["tasks"][0]["key"] == f"ci:{OTHER}:{'b' * 40}"
    assert json.loads(A.LOG.read_text(encoding="utf-8").splitlines()[-1])["mode"] == "dry"


def test_pending_or_green_base_is_no_task_and_empty_repo_is_a_note(tmp_path, monkeypatch):
    w = world(issues={}, prs={})
    w["checks"][OTHER] = [check("ci", "failure"), check("deny", None, "in_progress")]
    del w["heads"][HOME_REPO]
    monkeypatch.setattr(A, "gh", FakeGh(w))
    q = A.build_queue(A.load_state(), ents(tmp_path))
    assert q["tasks"] == [] and "o/home: no star/next head" in q["notes"][0]


def test_open_auto_pr_and_attempted_keys_are_not_queued_again(tmp_path, monkeypatch):
    w = world()
    w["prs"][OTHER] = [{"number": 9, "headRefName": "litha/auto-3-20261102", "headRefOid": "x", "baseRefName": "main",
                        "mergeable": "MERGEABLE", "body": f"... <!-- litha-task: ci:{OTHER}:{'c' * 40} -->"}]
    monkeypatch.setattr(A, "gh", FakeGh(w))
    state = A.load_state()
    state["done"][f"issue:{HOME_REPO}#5"] = {"day": "2026-11-02", "result": "commented"}
    q = A.build_queue(state, ents(tmp_path))
    keys = [t["key"] for t in q["tasks"]]
    assert keys == [f"issue:{HOME_REPO}#6"]          # ci: an older base sha's repair PR is still open
    whys = {s["key"]: s["why"] for s in q["skipped"]}
    assert "already works on it" in whys[f"ci:{OTHER}:{'b' * 40}"] and "attempted" in whys[f"issue:{HOME_REPO}#5"]


def test_retry_needs_same_head_and_a_reason(tmp_path):
    entry = ents(tmp_path)[0]
    prs = [{"number": n, "headRefName": f"b{n}", "headRefOid": f"h{n}", "baseRefName": "star/next",
            "mergeable": "CONFLICTING"} for n in (1, 2, 3, 4, 5)]
    prs.append({"number": 6, "headRefName": "litha/fix-4-20261101", "headRefOid": "h6", "baseRefName": "star/next"})
    tried = {"1": "h1", "2": "old", "3": "h3", "4": "h4", "5": "h5"}
    t = time.time()
    rows = [failed_row(1, t - 86400), failed_row(2, t - 86400), failed_row(3, t - 600),
            failed_row(4, t - 86400), failed_row(5, t - 600, "error"), failed_row(8, t - 86400)]
    head = {"sha": "s" * 40, "date": dt.datetime.fromtimestamp(t - 3600, dt.timezone.utc).isoformat()}
    state = A.load_state()
    state["retries"][f"{HOME_REPO}#1"] = ["z", "y"]
    tasks, skipped = A.retry_tasks(entry, prs, head, tried, state, rows)
    assert [x["number"] for x in tasks] == [5]                          # an error: once, even with no base move
    whys = {s["key"].split("#")[1]: s["why"] for s in skipped}
    assert "retried 2 times" in whys["1"] and "head changed" in whys["2"]
    assert "did not move" in whys["3"] and "already covers" in whys["4"]


def test_day_limit_blocks_new_prs(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "gh", FakeGh(world(issues={}, prs={})))
    state = A.load_state()
    state["opened"] = [{"day": dt.date.today().isoformat(), "key": f"k{i}"} for i in range(3)]
    A.save_state(state)
    out = A.run("dry", sys.executable, ents(tmp_path))
    assert out["rows"][0]["result"] == "limit"


def git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True)


def repo_with_bug(tmp_path) -> tuple[Path, Path, str]:
    origin, clone = tmp_path / "origin.git", tmp_path / "clone"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    git("clone", "-q", str(origin), str(clone), cwd=tmp_path)
    (clone / "star").mkdir()
    (clone / "tests").mkdir()
    (clone / "star" / "__init__.py").write_text("", encoding="utf-8")
    (clone / "star" / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (clone / "tests" / "test_calc.py").write_text("from star.calc import add\n\n\ndef test_add():\n"
                                                   "    assert add(1, 2) == 3\n", encoding="utf-8")
    git("checkout", "-q", "-b", "main", cwd=clone)
    git("add", "-A", cwd=clone)
    git("commit", "-q", "-m", "bug", cwd=clone)
    git("push", "-q", "origin", "main", cwd=clone)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True).stdout.strip()
    return clone, origin, sha


FIXED = json.dumps({"why": "subtracts", "edits": [{"file": "star/calc.py", "find": "a - b", "replace": "a + b"}]})


def test_apply_repairs_failing_base_on_her_branch_and_opens_one_pr(tmp_path, monkeypatch):
    clone, origin, sha = repo_with_bug(tmp_path)
    w = world(issues={}, prs={})
    w["heads"][OTHER] = (sha, NEW)
    fake = FakeGh(w)
    monkeypatch.setattr(A, "gh", fake)
    monkeypatch.setattr(F, "failed_logs", lambda s: FIX_LOG if s == sha else "")
    out = A.run("apply", sys.executable, ents(tmp_path, clone), asker=lambda p: FIXED)
    row = out["rows"][0]
    assert row["result"] == "opened", row
    branch = row["branch"]
    assert branch == f"litha/auto-1-{dt.date.today():%Y%m%d}" and row["files"] == ["star/calc.py"]
    heads = subprocess.run(["git", "ls-remote", "--heads", str(origin)], capture_output=True, text=True).stdout
    assert f"refs/heads/{branch}" in heads and f"{sha}\trefs/heads/main" in heads          # base untouched
    show = subprocess.run(["git", "--git-dir", str(origin), "show", f"{branch}:star/calc.py"], capture_output=True,
                          text=True).stdout
    assert "a + b" in show
    create = [c for c in fake.calls if c[:2] == ("pr", "create")][0]
    assert create[create.index("--base") + 1] == "main" and create[create.index("--head") + 1] == branch
    assert f"litha-task: ci:{OTHER}:{sha}" in create[create.index("--body") + 1]
    state = json.loads(A.STATE.read_text(encoding="utf-8"))
    assert state["n"] == 1 and len(state["opened"]) == 1 and f"ci:{OTHER}:{sha}" in state["done"]
    assert not (tmp_path / "wt" / "litha-auto-1").exists()
    # next run: the same failing head is not taken again
    again = A.run("apply", sys.executable, ents(tmp_path, clone), asker=lambda p: FIXED)
    assert again["rows"] == [] and len([c for c in fake.calls if c[:2] == ("pr", "create")]) == 1


def test_local_mode_repairs_but_pushes_nothing_and_cleans_up(tmp_path, monkeypatch):
    clone, origin, sha = repo_with_bug(tmp_path)
    w = world(issues={}, prs={})
    w["heads"][OTHER] = (sha, NEW)
    fake = FakeGh(w)
    monkeypatch.setattr(A, "gh", fake)
    monkeypatch.setattr(F, "failed_logs", lambda s: FIX_LOG)
    out = A.run("local", sys.executable, ents(tmp_path, clone), asker=lambda p: FIXED)
    assert out["rows"][0]["result"] == "fixed-local"
    heads = subprocess.run(["git", "ls-remote", "--heads", str(origin)], capture_output=True, text=True).stdout
    assert "litha/" not in heads and not any(c[:2] == ("pr", "create") for c in fake.calls)
    branches = subprocess.run(["git", "branch"], cwd=clone, capture_output=True, text=True).stdout
    assert "litha/" not in branches and not A.STATE.exists()


def test_failed_repair_opens_nothing(tmp_path, monkeypatch):
    clone, origin, sha = repo_with_bug(tmp_path)
    w = world(issues={}, prs={})
    w["heads"][OTHER] = (sha, NEW)
    monkeypatch.setattr(A, "gh", FakeGh(w))
    monkeypatch.setattr(F, "failed_logs", lambda s: FIX_LOG)
    monkeypatch.setattr(F, "ROUNDS", 1)
    out = A.run("apply", sys.executable, ents(tmp_path, clone), asker=lambda p: "not json")
    assert out["rows"][0]["result"] == "failed"
    assert "litha/" not in subprocess.run(["git", "ls-remote", "--heads", str(origin)], capture_output=True,
                                          text=True).stdout


def test_triage_comments_a_plan_only_in_apply(tmp_path, monkeypatch):
    task = {"key": f"issue:{HOME_REPO}#5", "kind": "issue", "repo": HOME_REPO, "number": 5, "title": "t",
            "body": "b", "test": ""}
    plan = json.dumps({"summary": "do it", "steps": ["find x", "change y"], "files": ["star/x.py"],
                       "check": "pytest", "size": "small"})
    fake = FakeGh(world())
    monkeypatch.setattr(A, "gh", fake)
    local = A.triage(task, False, asker=lambda p: plan)
    assert local["result"] == "planned-local" and "2. change y" in local["plan"] and fake.calls == []
    done = A.triage(task, True, asker=lambda p: plan)
    assert done["result"] == "commented" and fake.calls[0][:3] == ("issue", "comment", "5")
    assert "litha-task: issue:o/home#5" in fake.calls[0][-1]
    assert A.triage(task, True, asker=lambda p: "{}")["result"] == "failed"


def test_requeue_goes_through_pr_fixer_mark(tmp_path):
    F.STATE.write_text(json.dumps({"7": "h7"}), encoding="utf-8")
    state = A.load_state()
    task = {"key": "retry:x", "repo": HOME_REPO, "number": 7, "tried_key": "7", "sha": "s" * 40}
    assert A.requeue(task, state, False)["result"] == "would-requeue"
    assert json.loads(F.STATE.read_text(encoding="utf-8")) == {"7": "h7"}
    assert A.requeue(task, state, True)["result"] == "requeued"
    assert json.loads(F.STATE.read_text(encoding="utf-8")) == {"7": "retry:" + "s" * 12}
    assert state["retries"][f"{HOME_REPO}#7"] == ["s" * 40]


def test_off_switch_and_apply_file(tmp_path, monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(A, "run", lambda mode, python: seen.append(mode) or
                        {"tasks": 0, "skipped": 0, "notes": [], "queue": {"tasks": []}, "rows": []})
    A.HOME.mkdir(parents=True)
    A.OFF.touch()
    assert A.main([]) == 0 and seen == [] and "off" in capsys.readouterr().out
    A.OFF.unlink()
    A.main([])
    A.APPLY.touch()
    A.main([])
    A.main(["--dry"])
    assert seen == ["dry", "apply", "dry"] and not (A.HOME / "run.lock").exists()
