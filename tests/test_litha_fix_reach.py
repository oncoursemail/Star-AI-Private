from __future__ import annotations

import ast
import json
import sys

from litha import context_pack as C
from litha import fix_reach as R
import litha.pr_fixer as F

SHOP = '''"""A tiny shop."""


def price(item):
    return _base(item) * 2


def _base(item):
    table = {"apple": 1, "pear": 2}
    return _lookup(table, item)


def _lookup(table, item):
    return table[item]
'''
TEST = '''from star import shop


def test_price():
    assert shop.price("apple") == 2
    assert shop.price("plum") == 6


def test_discount():
    assert shop.discount(10) == 9
'''


def _repo(tmp_path):
    for d in ("star", "tests"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "star" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "star" / "shop.py").write_text(SHOP, encoding="utf-8")
    (tmp_path / "tests" / "test_shop.py").write_text(TEST, encoding="utf-8")
    return tmp_path


def test_trace_lists_what_the_failing_test_entered_with_its_distance_and_where_it_raised(tmp_path):
    tree = _repo(tmp_path)
    rows = R.trace(tree, "tests/test_shop.py::test_price", sys.executable)
    got = {r["name"]: r for r in rows}
    assert [r["name"] for r in rows] == ["price", "_base", "_lookup"]               # nearest to the test first
    assert (got["price"]["depth"], got["_base"]["depth"], got["_lookup"]["depth"]) == (1, 2, 3)
    assert got["_lookup"]["raised"] == 14 and got["price"]["path"] == "star/shop.py" and got["price"]["calls"] == 2
    assert R.trace(tree, "tests/test_shop.py", sys.executable) == []                # no test id: nothing to trace


def test_missing_names_are_read_from_the_failure_and_told_with_the_test_lines_that_use_them(tmp_path):
    tree = _repo(tmp_path)
    text = ("E   AttributeError: module 'star.shop' has no attribute 'discount'\n"
            "E   ImportError: cannot import name 'tax' from 'star.shop' (x.py)\n"
            "E   TypeError: price() got an unexpected keyword argument 'qty'\n"
            "E   AttributeError: <module 'star.shop' from 'C:\\x\\shop.py'> has no attribute 'discount'\n")
    assert [(m["kind"], m["module"] or m["owner"], m["name"]) for m in R.missing(text)] == [
        ("module", "star.shop", "discount"), ("import", "star.shop", "tax"), ("keyword", "price", "qty")]
    note, paths = R.missing_note(tree, text, [("tests/test_shop.py", "test_discount")])
    assert "star/shop.py has no `discount`" in note and "ADD it" in note
    assert "shop.discount(10) == 9" in note and "takes no keyword `qty`" in note and paths == ["star/shop.py"]
    assert R.missing_note(tree, "E   assert 1 == 2") == ("", [])


def test_an_insert_after_a_def_goes_below_the_whole_function_and_after_a_line_at_its_indentation(tmp_path):
    tree = _repo(tmp_path)
    edits = C.inserts(tree, [
        {"file": "star/shop.py", "after": "def price(item):", "insert": "def discount(x):\n    return x - 1"},
        {"file": "star/shop.py", "after": "    table = {\"apple\": 1, \"pear\": 2}", "insert": "table['fig'] = 4"},
        {"file": "star/shop.py", "find": "a", "replace": "b"}])
    assert edits[2] == {"file": "star/shop.py", "find": "a", "replace": "b"}       # find/replace edits unchanged
    assert F.apply_edits(tree, edits[:2]) == []
    text = (tree / "star" / "shop.py").read_text(encoding="utf-8")
    ast.parse(text)
    assert "    return _base(item) * 2\n\n\ndef discount(x):\n    return x - 1\n" in text
    assert "    table = {\"apple\": 1, \"pear\": 2}\n    table['fig'] = 4\n    return _lookup" in text
    tree = _repo(tmp_path)                                       # her own form: an empty find at a line number
    edits = C.inserts(tree, [{"file": "star/shop.py", "line": 5, "find": "", "replace": "\n\ndef tax(x):\n    return 0"},
                             {"file": "star/shop.py", "line": 10, "find": "", "replace": "    table['plum'] = 3"}])
    assert F.apply_edits(tree, edits) == []
    text = (tree / "star" / "shop.py").read_text(encoding="utf-8")
    assert "    return _base(item) * 2\n\n\ndef tax(x):\n    return 0\n\n\ndef _base" in text
    assert "    table['plum'] = 3\n    return _lookup(table, item)" in text


def test_wide_prompt_shows_the_traced_chain_the_missing_name_the_insert_form_and_the_whole_test(tmp_path):
    tree = _repo(tmp_path)
    ok, out = F.run_tests(tree, ["tests/test_shop.py"], sys.executable)
    assert not ok
    fails = F.failures(out)
    reached = R.trace(tree, fails[0]["test"], sys.executable)
    narrow = C.fixer_prompt(tree, title="t", fails=fails, out=out, diff="", symbols={})
    prompt = C.fixer_prompt(tree, title="t", fails=fails, out=out, diff="", symbols={}, reached=reached, wide=True)
    assert '"after": "<one existing' in prompt and '"after"' not in narrow       # the insert form: wide only
    assert "14:     return table[item]" in prompt and "3 calls deep" in prompt      # two calls past the test
    assert '6:     assert shop.price("plum") == 6' in prompt                      # the whole test, its spec
    assert C.tokens(prompt) <= C.WINDOW - C.ANSWER


def test_failure_text_keeps_the_error_lines_and_drops_the_warnings_summary():
    section = ("    def test_x(tmp_path):\n" + "        step()\n" * 300 + "E   AttributeError: no attribute 'away'\n"
               + "tmp_path = WindowsPath('C:/x')\n" + "        more()\n" * 300 + "tests/test_x.py:3: AttributeError\n"
               "============ warnings summary ============\nx.py:1: SyntaxWarning: invalid escape\n"
               "-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html\n")
    text = C.failure_text([{"test": "tests/test_x.py::test_x", "section": section}], "FAILED tests/test_x.py::test_x")
    assert "no attribute 'away'" in text and "SyntaxWarning" not in text and "WindowsPath" not in text
    assert C.tokens(text) <= 1100


def test_repair_traces_once_and_lands_a_new_function_sent_as_an_insert(tmp_path):
    tree = _repo(tmp_path)
    (tree / "tests" / "test_shop.py").write_text(TEST.split("def test_price")[0] + TEST.split("\n\n\n")[-1],
                                                encoding="utf-8")
    ok, out = F.run_tests(tree, ["tests/test_shop.py"], sys.executable)
    assert not ok and "discount" in out
    prompts = []

    def asker(p):
        prompts.append(p)
        return json.dumps({"why": "discount is missing", "edits": [
            {"file": "star/shop.py", "after": "def price(item):", "insert": "def discount(x):\n    return x - 1"}]})

    ok, why, rounds = F.repair(tree, "t", F.failures(out), out, ["tests/test_shop.py"], sys.executable, asker=asker)
    assert (ok, rounds) == (True, 1) and len(prompts) == 1
    assert "star/shop.py has no `discount`" in prompts[0]


def test_a_half_closed_one_line_docstring_is_mended_and_other_syntax_errors_are_told_exactly(tmp_path):
    tree = _repo(tmp_path)
    half = {"file": "star/shop.py", "after": "def price(item):", "insert": 'def away():\n    """Owner away."\n    return 1'}
    good = {"file": "star/shop.py", "find": "x", "replace": 'def f():\n    """Doc "quoted" here\n    more."""'}
    assert C.mend([half, good])[0]["insert"] == 'def away():\n    """Owner away."""\n    return 1'
    assert C.mend([half, good])[1] == good                                      # quotes already pair up
    assert F.apply_edits(tree, C.inserts(tree, [half])) == [] and C.check_syntax(tree, [half]) == []
    bad = {"file": "star/shop.py", "find": "    return table[item]", "replace": "    return table[item"}
    assert F.apply_edits(tree, [bad]) == []
    assert C.check_syntax(tree, [bad, {"file": "star/nope.py"}]) == [
        "star/shop.py: your edit is not valid Python: '[' was never closed at line 19: def _lookup(table, item): | "
        "    return table[item | "]


def test_wide_prompt_shows_the_module_constant_a_test_reads_without_calling_anything(tmp_path):
    tree = _repo(tmp_path)
    (tree / "star" / "shop.py").write_text(SHOP + '\nNOTE = ("Prices are in euro. "\n        "Ask before you buy.")\n',
                                           encoding="utf-8")
    (tree / "tests" / "test_shop.py").write_text(
        "from star import shop\n\n\ndef test_note():\n    assert 'never guess' in shop.NOTE\n", encoding="utf-8")
    ok, out = F.run_tests(tree, ["tests/test_shop.py"], sys.executable)
    assert not ok
    prompt = C.fixer_prompt(tree, title="t", fails=F.failures(out), out=out, diff="", symbols={}, reached=[], wide=True)
    assert "read by test_note (NOTE)" in prompt and '16: NOTE = ("Prices are in euro. "' in prompt
    assert "read by" not in C.fixer_prompt(tree, title="t", fails=F.failures(out), out=out, diff="", symbols={})


def test_an_edit_that_gets_the_test_one_assert_further_is_kept_though_as_many_tests_fail(tmp_path):
    tree = _repo(tmp_path)
    (tree / "tests" / "test_shop.py").write_text(
        "from star import shop\n\n\ndef test_discount():\n    assert shop.discount(10) == 9\n"
        "    assert shop.discount(0) == 0\n", encoding="utf-8")
    ok, out = F.run_tests(tree, ["tests/test_shop.py"], sys.executable)
    assert not ok and C.failed_at(out, "tests/test_shop.py::test_discount") == 5
    assert C.failed_at("1 passed", "tests/test_shop.py::test_discount") == 10 ** 6
    answers = iter([
        {"why": "missing", "edits": [{"file": "star/shop.py", "after": "def price(item):",
                                      "insert": "def discount(x):\n    return x - 1"}]},
        {"why": "never below 0", "edits": [{"file": "star/shop.py", "find": "    return x - 1",
                                            "replace": "    return max(0, x - 1)"}]}])
    prompts = []

    def asker(p):
        prompts.append(p)
        return json.dumps(next(answers))

    ok, why, rounds = F.repair(tree, "t", F.failures(out), out, ["tests/test_shop.py"], sys.executable, asker=asker)
    assert (ok, why, rounds) == (True, "never below 0", 2)
    assert "the test gets further" in prompts[1] and "return x - 1" in prompts[1]


def test_her_window_is_8192_only_when_the_node_her_calls_go_to_first_has_it(monkeypatch):
    from star.asset3d import llm
    monkeypatch.setenv("LITHA_FIX_WINDOW", "6000")
    assert R.window(4096) == 6000
    monkeypatch.delenv("LITHA_FIX_WINDOW")
    assert R.window(4096) == 4096                                   # under pytest: never probed
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    ctx = {"fast": 8192, "slow": 4096}
    nodes = [{"name": "slow", "usable": True, "status_url": "slow", "tok_s": 22},
             {"name": "fast", "usable": True, "status_url": "fast", "tok_s": 63}]
    monkeypatch.setattr(llm, "_router", lambda: "http://router")
    monkeypatch.setattr(llm, "_key", lambda: "k")
    monkeypatch.setattr(llm, "_get", lambda url, headers=None, timeout=8.0: {"nodes": nodes} if "router" in url
                        else {"models": [{"loaded": True, "ctx": ctx[url]}]})
    R._WINDOW.clear()
    assert R.window(4096) == 8192
    nodes[1]["tok_s"] = 5                                           # the 4096 node is now tried first
    assert R.window(4096) == 8192                                   # cached for a while ...
    R._WINDOW.clear()
    assert R.window(4096) == 4096                                   # ... then narrow
    R._WINDOW.clear()
    monkeypatch.setattr(llm, "_key", lambda: (_ for _ in ()).throw(OSError("no key")))
    assert R.window(4096) == 4096
    R._WINDOW.clear()
