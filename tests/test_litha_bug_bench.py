from __future__ import annotations

import json
import sys

import litha.bug_bench as B
import litha.bug_proof as P

SRC = '''"""doc: a == b in text is not code"""


def gate(x, items):
    if x > 3 and x != 7:
        return True
    return x in items
'''


def test_mutations_hit_code_lines_only_and_stay_valid_python():
    lines = B.code_lines(SRC)
    assert 1 not in lines and {5, 6, 7} <= lines
    assert B.mutate(SRC, 5, "and-or").split("\n")[4] == "    if x > 3 or x != 7:"
    assert B.mutate(SRC, 5, "gt-edge").split("\n")[4] == "    if x >= 3 and x != 7:"
    assert B.mutate(SRC, 6, "true-false").split("\n")[5] == "        return False"
    assert B.mutate(SRC, 7, "in-notin").split("\n")[6] == "    return x not in items"
    assert B.mutate(SRC, 6, "eq-flip") is None                         # nothing to flip there
    src = "def f(a, b, xs):\n    if any(xs):\n        return pow(a, b) + xs[0]\n    return a.lower()\n"
    assert B.mutate(src, 3, "drop-return").split("\n")[2] == "        pow(a, b) + xs[0]"
    assert B.mutate(src, 3, "swap-args").split("\n")[2] == "        return pow(b, a) + xs[0]"
    assert B.mutate(src, 2, "any-all").split("\n")[1] == "    if all(xs):"
    uni = "def g(a, b):\n    s = 'é' + str(a)\n    return s\n"
    assert B.mutate(uni, 2, "wrong-var").split("\n")[1] == "    s = 'é' + str(b)"   # byte offsets, not chars
    assert B.mutate(uni, 3, "wrong-var") is None                     # `s` is not a parameter


def test_lessons_remember_misses_and_show_the_weakest(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "LESSONS", tmp_path / "lessons.json")
    assert B.lessons_text() == ""
    B.learn("and-or", False, {"file": "a.py", "bad": "if a or b:", "good": "if a and b:"})
    B.learn("and-or", True, None)
    for _ in range(3):
        B.learn("eq-flip", True, None)
    text = B.lessons_text()
    assert "you solved 1/2" in text and "`if a or b:` should be `if a and b:`" in text
    assert "!=" not in text                                             # solved kinds are not lessons


def test_sft_pairs_hold_the_real_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "SFT", tmp_path / "sft.jsonl")
    monkeypatch.setattr(B, "bank_row", lambda *a, **k: None)          # never the real nightly bank in a test
    B.save_sft("prompt", {"kind": "and-or", "file": "a.py", "bad": "    if a or b:", "orig": "    if a and b:"})
    row = json.loads((tmp_path / "sft.jsonl").read_text(encoding="utf-8"))
    edit = json.loads(row["messages"][1]["content"])["edits"][0]
    assert (edit["find"], edit["replace"]) == ("if a or b:", "if a and b:")


def _tree(tmp_path, name, body):
    t = tmp_path / name
    (t / "star").mkdir(parents=True)
    (t / "tests").mkdir()
    (t / "star" / "__init__.py").write_text("", encoding="utf-8")
    (t / "star" / "calc.py").write_text(body, encoding="utf-8")
    return t


def test_a_proof_must_fail_on_an_assert_after_the_pr_and_pass_before(tmp_path):
    good = _tree(tmp_path, "base", "def add(a, b):\n    return a + b\n")
    bad = _tree(tmp_path, "head", "def add(a, b):\n    return a - b\n")
    proof = "from star.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    assert P.run_proof(bad, proof, sys.executable)[0] == "proven"
    assert P.run_proof(good, proof, sys.executable)[0] == "passed"
    crash = "from star.calc import add\n\n\ndef test_add():\n    assert add(1) == 3\n"
    assert P.run_proof(bad, crash, sys.executable)[0] == "crashed"
    risk = {"file": "star/calc.py", "line": 2, "severity": "high", "why": "subtracts"}
    ask = lambda prompt: json.dumps({"possible": True, "test": proof})          # noqa: E731
    assert P.prove(bad, risk, sys.executable, ask, base=good)["proven"] is True
    assert P.prove(bad, risk, sys.executable, ask, base=bad)["proven"] is False  # fails before too: her expectation


def test_bank_rows_go_to_the_nightly_work_dir(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"work_dir": str(work), "system_prompt": "You are Litha"}), encoding="utf-8")
    B.bank_row("p", {"edits": []}, {"kind": "and-or"}, cfg)
    row = json.loads((work / "bank-litha-fixes.jsonl").read_text(encoding="utf-8"))
    assert row["kind"] == "corrected" and [m["role"] for m in row["messages"]] == ["system", "user", "assistant"]
    B.bank_row("p", {}, {}, tmp_path / "missing.json")                # no nightly here: nothing written, no error


def test_hunt_keeps_only_proven_flags_on_changed_functions(tmp_path):
    from litha import bug_hunt as H
    src = "def a(x):\n    return x + 1\n\n\ndef b(x):\n    if x > 3:\n        return 1\n    return 0\n"
    head = _tree(tmp_path, "head", src)
    assert H.functions_touching(src, {6}) == [(5, 8)]
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return json.dumps({"bug": True, "line": 6, "why": "should be >="})

    proven = lambda tree, risk, py, asker, base=None: {"proven": risk["line"] == 6, "test": "t"}  # noqa: E731
    found = H.hunt(head, head, {"star/calc.py": {6}, "tests/x.py": {1}}, sys.executable, ask, proven)
    assert len(asked) == 1 and ">> 6:" in asked[0] and "return x + 1" not in asked[0]
    assert found == [{"file": "star/calc.py", "line": 6, "severity": "high", "why": "should be >=", "test": "t",
                      "proof": {"proven": True}}]                       # the test travels on to her fixer
    off = lambda p: json.dumps({"bug": True, "line": 2, "why": "outside the function"})  # noqa: E731
    assert H.hunt(head, head, {"star/calc.py": {6}}, sys.executable, off, proven) == []


def test_the_prover_sees_the_module_shape_and_a_real_test_and_retries_a_wrong_expectation(tmp_path):
    src = "class Calc:\n    def __init__(self, k):\n        self.k = k\n\n    def add(self, a):\n        return a + self.k\n"
    assert P.outline(src) == "class Calc:\n    def __init__(self, k):"
    good, bad = _tree(tmp_path, "base", src), _tree(tmp_path, "head", src.replace("a + self.k", "a - self.k"))
    (bad / "tests" / "test_calc.py").write_text(
        "from star.calc import Calc\n\n\ndef test_other():\n    assert 1\n\n\ndef test_k():\n    assert Calc(2).k == 2\n",
        encoding="utf-8")
    example = P.example_test(bad, "star.calc", ["Calc"])
    assert "from star.calc import Calc" in example and "test_k" in example and "test_other" not in example
    wrong = "from star.calc import Calc\n\n\ndef test_add():\n    assert Calc(2).add(1) == 99\n"
    right = "from star.calc import Calc\n\n\ndef test_add():\n    assert Calc(2).add(1) == 3\n"
    answers, prompts = iter([wrong, right]), []

    def ask(prompt):
        prompts.append(prompt)
        return json.dumps({"possible": True, "test": next(answers)})

    risk = {"file": "star/calc.py", "line": 6, "severity": "high", "why": "subtracts"}
    got = P.prove(bad, risk, sys.executable, ask, base=good)
    assert got["proven"] is True and got["tries"] == 2
    assert "class Calc:" in prompts[0] and "BEFORE the change too" in prompts[1]


def test_hunt_tries_the_second_suspect_and_shows_how_tests_call_the_function(tmp_path):
    from litha import bug_hunt as H
    src = "def score(x):\n    y = x * 2\n    return y + 1\n"
    head = _tree(tmp_path, "head", src)
    (head / "tests" / "test_calc.py").write_text("from star.calc import score\n\n\ndef test_s():\n    assert score(1) == 3\n",
                                                 encoding="utf-8")
    prompts, proved = [], []

    def ask(prompt):
        prompts.append(prompt)
        return json.dumps({"suspects": [{"line": 2, "why": "a"}, {"line": 3, "why": "b"}]})

    def prove(tree, risk, py, asker, base=None):
        proved.append(risk["line"])
        return {"proven": risk["line"] == 3}

    found = H.hunt(head, head, {"star/calc.py": {2, 3}}, sys.executable, ask, prove)
    assert proved == [2, 3] and [f["line"] for f in found] == [3]
    assert "assert score(1) == 3" in prompts[0]


def test_single_test_keeps_one_test_with_its_helpers():
    text = ("import pytest\n\n\ndef helper():\n    return 3\n\n\n@pytest.mark.parametrize('x', [1, 2])\n"
            "def test_a(x):\n    assert x\n\n\ndef test_b():\n    assert helper() == 3\n\n\nclass TestC:\n"
            "    def test_c1(self):\n        assert 1\n\n    def test_c2(self):\n        assert 2\n")
    only_a = P.single_test(text, "tests/test_x.py::test_a[2]")
    assert "def helper" in only_a and "parametrize" in only_a and "def test_a" in only_a
    assert "test_b" not in only_a and "TestC" not in only_a
    only_c2 = P.single_test(text, "tests/test_x.py::TestC::test_c2")
    assert "class TestC" in only_c2 and "test_c2" in only_c2 and "test_c1" not in only_c2 and "test_a" not in only_c2
    assert P.single_test(text, "tests/test_x.py::test_missing") is None
    compile(only_a, "x", "exec")
    compile(only_c2, "x", "exec")


def test_an_existing_test_that_fails_after_and_passes_before_is_the_proof_without_her(tmp_path):
    good = _tree(tmp_path, "base", "def add(a, b):\n    return a + b\n")
    bad = _tree(tmp_path, "head", "def add(a, b):\n    return a - b\n")
    tests = ("from star.calc import add\n\n\ndef test_zero():\n    assert add(0, 0) == 0\n\n\n"
             "def test_add():\n    assert add(1, 2) == 3\n")
    for t in (good, bad):
        (t / "tests" / "test_calc.py").write_text(tests, encoding="utf-8")

    def never(prompt):
        raise AssertionError("no model call needed")

    risk = {"file": "star/calc.py", "line": 2, "severity": "high", "why": "subtracts"}
    got = P.prove(bad, risk, sys.executable, never, base=good)
    assert got["proven"] is True and got["via"] == "existing test tests/test_calc.py::test_add"
    assert "def test_add" in got["test"] and "test_zero" not in got["test"]           # trimmed to the one test
    assert not (bad / P.PROOF).exists() and not (good / P.PROOF).exists()
    no = lambda p: json.dumps({"possible": False})                                      # noqa: E731
    assert P.prove(bad, risk, sys.executable, no, base=None)["proven"] is False         # no base: no shortcut


def test_a_failing_test_that_is_no_clean_proof_is_her_starting_point(tmp_path):
    src = "def add(a, b):\n    return a - b\n"
    good, bad = _tree(tmp_path, "base", src), _tree(tmp_path, "head", src)          # fails before too: not the PR
    (bad / "tests" / "test_calc.py").write_text(
        "from star.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n", encoding="utf-8")
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return json.dumps({"possible": False, "test": ""})

    risk = {"file": "star/calc.py", "line": 2, "severity": "high", "why": "subtracts"}
    assert P.prove(bad, risk, sys.executable, ask, base=good)["proven"] is False
    assert "An existing test of this module fails on the new code (tests/test_calc.py::test_add)" in prompts[0]
    assert "assert add(1, 2) == 3" in prompts[0]


def test_a_flaky_existing_test_is_no_proof(tmp_path):
    good = _tree(tmp_path, "base", "def add(a, b):\n    return a + b\n")
    bad = _tree(tmp_path, "head", "def add(a, b):\n    return a + b\n")
    count = (tmp_path / "count.txt").as_posix()
    (bad / "tests" / "test_calc.py").write_text(
        "from pathlib import Path\nfrom star.calc import add\n\n\ndef test_add():\n"
        f"    f = Path({count!r})\n    n = int(f.read_text()) + 1 if f.exists() else 1\n    f.write_text(str(n))\n"
        "    assert n >= 3 and add(1, 2) == 3\n", encoding="utf-8")          # fails on runs 1-2, passes from run 3
    risk = {"file": "star/calc.py", "line": 2, "severity": "high", "why": "?"}
    got = P.prove(bad, risk, sys.executable, lambda p: json.dumps({"possible": False}), base=good)
    assert got["proven"] is False and (tmp_path / "count.txt").read_text() == "3"    # the rerun passed: no proof


def test_the_hunt_bench_can_pick_mutants_the_tests_miss(tmp_path, monkeypatch):
    t = _tree(tmp_path, "head", "def gate(x):\n    if x > 3:\n        return True\n    return False\n")
    orig = (t / "star" / "calc.py").read_text(encoding="utf-8")
    monkeypatch.setattr(B, "reset", lambda tree: (tree / "star" / "calc.py").write_text(orig, encoding="utf-8"))
    monkeypatch.setattr(B, "sh", lambda *a, **k: type("R", (), {"stdout": ""})())
    items = [{"file": "star/calc.py", "line": 2, "kind": "gt-edge", "tests": ["t"], "orig": "    if x > 3:"},
             {"file": "star/calc.py", "line": 3, "kind": "true-false", "tests": ["t"], "orig": "        return True"}]
    survives = {"gt-edge"}                                       # pretend the tests miss the edge case only
    monkeypatch.setattr(B, "run_tests", lambda tree, tests, py: (
        ">=" in (tree / "star" / "calc.py").read_text(encoding="utf-8") and "gt-edge" in survives, "out"))
    rng = B.random.Random(1)
    assert [m["kind"] for m in B.killed(t, items, 5, sys.executable, rng)] == ["true-false"]
    assert [m["kind"] for m in B.killed(t, items, 5, sys.executable, rng, survivors=True)] == ["gt-edge"]


def test_the_hunt_shows_her_the_assert_that_differs_and_proves_with_that_test(tmp_path):
    from litha import bug_hunt as H
    good = _tree(tmp_path, "base", "def add(a, b):\n    c = a + b\n    return c\n")
    bad = _tree(tmp_path, "head", "def add(a, b):\n    c = a - b\n    return c\n")
    (bad / "tests" / "test_calc.py").write_text("from star.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
                                                encoding="utf-8")
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return json.dumps({"suspects": [{"line": 2, "why": "subtracts"}]})

    found = H.hunt(bad, good, {"star/calc.py": {2}}, sys.executable, ask)
    assert len(prompts) == 1                                          # the proof needed no model call
    assert "passed on the code before the change and fails now (tests/test_calc.py::test_add)" in prompts[0]
    assert "assert -1 == 3" in prompts[0]
    assert [f["line"] for f in found] == [2] and found[0]["proof"]["via"] == "existing test tests/test_calc.py::test_add"


def test_an_existing_test_that_crashes_inside_the_changed_module_is_a_proof_one_crashing_in_itself_is_not(tmp_path):
    good = _tree(tmp_path, "base", "def first(xs):\n    return xs[0] if xs else None\n")
    bad = _tree(tmp_path, "head", "def first(xs):\n    return xs[0]\n")              # dropped the empty guard
    (bad / "tests" / "test_calc.py").write_text(
        "from star.calc import first\n\n\ndef test_empty():\n    assert first([]) is None\n", encoding="utf-8")
    risk = {"file": "star/calc.py", "line": 2, "severity": "high", "why": "IndexError on []"}
    got = P.prove(bad, risk, sys.executable, lambda p: json.dumps({"possible": False}), base=good)
    assert got["proven"] is True and got["via"] == "existing test tests/test_calc.py::test_empty"
    assert "IndexError" in got["failure"]

    good2 = _tree(tmp_path, "base2", "def pair():\n    return {'a': 1}\n")
    bad2 = _tree(tmp_path, "head2", "def pair():\n    return 1\n")
    (bad2 / "tests" / "test_calc.py").write_text(
        "from star.calc import pair\n\n\ndef test_pair():\n    assert pair()['a'] == 1\n", encoding="utf-8")
    risk2 = {"file": "star/calc.py", "line": 2, "severity": "high", "why": "?"}
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return json.dumps({"possible": False})

    assert P.prove(bad2, risk2, sys.executable, ask, base=good2)["proven"] is False  # TypeError in the test's own line
    assert not P.raised_in("E   TypeError: x\ntests/test_calc.py:5: TypeError", "star/calc.py")
    assert P.raised_in("star\\calc.py:2: in first\nE   IndexError: list index out of range", "star/calc.py")
