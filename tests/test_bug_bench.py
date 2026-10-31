from __future__ import annotations

import json
import sys

import star.bug_bench as B
import star.bug_proof as P

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
    from star import bug_hunt as H
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
    assert found == [{"file": "star/calc.py", "line": 6, "severity": "high", "why": "should be >=", "proof": {"proven": True}}]
    off = lambda p: json.dumps({"bug": True, "line": 2, "why": "outside the function"})  # noqa: E731
    assert H.hunt(head, head, {"star/calc.py": {6}}, sys.executable, off, proven) == []
