from __future__ import annotations

import json
import os
import sys

import pytest

import litha.bug_bench as B
import litha.learn_loop as L
import litha.pr_fixer as F


def _tree(tmp_path, body="1 + 1"):
    (tmp_path / "star").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "star" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "star" / "m.py").write_text(f"def f():\n    return {body}\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text("from star.m import f\n\n\ndef test_f():\n    assert f() == 2\n",
                                                  encoding="utf-8")
    return tmp_path / "star" / "m.py"


def _same_size_same_second(src, new):
    """The mutant/fix case: same size, and an mtime Python's .pyc check cannot tell from the old one."""
    st = src.stat()
    src.write_text(new, encoding="utf-8")
    os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns))


@pytest.mark.parametrize("run", [lambda t, p: F.run_tests(t, ["tests/test_m.py"], p)[0],
                                 lambda t, p: B.run_tests(t, ["tests/test_m.py"], p)[0],
                                 lambda t, p: L.run_tests(t, ["tests/test_m.py"], p)[0]],
                         ids=["pr_fixer", "bug_bench", "learn_loop"])
def test_a_same_size_edit_in_the_same_second_runs_the_new_code(tmp_path, run):
    """Python keeps a .pyc while size and mtime second match: `1 + 1` -> `1 - 1` used to run the old code (on CI
    the standard suite killed 0/4 planted bugs)."""
    src = _tree(tmp_path)
    (tmp_path / "star" / "__pycache__").mkdir()          # a stale cache from an earlier run, like a bench checkout's
    import py_compile
    py_compile.compile(str(src), cfile=str(tmp_path / "star" / "__pycache__" /
                                           f"m.{sys.implementation.cache_tag}.pyc"))
    assert run(tmp_path, sys.executable)
    _same_size_same_second(src, "def f():\n    return 1 - 1\n")
    assert not run(tmp_path, sys.executable)


def test_a_fix_that_also_passes_without_her_edits_is_flaky_not_fixed(tmp_path):
    """#905: a no-op line in a file no failing test imports 'fixed' #903. The tests pass on the code repair()
    started from, so her edit is undone and the result says flaky."""
    src = _tree(tmp_path)
    before = src.read_text(encoding="utf-8")
    out = "FAILED tests/test_m.py::test_f - assert 0 == 2\n"            # what CI said; locally it passes
    edit = json.dumps({"why": "looked", "edits": [{"file": "star/m.py", "find": "def f():", "replace": "def f():  # x"}]})
    ok, why, _ = F.repair(tmp_path, "t", F.failures(out), out, ["tests/test_m.py"], sys.executable,
                          asker=lambda p: edit, k=1)
    assert not ok and why.startswith(F.FLAKY)
    assert src.read_text(encoding="utf-8") == before


def test_a_real_fix_still_counts(tmp_path):
    src = _tree(tmp_path, "1 - 1")
    ok, out = F.run_tests(tmp_path, ["tests/test_m.py"], sys.executable)
    edit = json.dumps({"why": "plus", "edits": [{"file": "star/m.py", "find": "1 - 1", "replace": "1 + 1"}]})
    ok, why, rounds = F.repair(tmp_path, "t", F.failures(out), out, ["tests/test_m.py"], sys.executable,
                               asker=lambda p: edit, k=1)
    assert (ok, why, rounds) == (True, "plus", 1)
    assert "1 + 1" in src.read_text(encoding="utf-8")


def test_an_edit_that_adds_an_undefined_name_is_refused_before_any_test_runs(tmp_path, monkeypatch):
    """#905's edit: a module-level `if "tests/" in tests:` where `tests` exists nowhere. Refused (and undone)
    without a test run; a correct fix in the next round still lands."""
    pytest.importorskip("ruff")
    src = _tree(tmp_path, "1 - 1")
    ok, out = F.run_tests(tmp_path, ["tests/test_m.py"], sys.executable)
    answers = iter([json.dumps({"why": "guard", "edits": [{"file": "star/m.py", "find": "def f():",
                                                           "replace": "if 'tests/' in tests:\n    pass\n\n\ndef f():"}]}),
                    json.dumps({"why": "plus", "edits": [{"file": "star/m.py", "find": "1 - 1", "replace": "1 + 1"}]})])
    runs = []
    real = F.run_tests
    monkeypatch.setattr(F, "run_tests", lambda *a, **k: runs.append(1) or real(*a, **k))
    prompts, runs_at_ask = [], []
    ok, why, rounds = F.repair(tmp_path, "t", F.failures(out), out, ["tests/test_m.py"], sys.executable,
                               asker=lambda p: prompts.append(p) or runs_at_ask.append(len(runs)) or next(answers), k=1)
    assert (ok, why, rounds) == (True, "plus", 2)
    assert "tests" not in src.read_text(encoding="utf-8")
    assert "Undefined name `tests`" in prompts[1]
    assert runs_at_ask[0] == runs_at_ask[1]               # no test run for the refused edit
