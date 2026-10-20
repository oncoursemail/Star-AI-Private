from __future__ import annotations

import json

from metallic_fixtures import commit, git, write

from metallic import cache as cache_mod
from metallic import checks, engine, gitutil, impact, review, status
from metallic.config import load


def _check(root, **kw):
    return engine.run_check(root, load(root), cache=cache_mod.Cache(engine.default_cache_dir()), jobs=2, **kw)


def _by_name(report, name):
    return next(c for c in report["checks"] if c["name"] == name)


def _select(root, changed):
    cfg = load(root)
    files = gitutil.blobs(gitutil.worktree_tree(root), root)
    graph = impact.build(root, files, cfg, cache_mod.Cache(engine.default_cache_dir()))
    return impact.select(graph, changed, cfg)


def test_impact_selects_only_dependent_tests(repo):
    assert _select(repo, ["pkg/other.py"]).tests == ["tests/test_other.py"]
    assert _select(repo, ["pkg/data.json"]).tests == ["tests/test_loader.py"]       # named by a string constant
    assert _select(repo, ["pkg/__init__.py"]).tests == ["tests/test_core.py", "tests/test_loader.py",
                                                        "tests/test_other.py"]   # every import of pkg.x runs it
    assert _select(repo, ["README.md"]).tests == []
    write(repo, "pkg/blob.bin", "x")
    sel = _select(repo, ["pkg/blob.bin"])                                            # nobody names it: run all
    assert sel.full_reason and len(sel.tests) == 3
    assert _select(repo, ["metallic.toml"]).full_reason == "metallic.toml matches full_on"


def test_lazy_and_relative_imports_are_edges(repo):
    write(repo, "pkg/lazy.py", "def f():\n    from .core import add\n    return add\n")
    write(repo, "tests/test_lazy.py", "import importlib\n\n\ndef test_f():\n"
                                      "    assert importlib.import_module('pkg.lazy').f()(1, 1) == 2\n")
    sel = _select(repo, ["pkg/core.py"])
    assert sel.tests == ["tests/test_core.py", "tests/test_lazy.py"]
    assert sel.distance == {"tests/test_core.py": 1, "tests/test_lazy.py": 2}       # run order: nearest first


def test_fail_fast_starts_no_new_batch_after_a_failure(repo):
    import sys
    from metallic import testrun
    write(repo, "pkg/core.py", "def add(a, b):\n    return a - b\n")
    durations = testrun.Durations(repo / "durations.json")
    got = testrun.run_files(repo, ["tests/test_core.py", "tests/test_other.py", "tests/test_loader.py"],
                            load(repo).test_cmd, sys.executable, {}, jobs=1, durations=durations,
                            priority={"tests/test_core.py": 0}, fail_fast=True)
    assert [(r.path, r.status) for r in got] == [("tests/test_core.py", "fail")]


def test_rerun_is_all_cache_hits_and_change_reruns_only_affected(repo):
    first = _check(repo, full=True)
    assert first["verdict"] == "green"
    assert first["tests"]["ran"] == 3 and first["tests"]["cached"] == 0
    again = _check(repo, full=True)
    assert again["tests"]["ran"] == 0 and again["tests"]["cached"] == 3
    write(repo, "pkg/other.py", "def name():\n    return 'x'  # same behaviour\n")
    third = _check(repo, full=True)
    assert third["tests"]["ran"] == 1 and third["tests"]["cached"] == 2


def test_failing_affected_test_makes_check_red_and_is_not_cached(repo):
    write(repo, "pkg/core.py", "def add(a, b):\n    return a - b\n")
    rep = _check(repo)
    assert rep["verdict"] == "red" and rep["red"] == ["tests"]
    assert rep["tests"]["selected"] == 1 and rep["tests"]["failed"][0]["file"] == "tests/test_core.py"
    assert _check(repo)["tests"]["ran"] == 1                                        # failures are never cached
    assert rep["timings"]["first_test"] <= rep["timings"]["total"]


def test_secret_scan_reports_category_never_the_text(repo):
    token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    address = ".".join(["10", "17", "0", "9"])
    write(repo, "pkg/other.py", f"def name():\n    return 'x'\nTOKEN = '{token}'\nHOST = '{address}'\n")
    rep = _check(repo, only=["secrets"])
    sec = _by_name(rep, "secrets")
    assert sec["status"] == "fail"
    cats = {f["message"] for f in sec["findings"]}
    assert "private network address" in cats and any("GitHub token" in c for c in cats)
    dumped = json.dumps(rep)
    assert token not in dumped and address not in dumped


def test_private_names_from_user_file(repo, env):
    (env / "home").mkdir()
    (env / "home" / "private_names.txt").write_text("# names\nbuzuser\n", encoding="utf-8")
    write(repo, "README.md", "ssh buzuser@server\n")
    sec = _by_name(_check(repo, only=["secrets"]), "secrets")
    assert sec["status"] == "fail" and "buzuser" not in json.dumps(sec)


def test_diff_check_catches_conflict_markers(repo):
    write(repo, "pkg/other.py", "<<<<<<< HEAD\ndef name():\n    return 'x'\n=======\n>>>>>>> b\n")
    assert _by_name(_check(repo, only=["diff-check"]), "diff-check")["status"] == "fail"


def test_protected_paths_only_on_generator_branches(repo):
    git(repo, "checkout", "-q", "-b", "star/chatgpt-x")
    write(repo, "evals/suite.json", "{}\n")
    assert _by_name(_check(repo, only=["protected-paths"]), "protected-paths")["status"] == "fail"
    git(repo, "checkout", "-q", "-b", "star/fix-1")
    assert _by_name(_check(repo, only=["protected-paths"]), "protected-paths")["status"] == "pass"


def test_forbidden_files(repo):
    write(repo, "models/tiny.gguf", "x")
    write(repo, "deploy/.env", "A=1\n")
    found = {f["file"] for f in _by_name(_check(repo, only=["files"]), "files")["findings"]}
    assert found == {"models/tiny.gguf", "deploy/.env"}


def test_anti_slop_rules_on_added_lines(repo):
    write(repo, "web/app.test.ts", "it.only('x', () => {\n  expect(true).toBe(true)\n})\n")
    write(repo, "tests/test_core.py", "from pkg.core import add\n\n\ndef test_add():\n    assert True\n"
                                      "    # TODO make this real\n")
    write(repo, "pkg/other.py", "def name():\n    # x = compute(1)\n    # y = x + 2\n    # return y\n"
                                "    return 'x'  # TODO #12 tracked\n")
    sl = _by_name(_check(repo, only=["anti-slop"]), "anti-slop")
    rules = {(f["file"], f["rule"]) for f in sl["findings"]}
    assert ("web/app.test.ts", "S02.focused-test") in rules
    assert ("web/app.test.ts", "S04.vacuous-assert") in rules
    assert ("tests/test_core.py", "S04.vacuous-assert") in rules
    assert ("tests/test_core.py", "S01.todo") in rules
    assert ("pkg/other.py", "S08.commented-code") in rules
    assert ("pkg/other.py", "S01.todo") not in rules            # has an issue number
    assert sl["status"] == "fail"


def test_luau_api_check(repo, env, monkeypatch):
    dump = env / "api.json"
    dump.write_text(json.dumps({"Classes": [{"Name": "Players", "Tags": ["NotCreatable", "Service"]},
                                            {"Name": "Part", "Tags": []},
                                            {"Name": "Workspace", "Tags": ["NotCreatable", "Service"]}]}))
    write(repo, "src/a.luau", 'local P = game:GetService("Players")\nlocal M = game:GetService("MarketPLACE")\n'
                              'local p = Instance.new("Part")\nlocal w = Instance.new("Workspace")\nwait(1)\n'
                              'task.wait(1) -- wait(2) in a comment\n')
    monkeypatch.setenv("METALLIC_ROBLOX_API_DUMP", str(dump))
    lu = _by_name(_check(repo, only=["luau-api"]), "luau-api")
    got = sorted((f["line"], f["rule"]) for f in lu["findings"])
    assert got == [(2, "L01.unknown-service"), (4, "L02.instance-new"), (5, "L03.deprecated")]


def test_eval_gate_needs_an_allowing_paired_verdict(repo, env):
    write(repo, "pkg/prompts.py", "SYSTEM = 'be very brief'\n")
    assert _by_name(_check(repo, only=["eval-gate"]), "eval-gate")["status"] == "fail"
    verdict = env / "verdict.json"
    verdict.write_text(json.dumps({"allowed": False, "exit_code": 4}))
    assert _by_name(_check(repo, only=["eval-gate"], verdict_file=str(verdict)), "eval-gate")["status"] == "fail"
    verdict.write_text(json.dumps({"allowed": True, "exit_code": 0}))
    assert _by_name(_check(repo, only=["eval-gate"], verdict_file=str(verdict)), "eval-gate")["status"] == "pass"


def test_gate_runs_when_inputs_change_and_caches_pass(repo):
    write(repo, "metallic.toml", (repo / "metallic.toml").read_text() +
          '\n[[gate]]\nname = "no-print"\ncmd = ["{python}", "-c", "import sys; '
          'sys.exit(1 if \'print(\' in open(\'pkg/other.py\').read() else 0)"]\ninputs = ["pkg/**"]\n')
    commit(repo, "gate")
    write(repo, "pkg/other.py", "def name():\n    return 'y'\n")
    first = _by_name(_check(repo, only=["no-print"]), "no-print")
    assert first["status"] == "pass" and not first["cached"]
    assert _by_name(_check(repo, only=["no-print"]), "no-print")["cached"]
    write(repo, "pkg/other.py", "def name():\n    print('x')\n")
    assert _by_name(_check(repo, only=["no-print"]), "no-print")["status"] == "fail"


def test_ai_review_only_comments():
    class Resp:
        def __init__(self, text):
            self.text = text

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": self.text}}]}).encode()

    r = review.review("+x = 1\n", url="http://brain.invalid", key_file="/nonexistent",
                      opener=lambda req, timeout: Resp('[{"file": "a.py", "line": 1, "comment": "x unused"}]'))
    assert r.status == checks.INFO and r.blocking is False and r.findings[0]["message"] == "x unused"

    def down(req, timeout):
        raise OSError("refused")

    r = review.review("+x\n", url="http://brain.invalid", opener=down)
    assert r.status == checks.SKIP and "brain.invalid" not in r.summary
    assert review.review("+x\n").status == checks.SKIP                       # no brain configured


def test_status_lists_projects_runs_and_missing_clones(repo, env):
    engine.save_report(repo, _check(repo, only=["diff-check"]))
    (env / "home").mkdir(exist_ok=True)
    (env / "home" / "projects.toml").write_text(
        f'[[project]]\nname = "Demo"\npath = "{repo.as_posix()}"\n\n[[project]]\nname = "Metallic-MC"\n'
        'path = "/nowhere/mc"\nlang = "Go"\n', encoding="utf-8")
    data = status.collect(repo)
    names = [p["name"] for p in data["projects"]]
    assert names == ["Demo", "Metallic-MC"]
    demo, mc = data["projects"]
    assert demo["connected"] and len(demo["checks"]) == 1 and demo["checks"][0]["verdict"] == "green"
    assert not mc["connected"] and mc["note"] == "no local clone connected"
    assert data["runners"][0]["status"] == "online"
