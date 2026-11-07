from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import litha.ast_mutants as M
import litha.bug_bench as B
import litha.learn_loop as L
import litha.pr_fixer as F
import litha.real_fixes as R

SRC = '''LIMIT = 3 + 1


def gate(x, items, n):
    """doc == text"""
    if not items:
        return False
    if x > 3 and x != 7:
        return True
    elif x is None:
        return f"{x == 1}"
    total = x + n * 2
    for i in range(0, n):
        if i in items:
            continue
    return max(x, n) - items[0] <= total
'''


def _mutants(src):
    return {(s["op"], s["sub"], s["line"]): M.changed_line(src, M.apply(src, s), s["line"])[1].strip()
            for s in M.sites(src) if M.apply(src, s)}


def test_every_family_plants_one_exact_change_and_leaves_the_rest_byte_identical():
    got = _mutants(SRC)
    assert set(M.FAMILIES) == {op for op, _, _ in got}
    assert got[("op-swap", "and->or", 8)] == "if x > 3 or x != 7:"
    assert got[("op-swap", "+->-", 12)] == "total = x - n * 2"
    assert got[("cmp-flip", ">-><=", 8)] == "if x <= 3 and x != 7:"
    assert got[("cmp-flip", "is->is not", 10)] == "elif x is not None:"
    assert got[("cmp-flip", "in->not in", 14)] == "if i not in items:"
    assert got[("off-by-one", "<=-><", 16)] == "return max(x, n) - items[0] < total"
    assert got[("off-by-one", "0->1", 13)] == "for i in range(1, n):"
    assert got[("drop-return", "return x->x", 16)] == "max(x, n) - items[0] <= total"
    assert got[("swap-args", "f(a, b)->f(b, a)", 13)] == "for i in range(n, 0):"
    assert got[("drop-guard", "if c: exit->pass", 6)] == "pass"
    assert got[("bool-invert", "not c->c", 6)] == "if items:"
    assert got[("bool-invert", "c->not c", 8)] == "if not (x > 3 and x != 7):"
    assert got[("bool-invert", "True->False", 9)] == "return False"
    assert not any(line in (1, 5) for _, _, line in got)              # module constant, docstring
    assert [sub for _, sub, line in got if line == 11] == ["return x->x"]   # nothing inside the f-string
    assert ("drop-guard", "if c: exit->pass", 10) not in got            # an elif is never dropped as a guard
    site = M.find(SRC, 8, 7, "and->or")
    new = M.apply(SRC, site)
    diff = [(a, b) for a, b in zip(SRC.split("\n"), new.split("\n")) if a != b]
    assert diff == [("    if x > 3 and x != 7:", "    if x > 3 or x != 7:")]


def test_byte_offsets_survive_non_ascii_and_the_order_is_fixed():
    uni = "def g(a, b):\n    s = 'é' + str(a)\n    return s == 'ü' + b\n"
    got = _mutants(uni)
    assert got[("op-swap", "+->-", 2)] == "s = 'é' - str(a)"
    assert got[("cmp-flip", "==->!=", 3)] == "return s != 'ü' + b"
    assert [(s["line"], s["col"], s["sub"]) for s in M.sites(uni)] == \
        [(s["line"], s["col"], s["sub"]) for s in M.sites(uni)]
    assert M.find(uni + "\n# changed\n", 99, 0, "+->-") is None


def _tiny(tmp_path):
    tree = tmp_path / "tree"
    (tree / "star").mkdir(parents=True)
    (tree / "tests").mkdir()
    (tree / "star" / "calc.py").write_text(
        "def clamp(x, lo, hi):\n    if x < lo:\n        return lo\n    if x > hi:\n        return hi\n    return x\n",
        encoding="utf-8")
    (tree / "tests" / "test_calc.py").write_text(
        "from star.calc import clamp\n\n\ndef test_clamp():\n    assert clamp(5, 0, 9) == 5\n"
        "    assert clamp(-1, 0, 9) == 0\n    assert clamp(12, 0, 9) == 9\n    assert clamp(0, 0, 9) == 0\n",
        encoding="utf-8")
    snap = {p: p.read_bytes() for p in tree.rglob("*.py")}

    def fresh(sha, t=None):
        for p, data in snap.items():
            p.write_bytes(data)
        return tree
    return tree, fresh


def test_the_standard_suite_keeps_only_mutants_an_existing_test_kills(tmp_path, monkeypatch):
    tree, fresh = _tiny(tmp_path)
    monkeypatch.setattr(L, "bench_tree", fresh)
    suite = L.build_standard(sys.executable, n=4, seed=1, sha="abc", per_file=4, log=lambda *a: None)
    assert len(suite["items"]) == 4 and suite["sha"] == "abc"
    for it in suite["items"]:
        assert it["tests"] == ["tests/test_calc.py"] and it["file"] == "star/calc.py"
        fresh("abc")
        assert L.plant(tree, it) is not None                              # found again by file, line, col, op
        ok, _, _ = L.run_tests(tree, it["tests"], sys.executable)
        assert not ok                                                      # killed by the existing test
    assert len({it["op"] for it in suite["items"]}) == 4                  # round-robin over the families


def test_a_standard_run_counts_solves_and_calls_and_never_teaches(tmp_path, monkeypatch):
    tree, fresh = _tiny(tmp_path)
    monkeypatch.setattr(L, "bench_tree", fresh)
    monkeypatch.setattr(L, "RUNS", tmp_path / "runs.jsonl")
    monkeypatch.setattr(B, "LESSONS", tmp_path / "lessons.json")
    B.LESSONS.write_text(json.dumps({"eq-flip": {"tries": 2, "solved": 0}}), encoding="utf-8")
    text = (tree / "star" / "calc.py").read_text(encoding="utf-8")
    site = M.find(text, 2, 7, "<->>=")
    suite = {"sha": "abc", "items": [{"id": "S01", "file": "star/calc.py", "line": 2, "col": 7, "op": "cmp-flip",
                                      "sub": "<->>=", "tests": ["tests/test_calc.py"], "orig": "", "bad": "",
                                      "file_sha": L.file_hash(text.encode())}]}
    assert site
    seen = []

    def asker(prompt):
        seen.append(prompt)
        return json.dumps({"why": "flipped", "edits": [{"file": "star/calc.py", "find": "if x >= lo:",
                                                        "replace": "if x < lo:"}]})
    res = L.run_standard(sys.executable, k=1, asker=asker, suite=suite, log=lambda *a: None)
    assert (res["solved"], res["n"], res["calls"]) == (1, 1, 1)
    assert "if x >= lo:" in seen[0] and "Lessons from your past fixes" in seen[0]   # the diff + frozen lessons
    assert B.LESSONS == tmp_path / "lessons.json"                         # restored after the run
    assert json.loads(B.LESSONS.read_text(encoding="utf-8")) == {"eq-flip": {"tries": 2, "solved": 0}}  # untouched
    assert json.loads(L.RUNS.read_text(encoding="utf-8"))["solved"] == 1
    suite["items"][0]["file_sha"] = "0" * 16                               # the file moved on: never a wrong plant
    assert L.run_standard(sys.executable, asker=asker, suite=suite, log=lambda *a: None)["solved"] == 0


def _gate_env(tmp_path, monkeypatch, solved):
    monkeypatch.setattr(L, "BASELINE", tmp_path / "baseline.json")
    monkeypatch.setattr(L, "PENDING", tmp_path / "pending.json")
    monkeypatch.setattr(L, "REJECTED", tmp_path / "rejected.jsonl")
    monkeypatch.setattr(L, "SUITE", tmp_path / "suite.json")
    monkeypatch.setattr(B, "LESSONS", tmp_path / "lessons.json")
    L.SUITE.write_text(json.dumps({"sha": "abc", "items": [{"id": "S01"}]}), encoding="utf-8")
    L.BASELINE.write_text(json.dumps({"suite_id": L.suite_id(json.loads(L.SUITE.read_text())), "solved": 20,
                                      "n": 32}), encoding="utf-8")
    seen = {}

    def fake(python, k=1, asker=None, extra_lessons=None, **kw):
        seen["lessons"] = extra_lessons
        return {"solved": solved, "n": 32}
    monkeypatch.setattr(L, "run_standard", fake)
    return seen


def test_the_gate_keeps_a_lesson_only_when_the_standard_score_does_not_drop(tmp_path, monkeypatch):
    seen = _gate_env(tmp_path, monkeypatch, solved=20)
    L.add_pending("real:901", "a cache key missed the user id", item="o/r@abc")
    code, verdict = L.gate("py", log=lambda *a: None)
    assert code == 0 and verdict["kept"] and "real:901" in seen["lessons"]
    assert "real:901" in B.load_lessons() and not L.PENDING.exists()
    assert "a cache key missed the user id (a real fix)" in B.lessons_text()
    _gate_env(tmp_path, monkeypatch, solved=19)
    L.add_pending("real:902", "a lesson that hurts", item="o/r@def")
    code, verdict = L.gate("py", log=lambda *a: None)
    assert code == 1 and not verdict["kept"] and "real:902" not in B.load_lessons()
    assert "real:902" in L.REJECTED.read_text(encoding="utf-8") and not L.PENDING.exists()
    assert L.gate("py", margin=1, log=lambda *a: None)[0] == 0           # an explicit noise margin
    L.BASELINE.unlink()
    assert L.gate("py", log=lambda *a: None)[0] == 2                     # no baseline: no verdict


def test_a_real_item_never_sees_the_lesson_made_from_itself(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "LESSONS", tmp_path / "lessons.json")
    B.LESSONS.write_text(json.dumps({"real:1": {"tries": 0, "solved": 0, "real": True, "hint": "own answer",
                                                "item": "o/r@aaa"},
                                     "real:2": {"tries": 0, "solved": 0, "real": True, "hint": "other fix",
                                                "item": "o/r@bbb"}}), encoding="utf-8")
    snap = L.Lessons()
    snap.use(hide="o/r@aaa")
    text = B.lessons_text()
    snap.close()
    assert "other fix" in text and "own answer" not in text and B.LESSONS == tmp_path / "lessons.json"


def test_every_real_python_failure_or_fix_queues_a_bench_item_and_a_fix_a_pending_lesson(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "LOG", tmp_path / "fixes.jsonl")
    monkeypatch.setattr(F, "STATE", tmp_path / "tried.json")
    monkeypatch.setattr(L, "QUEUE", tmp_path / "queue.jsonl")
    monkeypatch.setattr(L, "PENDING", tmp_path / "pending.json")
    monkeypatch.setattr(B, "LESSONS", tmp_path / "lessons.json")
    F.STATE.write_text(json.dumps({"901": "a" * 40, "902": "b" * 40, "o/x#5": "c" * 40}), encoding="utf-8")
    row = {"pr": 901, "result": "failed", "tests": ["tests/test_cache.py"], "why": "x"}
    assert L.after_fix(row) is None                                       # a redirected log is no real run
    monkeypatch.setattr(L, "FIXER_LOG", F.LOG)
    it = L.after_fix(row)
    assert it["sha"] == "a" * 40 and it["tests"] == ["tests/test_cache.py"] and not it["verified"]
    L.after_fix(row)                                                      # the same head is queued once
    assert len(L.QUEUE.read_text(encoding="utf-8").splitlines()) == 1 and not L.PENDING.exists()
    L.after_fix({"pr": 902, "result": "fixed", "tests": ["tests/test_cache.py"], "why": "the key missed the user",
                 "fix_pr": "https://github.com/o/r/pull/950"})
    pending = json.loads(L.PENDING.read_text(encoding="utf-8"))
    assert pending["real:902"]["hint"] == "the key missed the user" and pending["real:902"]["item"].endswith("b" * 40)
    assert json.loads(L.QUEUE.read_text(encoding="utf-8").splitlines()[1])["fix_pr"] == 950
    for skip in ({"pr": 902, "result": "fixed", "kind": "merge", "tests": ["tests/a.py"]},
                 {"pr": 5, "repo": "o/x", "result": "failed", "tests": ["tests/a.py"]},
                 {"pr": 902, "result": "fixed", "tests": ["cargo test -p x"]},
                 {"pr": 903, "result": "failed", "tests": ["tests/a.py"]}):           # no sha known
        assert L.after_fix(skip) is None
    assert "real:902" not in B.load_lessons()                             # pending: not shown before the gate


def test_the_report_prints_both_scores_and_writes_one_record(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(L, "RUNS", tmp_path / "runs.jsonl")
    monkeypatch.setattr(L, "SCOREBOARD", tmp_path / "scoreboard.jsonl")
    monkeypatch.setattr(L, "BASELINE", tmp_path / "baseline.json")
    L.append(L.RUNS, {"suite": "standard", "solved": 21, "n": 32, "seconds": 900, "calls": 70, "fixer": "abc"})
    L.append(L.RUNS, {"suite": "standard", "label": "gate", "solved": 2, "n": 32})
    L.append(L.RUNS, {"suite": "real", "solved": 3, "n": 9, "seconds": 400, "calls": 30})
    rec = L.report("py", last=True)
    out = capsys.readouterr().out
    assert "standard suite  21/32   900 s   70 calls" in out and "real fixes      3/9   400 s   30 calls" in out
    assert json.loads(L.SCOREBOARD.read_text(encoding="utf-8")) == json.loads(json.dumps(rec))


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def test_a_real_fix_from_git_history_becomes_a_verified_item(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    tree, _ = _tiny(tmp_path)
    tree.rename(repo)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "start")
    calc = repo / "star" / "calc.py"
    calc.write_text(calc.read_text(encoding="utf-8").replace("if x > hi", "if x >= hi + 1"), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "clamp off by one")
    test = repo / "tests" / "test_calc.py"
    test.write_text(test.read_text(encoding="utf-8") + "    assert clamp(9.5, 0, 9) == 9\n", encoding="utf-8")
    calc.write_text(calc.read_text(encoding="utf-8").replace("if x >= hi + 1", "if x > hi"), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "Fix clamp: the upper edge was wrong")
    monkeypatch.setattr(L, "ROOT", repo)
    monkeypatch.setattr(L, "TREE", tmp_path / "bench")
    monkeypatch.setattr(R, "FIXLOG", tmp_path / "none.jsonl")
    items = R.mine(sys.executable, rev="HEAD", scan=10, want=3, log=lambda *a: None)
    assert len(items) == 1
    it = items[0]
    assert it["sha"] == _git(repo, "rev-parse", "HEAD") and it["parent"] == _git(repo, "rev-parse", "HEAD~1")
    assert (it["src"], it["tests"], it["source"]) == (["star/calc.py"], ["tests/test_calc.py"], "git")
    assert it["fails"] == ["tests/test_calc.py::test_clamp"]
    assert set(it) == {"id", "repo", "sha", "parent", "src", "tests", "fails", "source"}   # no titles, no paths
    L.break_tree(L.TREE, it)                                               # the replay: broken again
    assert not L.run_tests(L.TREE, it["tests"], sys.executable)[0]


def test_a_queued_failure_counts_once_its_fix_is_known(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    tree, _ = _tiny(tmp_path)
    tree.rename(repo)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "start")
    calc, test = repo / "star" / "calc.py", repo / "tests" / "test_calc.py"
    calc.write_text(calc.read_text(encoding="utf-8").replace("if x > hi", "if x >= hi + 1"), encoding="utf-8")
    test.write_text(test.read_text(encoding="utf-8") + "    assert clamp(9.5, 0, 9) == 9\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "a PR that fails its test")
    broken = _git(repo, "rev-parse", "HEAD")
    calc.write_text(calc.read_text(encoding="utf-8").replace("if x >= hi + 1", "if x > hi"), encoding="utf-8")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "her fix")
    monkeypatch.setattr(L, "ROOT", repo)
    monkeypatch.setattr(L, "TREE", tmp_path / "bench")
    monkeypatch.setattr(L, "QUEUE", tmp_path / "queue.jsonl")
    L.append(L.QUEUE, {"id": "Q7", "repo": L.REPO, "pr": 7, "sha": broken, "tests": ["tests/test_calc.py"],
                       "src": [], "verified": False})
    assert L.real_items() == [] or all(i["id"] != "Q7" for i in L.real_items())   # unverified: not scored
    assert R.verify_queue(sys.executable, heads=lambda it: [broken], log=lambda *a: None) == 0   # still red there
    assert R.verify_queue(sys.executable, heads=lambda it: [_git(repo, "rev-parse", "HEAD")], log=lambda *a: None) == 1
    assert any(i["id"] == "Q7" and i["fix"] == _git(repo, "rev-parse", "HEAD") for i in L.real_items())
