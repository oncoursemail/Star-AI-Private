from __future__ import annotations

import json
import sys

import litha.bug_diff as D
import litha.bug_proof as P

BASE = "def gate(x):\n    if x > 3:\n        return True\n    return False\n"
HEAD = BASE.replace("x > 3", "x >= 3")
PASSING = "from star.calc import gate\n\n\ndef test_big():\n    assert gate(9) is True\n"   # misses the edge


def _tree(tmp_path, name, body, test=PASSING):
    t = tmp_path / name
    (t / "star").mkdir(parents=True)
    (t / "tests").mkdir()
    (t / "star" / "__init__.py").write_text("", encoding="utf-8")
    (t / "star" / "calc.py").write_text(body, encoding="utf-8")
    (t / "tests" / "test_calc.py").write_text(test, encoding="utf-8")
    return t


def _asker(calls, bug=True, prompts=None):
    def ask(prompt):
        if prompts is not None:
            prompts.append(prompt)
        if prompt.startswith("A pull request changed this code (changed"):
            return json.dumps({"calls": calls})
        return json.dumps({"bug": bug, "why": "3 is not above 3"})
    return ask


RISK = {"file": "star/calc.py", "line": 2, "severity": "high", "why": ">= lets 3 through, should be >"}
NO_TEST = lambda p: json.dumps({"possible": False})  # noqa: E731 - her own test is not the path under test


def test_a_survivor_is_proven_by_the_first_call_that_differs_as_a_test_that_passes_before(tmp_path):
    good, bad = _tree(tmp_path, "base", BASE), _tree(tmp_path, "head", HEAD)
    prompts = []
    got = P.prove(bad, RISK, sys.executable, NO_TEST, base=good, diff_asker=_asker(["gate(9)", "gate(3)"], True, prompts))
    assert got["proven"] is True and got["via"] == "differential gate(3)"
    assert got["difference"] == {"call": "gate(3)", "before": "False", "after": "True"}
    assert "from star.calc import gate" in got["test"] and "assert got is False" in got["test"]
    assert "was: if x > 3:" in prompts[0]                                    # she sees the exact changed line
    assert P.run_proof(good, got["test"], sys.executable)[0] == "passed"
    assert P.run_proof(bad, got["test"], sys.executable)[0] == "proven"


def test_a_difference_she_judges_intended_holds_nothing_and_the_judge_sees_the_authors_words(tmp_path):
    good, bad = _tree(tmp_path, "base", BASE), _tree(tmp_path, "head", HEAD)
    prompts = []
    got = P.prove(bad, RISK, sys.executable, NO_TEST, base=good, intent="Let 3 through the gate on purpose",
                  diff_asker=_asker(["gate(3)"], False, prompts))
    assert got["proven"] is False
    assert any("Let 3 through the gate on purpose" in p and "gave False before" in p for p in prompts)


def test_calls_the_old_code_cannot_take_never_count(tmp_path):
    good = _tree(tmp_path, "base", BASE)
    bad = _tree(tmp_path, "head", HEAD.replace("def gate(x):", "def gate(x, edge=3):").replace("3:", "edge:"))
    risk = {**RISK, "line": 2}
    got = D.differential(bad, good, risk, sys.executable, _asker(["gate(3, edge=3)", "new_name(1)"]))
    assert got["proven"] is False                     # TypeError / NameError come from the call, not the module


def test_unchanged_behaviour_and_unreached_lines_prove_nothing(tmp_path):
    good, bad = _tree(tmp_path, "base", BASE), _tree(tmp_path, "head", BASE.replace("x > 3", "3 < x"))
    prompts = []
    got = D.differential(bad, good, RISK, sys.executable, _asker(["gate(3)", "gate(4)"], True, prompts))
    assert got["proven"] is False and got["why"] == "no input gave a different result"
    assert "showed no bug" in prompts[-1] and "`gate(3)`: False on both sides" in prompts[-1]  # round 2 sees it


def test_an_exception_raised_inside_the_module_after_the_change_is_a_difference(tmp_path):
    good = _tree(tmp_path, "base", "def first(xs):\n    return xs[0] if xs else None\n")
    bad = _tree(tmp_path, "head", "def first(xs):\n    return xs[0]\n")
    risk = {"file": "star/calc.py", "line": 2, "severity": "high", "why": "IndexError on []"}
    got = D.differential(bad, good, risk, sys.executable, _asker(["first([1])", "first([])"]))
    assert got["proven"] is True and got["difference"]["after"] == "an exception IndexError"
    assert "assert got is None" in got["test"]


def test_the_function_to_call_and_the_lines_it_replaced():
    src = "class Calc:\n    def add(self, a):\n        return a + 1\n\n\ndef outer():\n    def inner():\n        return 1\n"
    assert D.target(src, 3) == ("Calc.add", 2, 3)
    assert D.target(src, 8) is None                                           # nested: not callable from outside
    assert D.was_lines("a\nb\nc\n", "a\nB\nc\nd\n") == {2: "b", 4: None}
    assert D.calls_of(json.dumps({"calls": ["f(1)", "f(1)", "import os", "open('x')", "f(None)"]})) == (
        "", ["f(1)", "f(None)"])
    assert D.calls_of(json.dumps({"setup": "s = Store()", "calls": ["f(s)"]})) == ("s = Store()", ["f(s)"])
    assert D.calls_of(json.dumps({"setup": "import subprocess", "calls": ["f(1)"]}))[0] == ""


def test_setup_builds_the_object_the_calls_need_and_travels_into_the_test(tmp_path):
    src = ("class Store:\n    def __init__(self):\n        self.items = [3, 1, 2]\n\n\n"
           "def top(store):\n    return max(store.items)\n")
    good, bad = _tree(tmp_path, "base", src), _tree(tmp_path, "head", src.replace("max(", "min("))
    risk = {"file": "star/calc.py", "line": 7, "severity": "high", "why": "min where max is meant"}

    def ask(prompt):
        if prompt.startswith("A pull request changed this code (changed"):
            return json.dumps({"setup": "s = Store()", "calls": ["top(s)"]})
        return json.dumps({"bug": True})

    got = D.differential(bad, good, risk, sys.executable, ask)
    assert got["proven"] is True and "    s = Store()\n    got = top(s)\n    assert got == 3" in got["test"]
    assert "from star.calc import Store, top" in got["test"]


def test_a_result_that_holds_its_own_checkout_path_is_no_difference_and_calls_write_outside_the_checkout(tmp_path):
    src = "from pathlib import Path\n\n\ndef where(x):\n    Path('made.txt').write_text('x')\n    return (str(Path(__file__)), x > 3)\n"
    good, bad = _tree(tmp_path, "base", src), _tree(tmp_path, "head", src.replace("x > 3", "x >= 3"))
    risk = {"file": "star/calc.py", "line": 6, "severity": "high", "why": ">= should be >"}
    got = D.differential(bad, good, risk, sys.executable, _asker(["where(3)"]))
    assert got["proven"] is False                   # the paths differ on each side: not a behaviour change
    assert not (bad / "made.txt").exists() and not (good / "made.txt").exists()
