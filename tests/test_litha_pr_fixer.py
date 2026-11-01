from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

import pytest

import litha.pr_fixer as F

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


def test_a_dependency_bump_gets_its_lock_regenerated_by_the_project_tool(tmp_path):
    (tmp_path / "installer" / "star-home").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "requirements-home.in").write_text("yt-dlp==2\n", encoding="utf-8")
    (tmp_path / "installer" / "star-home" / "pin_requirements.py").write_text(
        "from pathlib import Path\nPath('requirements-home.txt').write_text(Path('requirements-home.in').read_text())\n",
        encoding="utf-8")
    (tmp_path / "tests" / "test_home_installer.py").write_text(
        "from pathlib import Path\n\n\ndef test_lock():\n    assert Path('requirements-home.txt').read_text().split() == ['yt-dlp==2']\n",
        encoding="utf-8")
    assert F.fix_lock(tmp_path, sys.executable)[0] is True
    assert F.DEP_FILE.match("requirements-home.txt") and not F.DEP_FILE.match("star/x.py")
    (tmp_path / "requirements-home.in").write_text("yt-dlp==3\n", encoding="utf-8")
    (tmp_path / "tests" / "test_home_installer.py").write_text(
        "def test_pin():\n    assert 'yt-dlp==2' in open('requirements-home.txt').read()\n", encoding="utf-8")
    ok, why = F.fix_lock(tmp_path, sys.executable)
    assert not ok and "needs review" in why


def test_conflicts_are_resolved_block_by_block_and_must_compile():
    text = ("import os\n<<<<<<< HEAD\nA = 1\n=======\nB = 2\n>>>>>>> origin/star/next\n\nx = 3\n"
            "<<<<<<< HEAD\ny = 1\n=======\ny = 2\n>>>>>>> origin/star/next\n")
    answers = iter([json.dumps({"resolved": "A = 1\nB = 2\n"}), json.dumps({"resolved": "y = 2"})])
    merged, why = F.resolve_text("star/m.py", text, "t", lambda p: next(answers))
    assert merged == "import os\nA = 1\nB = 2\n\nx = 3\ny = 2\n" and why == ""
    bad = iter([json.dumps({"resolved": "def f(:\n"})] * 3)
    assert F.resolve_text("star/m.py", text, "t", lambda p: next(bad))[0] is None         # brackets do not balance
    assert "does not compile" in F.broken(Path("."), "star/m.py", "import os\ndef f:\n")    # must compile
    marked = iter([json.dumps({"resolved": "<<<<<<< HEAD"})] * 3)
    assert F.resolve_text("star/m.py", text, "t", lambda p: next(marked))[0] is None      # no markers left


DIFF3 = ("<<<<<<< HEAD\nfn keep() {}\nfn pr_added() {}\n||||||| base\nfn keep() {}\n=======\nfn keep() {}\n"
         "fn main_added() {}\n>>>>>>> origin/main\n")


def test_a_resolution_that_drops_what_one_side_added_is_sent_back():
    asked = []
    answers = iter([json.dumps({"resolved": "fn keep() {}\nfn pr_added() {}\n"}),             # lost main's function
                    json.dumps({"resolved": "fn keep() {}\nfn pr_added() {}\nfn main_added() {}\n"})])
    merged, why = F.resolve_text("crates/a/src/lib.rs", DIFF3, "t", lambda p: asked.append(p) or next(answers))
    assert why == "" and "fn main_added" in merged
    assert "fn main_added" in asked[1] and "dropped" in asked[1]
    lazy = iter([json.dumps({"resolved": "fn keep() {}\n"})] * 3)
    assert F.resolve_text("crates/a/src/lib.rs", DIFF3, "t", lambda p: next(lazy))[0] is None


def test_lost_brackets_and_decoded_escapes_are_sent_back():
    block = ('<<<<<<< HEAD\n    fn a() {\n        eprintln!("{m}\\nusage: a");\n    }\n||||||| base\n    fn a() {}\n'
             '=======\n    fn a() {\n        eprintln!("{m}\\nusage: b");\n    }\n>>>>>>> origin/main\n')
    good = '    fn a() {\n        eprintln!("{m}\\nusage: a b");\n    }\n'
    assert F.slips("x.rs", block, good) == ""
    assert "brackets" not in F.slips("x.rs", block, good.replace("\\n", "\n")) and \
        "escape" in F.slips("x.rs", block, good.replace("\\n", "\n"))                     # the #446 slip
    assert "{}" in F.slips("x.rs", block, good.rsplit("    }", 1)[0])                       # lost closing brace
    answers = iter([json.dumps({"resolved": good.replace("\\n", "\n")}), json.dumps({"resolved": good})])
    assert F.resolve_text("x.rs", block, "t", lambda p: next(answers))[0] == good


def test_repeating_the_line_outside_the_block_is_sent_back():
    block = ("<<<<<<< HEAD\n companions?:ReactNode\n||||||| base\n companions?:ReactNode\n=======\n companions?:ReactNode\n"
             " account?:ReactNode\n>>>>>>> origin/main\n")
    before, after = "export type P={\n appearance?:ReactNode\n", " data:BootData\n}\n"
    assert F.slips("p.tsx", block, " companions?:ReactNode\n account?:ReactNode\n", before, after) == ""
    assert "just before" in F.slips("p.tsx", block, " appearance?:ReactNode\n companions?:ReactNode\n account?:ReactNode\n",
                                    before, after)                                       # the #853 slip
    assert "just after" in F.slips("p.tsx", block, " companions?:ReactNode\n account?:ReactNode\n data:BootData\n",
                                   before, after)


def test_two_pure_additions_are_kept_both_without_asking():
    text = ("    fn start() {\n<<<<<<< HEAD\n        let a = 1;\n||||||| 494e8a5d\n=======\n        sync();\n"
            ">>>>>>> origin/main\n        run();\n    }\n")
    merged, why = F.resolve_text("s.rs", text, "t", lambda p: 1 / 0)               # the model is never asked
    assert why == "" and merged == "    fn start() {\n        let a = 1;\n        sync();\n        run();\n    }\n"
    answers = iter([json.dumps({"resolved": "        sync();\n        let a = 1;\n"})])   # a checker complained: she decides
    assert F.resolve_text("s.rs", text, "t", lambda p: next(answers), hint="x\n")[0].count("sync();") == 1


def test_what_one_side_deleted_on_purpose_may_stay_deleted():
    block = ("<<<<<<< HEAD\n## Physics\n| Crate | Role |\n| --- | --- |\n| core | data |\n||||||| base\n## Physics\n"
             "## Old notes\n=======\n## Physics\n## Old notes\n| render | GPU |\n>>>>>>> origin/main\n")
    assert F.dropped(block, "## Physics\n| Crate | Role |\n| --- | --- |\n| core | data |\n| render | GPU |\n") == []
    assert F.dropped(block, "## Physics\n| core | data |\n") == ["row Crate", "row render"]


def test_merged_rust_must_parse_when_the_base_copy_does(tmp_path):
    if not (shutil.which("rustfmt") or (Path.home() / ".cargo/bin/rustfmt.exe").exists()):
        pytest.skip("no rustfmt")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "a"\nedition = "2024"\n', encoding="utf-8")
    (tmp_path / "lib.rs").write_text("fn a() {}\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", *F.IDENTITY, "commit", "-qm", "x"], cwd=tmp_path, check=True)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=tmp_path, check=True)
    with patch.object(F, "BASE", "main"):
        assert F.broken(tmp_path, "lib.rs", "fn a() {}\nfn b() { let x = 1; }\n") == ""
        assert "rustfmt rejects" in F.broken(tmp_path, "lib.rs", "fn a() {}\nfn b() { let x = ; }\n")
        assert F.broken(tmp_path, "new.rs", "fn c( {") == ""               # no base copy to compare with: CI decides
        assert F.tidy(tmp_path, "lib.rs", "fn a() {}\nfn b() {\n    \n}\n") == "fn a() {}\nfn b() {}\n"   # cargo fmt clean
        (tmp_path / "lib.rs").write_text("fn  a() {}\n", encoding="utf-8")         # a base that is not rustfmt-clean:
        subprocess.run(["git", *F.IDENTITY, "commit", "-qam", "y"], cwd=tmp_path, check=True)
        subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=tmp_path, check=True)
        assert F.tidy(tmp_path, "lib.rs", "fn  a() {}\nfn b() {\n    \n}\n") == "fn  a() {}\nfn b() {\n    \n}\n"
