from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys

import pytest

from litha import context_pack as C
import litha.pr_fixer as F

CALC = '''"""Small calculator."""
from star.util import double


def add(a, b):
    """Add two numbers."""
    total = a - b
    return total


def twice_sum(a, b):
    return double(add(a, b))


def unrelated(x):
    return x * 3
'''
UTIL = '''def double(x):
    """Twice x."""
    return x * 2
'''
TEST = '''from star.calc import add, twice_sum


def test_add():
    assert add(1, 2) == 3


def test_twice():
    assert twice_sum(1, 2) == 6
'''
LOG = """____________________________ test_add ____________________________

    def test_add():
>       assert add(1, 2) == 3
E       assert -1 == 3
E        +  where -1 = add(1, 2)

tests/test_calc.py:5: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_calc.py::test_add - assert -1 == 3
"""


def _repo(tmp_path, calc=CALC):
    for d in ("star", "tests"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "star" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "star" / "calc.py").write_text(calc, encoding="utf-8")
    (tmp_path / "star" / "util.py").write_text(UTIL, encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(TEST, encoding="utf-8")
    return tmp_path


def test_packer_shows_the_test_the_function_it_calls_and_its_callee_numbered_as_in_the_file(tmp_path):
    tree = _repo(tmp_path)
    units = C.pick(tree, F.failures(LOG), LOG)
    text, paths = C.pack(tree, units, 2000)
    assert "4: def test_add():" in text and "5:     assert add(1, 2) == 3" in text     # the failing test
    assert "7:     total = a - b" in text                                              # the function it calls
    assert text.index("def test_add") < text.index("total = a - b")
    assert "unrelated" not in text                                                     # not called by anything here
    assert paths[0] == "tests/test_calc.py" and "star/calc.py" in paths


def test_packer_puts_the_changed_hunk_first_and_follows_calls_one_hop(tmp_path):
    tree = _repo(tmp_path)
    diff = ("diff --git a/star/calc.py b/star/calc.py\n--- a/star/calc.py\n+++ b/star/calc.py\n"
            "@@ -7,1 +7,1 @@\n-    total = a + b\n+    total = a - b\n")
    units = C.pick(tree, F.failures(LOG), LOG, diff)
    text, _ = C.pack(tree, units, 2000)
    first = text.split("\n--- ")[0]
    assert "changed by the PR" in first and re.search(r"look at line [0-9, ]*\b7\b", first) and "7:     total = a - b" in first
    assert "calls add" in text and "12:     return double(add(a, b))" in text          # a caller, one hop


def test_a_big_function_is_cut_to_the_lines_around_the_failure_and_the_budget_holds(tmp_path):
    body = "\n".join(f"    x{i} = {i}" for i in range(400))
    tree = _repo(tmp_path, CALC + f"\n\ndef huge():\n{body}\n    return x399\n")
    log = "star/calc.py:220: in huge\nE   ValueError: boom\nFAILED tests/test_calc.py::test_add - ValueError"
    units = C.pick(tree, F.failures(log), log)
    text, _ = C.pack(tree, units, 600)
    assert C.tokens(text) <= 600
    assert "220:     x200 = 200" in text and "19: def huge():" in text and "    x10 = 10" not in text


def test_the_whole_prompt_fits_her_window_however_big_the_failure_and_diff(tmp_path):
    tree = _repo(tmp_path)
    log = LOG + ("E   noise " * 20 + "\n") * 400
    diff = "diff --git a/star/calc.py b/star/calc.py\n+++ b/star/calc.py\n@@ -7,1 +7,1 @@\n" + "+x\n" * 3000
    prompt = C.fixer_prompt(tree, title="t", fails=F.failures(LOG), out=log, diff=diff, lessons="L" * 5000,
                            feedback="F" * 9000, proposed="P" * 5000)
    assert C.tokens(prompt) <= C.WINDOW - C.ANSWER
    assert "7:     total = a - b" in prompt and '"line": <number' in prompt


def test_land_exact_and_spaces_and_numbers_and_diff_markers():
    text = "def f(a):\n    if a:\n        return 1\n    return 2\n"
    assert C.land(text, "return 1", "return 3")[3] == "exact"
    s, e, rep, how = C.land(text, "if a:\n    return 1", "if a:\n    return 3")   # lost its indentation
    assert how == "whitespace-tolerant" and text[s:e] == "    if a:\n        return 1"
    assert rep == "    if a:\n        return 3"
    s, e, rep, how = C.land(text, "2:     if a:\n3:         return 1", "2:     if not a:\n3:         return 1")
    assert text[s:e] == "    if a:\n        return 1" and rep == "    if not a:\n        return 1"
    s, e, rep, how = C.land(text, "-        return 0\n+        return 1", "        return 5")
    assert text[s:e] == "        return 1" and rep == "        return 5"
    mutated = "def f(rows):\n    return [r for r in rows if r != 'run_started']\n"
    s, e, rep, how = C.land(mutated, "-    return [r for r in rows if r == 'run_started']",   # only the old side
                            "    return [r for r in rows if r == 'run_started']")
    assert how.startswith("fuzzy") and mutated[s:e] == "    return [r for r in rows if r != 'run_started']"


def test_land_fuzzy_only_when_unique_and_two_equal_places_only_by_their_line_number():
    text = ("def f(items):\n    ok = all(k in seen for k in items)\n    return ok\n\n\n"
            "def g(rows):\n    return [r for r in rows if r]\n")
    s, e, rep, how = C.land(text, "    ok = any(k in seen for k in items)", "    ok = any(k in seen for k in items)")
    assert how.startswith("fuzzy") and text[s:e] == "    ok = all(k in seen for k in items)"
    twins = "def a():\n    return value + 1\n\n\ndef b():\n    return value + 1\n"
    assert "2 times" in C.land(twins, "return value + 1", "return value")
    s, e, _, how = C.land(twins, "return value + 1", "return value", line=6)
    assert C._line_of(twins, s) == 6 and "line number" in how
    alike = "x = compute(alpha, beta)\ny = compute(alpha, betb)\n"
    assert "ambiguous" in C.land(alike, "z = compute(alpha, betc)", "z = 0")
    assert "not in the file" in C.land(text, "something completely different here", "")


def test_apply_edits_lands_a_near_find_but_never_on_tests_and_reports_misses(tmp_path):
    tree = _repo(tmp_path)
    misses = []
    problems = F.apply_edits(tree, [
        {"file": "star/calc.py", "find": "total = a  -  b", "replace": "total = a + b"},
        {"file": "tests/test_calc.py", "find": "assert add(1, 2) == 3", "replace": "assert True"},
        {"file": "star/calc.py", "line": 15, "find": "return nothing_like_this_at_all(q)", "replace": "x"}], misses)
    assert "total = a + b" in (tree / "star" / "calc.py").read_text(encoding="utf-8")
    assert "assert add(1, 2) == 3" in (tree / "tests" / "test_calc.py").read_text(encoding="utf-8")
    assert len(problems) == 2 and any("tests, CI and locks" in p for p in problems)
    assert [m["index"] for m in misses] == [2] and "matched 0 times" in problems[-1]
    assert any("not in the file" in r["reason"] for r in C.REJECTS)


def test_rejected_edits_are_logged_with_why_when_a_log_is_set(tmp_path, monkeypatch):
    log = tmp_path / "rejected.jsonl"
    monkeypatch.setattr(C, "REJECT_LOG", log)
    _repo(tmp_path)
    F.apply_edits(tmp_path, [{"file": "tests/test_calc.py", "find": "x", "replace": "y"}])
    row = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert row["file"] == "tests/test_calc.py" and "may not edit" in row["reason"]


def test_repair_reasks_once_with_the_nearest_real_lines_then_lands_her_corrected_edit(tmp_path):
    tree = _repo(tmp_path)
    ok, out = F.run_tests(tree, ["tests/test_calc.py"], sys.executable)
    assert not ok
    prompts = []
    answers = iter([
        json.dumps({"why": "subtracts", "edits": [{"file": "star/calc.py", "find": "    total = subtract(a, b)",
                                                   "replace": "    total = add_up(a, b)"}]}),
        json.dumps({"edits": [{"file": "star/calc.py", "line": 7, "find": "    total = a - b",
                               "replace": "    total = a + b"}]})])

    def asker(p):
        prompts.append(p)
        return next(answers)

    ok, why, rounds = F.repair(tree, "add", F.failures(out), out, ["tests/test_calc.py"], sys.executable,
                               asker=asker, k=1)
    assert (ok, why, rounds) == (True, "subtracts", 1)
    assert len(prompts) == 2 and "did not apply" in prompts[1] and "7:     total = a - b" in prompts[1]
    assert "total = a + b" in (tree / "star" / "calc.py").read_text(encoding="utf-8")


def test_repo_map_is_cached_per_tree_hash_and_says_where_names_live(tmp_path):
    if not shutil.which("git"):
        pytest.skip("no git")
    tree = _repo(tmp_path / "repo")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    for args in (["init", "-q"], ["add", "."], ["commit", "-qm", "one"]):
        subprocess.run([*git, *args], cwd=tree, check=True, capture_output=True)
    cache = tmp_path / "maps"
    first = C.repo_map(tree, cache)
    assert [s[1] for s in first["star/calc.py"]["symbols"]][:2] == ["add(a, b)", "twice_sum(a, b)"]
    assert first["star/calc.py"]["symbols"][0][2] == "Add two numbers." and first["star/calc.py"]["doc"]
    assert len(list(cache.glob("*.json"))) == 1
    (tree / "star" / "util.py").write_text(UTIL + "\n\ndef triple(x):\n    return x * 3\n", encoding="utf-8")
    for args in (["add", "."], ["commit", "-qm", "two"]):
        subprocess.run([*git, *args], cwd=tree, check=True, capture_output=True)
    second = C.repo_map(tree, cache)
    assert len(list(cache.glob("*.json"))) == 2 and "triple" in [s[0] for s in second["star/util.py"]["symbols"]]
    assert C.symbol_index(tree, cache)["double"] == ["star/util.py"]
    where = C.map_text(tree, ["star/calc.py"], 200, cache)
    assert "star/calc.py: add(a, b)" in where and "star/util.py: double(x)" in where   # and what it imports
