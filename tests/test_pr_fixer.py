from __future__ import annotations

import json
import sys

import star.pr_fixer as F

LOG = """____________________________ test_add ____________________________

    def test_add():
>       assert add(1, 2) == 3
E       assert -1 == 3

tests/test_calc.py:4: AssertionError
star/calc.py:2: in add
=========================== short test summary info ===========================
FAILED tests/test_calc.py::test_add - assert -1 == 3
FAILED tests/test_calc.py::test_add - assert -1 == 3
"""


def test_failures_take_each_failed_test_once_with_its_section():
    got = F.failures(LOG)
    assert [g["test"] for g in got] == ["tests/test_calc.py::test_add"]
    assert "assert -1 == 3" in got[0]["section"] and "short test summary" not in got[0]["section"]


def test_code_excerpts_show_real_lines_around_frames(tmp_path):
    (tmp_path / "star").mkdir()
    (tmp_path / "star" / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    text = F.code_excerpts(tmp_path, LOG)
    assert "--- star/calc.py" in text and "2:     return a - b" in text


def test_edits_must_match_once_and_never_touch_tests(tmp_path):
    (tmp_path / "star").mkdir()
    (tmp_path / "tests").mkdir()
    src = tmp_path / "star" / "calc.py"
    src.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text("x = 1\n", encoding="utf-8")
    problems = F.apply_edits(tmp_path, [
        {"file": "star/calc.py", "find": "return a - b", "replace": "return a + b"},
        {"file": "tests/test_calc.py", "find": "x = 1", "replace": "x = 2"},
        {"file": "star/calc.py", "find": "nothing here", "replace": "y"},
        {"file": "../outside.py", "find": "a", "replace": "b"},
        {"oops": 1}])
    assert src.read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"
    assert (tmp_path / "tests" / "test_calc.py").read_text(encoding="utf-8") == "x = 1\n"
    assert len(problems) == 4 and any("tests, CI and locks" in p for p in problems)
    assert any("matched 0 times" in p for p in problems)


def test_repair_runs_her_edit_against_the_real_tests(tmp_path):
    import json
    import sys
    (tmp_path / "star").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "star" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "star" / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from star.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n", encoding="utf-8")
    ok, out = F.run_tests(tmp_path, ["tests/test_calc.py"], sys.executable)
    assert not ok
    answers = iter([json.dumps({"why": "wrong place", "edits": [{"file": "tests/test_calc.py", "find": "3", "replace": "-1"}]}),
                    json.dumps({"why": "subtracts", "edits": [{"file": "star/calc.py", "find": "a - b", "replace": "a + b"}]})])
    ok, why, rounds = F.repair(tmp_path, "add", F.failures(out), out, ["tests/test_calc.py"], sys.executable,
                               asker=lambda p: next(answers))
    assert (ok, why, rounds) == (True, "subtracts", 2)
    assert "a + b" in (tmp_path / "star" / "calc.py").read_text(encoding="utf-8")


def test_lint_failures_get_safe_autofixes_then_her_edits(tmp_path):
    import pytest
    pytest.importorskip("ruff")
    (tmp_path / "star").mkdir()
    (tmp_path / "star" / "m.py").write_text("import os\n\n\ndef f():\n    x = 1\n    return 2\n", encoding="utf-8")
    assert {e[2].split()[0] for e in F.lint(tmp_path, sys.executable)} == {"F401", "F841"}
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return json.dumps({"why": "unused local", "edits": [{"file": "star/m.py", "find": "    x = 1\n", "replace": ""}]})

    ok, why, rounds = F.fix_lint(tmp_path, sys.executable, ask)
    assert ok and why == "unused local" and len(asked) == 1 and "F401" not in asked[0]      # os import: autofixed
    assert (tmp_path / "star" / "m.py").read_text(encoding="utf-8") == "\n\ndef f():\n    return 2\n"
    assert F.RUFF_CI.search("::error title=Ruff (F401),file=star/m.py,line=1::x")
