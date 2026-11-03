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
                               asker=lambda p: next(answers), k=1)
    assert (ok, why, rounds) == (True, "subtracts", 2)
    assert "a + b" in (tmp_path / "star" / "calc.py").read_text(encoding="utf-8")


def _calc(tmp_path, code):
    (tmp_path / "star").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "star" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "star" / "calc.py").write_text(code, encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from star.calc import add, mul\n\n\ndef test_add():\n    assert add(1, 2) == 3\n\n\n"
        "def test_mul():\n    assert mul(2, 3) == 6\n", encoding="utf-8")
    return F.run_tests(tmp_path, ["tests/test_calc.py"], sys.executable)[1]


TWO_BUGS = "def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a + b\n"


def _edit(why, find, replace):
    return json.dumps({"why": why, "edits": [{"file": "star/calc.py", "find": find, "replace": replace}]})


def test_best_of_k_keeps_the_candidate_with_fewest_failures_then_the_smallest(tmp_path):
    out = _calc(tmp_path, TWO_BUGS)
    answers = iter([_edit("nothing", "return a * a", "return 0"),                    # refused: no match
                    _edit("add, big", "def add(a, b):\n    return a - b", "def add(a, b):\n    x = 1\n    return a + b"),
                    _edit("add", "return a - b", "return a + b"),                     # same failures, smaller
                    _edit("mul", "def mul(a, b):\n    return a + b", "def mul(a, b):\n    return a * b")])
    prompts = []

    def asker(p):
        prompts.append(p)
        return next(answers)

    ok, why, rounds = F.repair(tmp_path, "calc", F.failures(out), out, ["tests/test_calc.py"], sys.executable,
                               asker=asker, k=3)
    assert (ok, why, rounds) == (True, "mul", 2)
    assert len(prompts) == 4                       # 3 candidates in round 1, the first of round 2 passed at once
    assert "already proposed" not in prompts[0] and "return a * a" in prompts[1] and "x = 1" in prompts[2]
    assert "were kept" in prompts[3] and "already proposed" not in prompts[3]
    assert (tmp_path / "star" / "calc.py").read_text(encoding="utf-8") == (
        "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n")   # the small add fix, not x = 1


def test_a_candidate_that_passes_ends_the_round_without_asking_for_more(tmp_path):
    out = _calc(tmp_path, "def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n")
    calls = []
    ok, why, rounds = F.repair(tmp_path, "add", F.failures(out), out, ["tests/test_calc.py"], sys.executable,
                               asker=lambda p: calls.append(p) or _edit("sub", "a - b", "a + b"), k=3)
    assert (ok, why, rounds, len(calls)) == (True, "sub", 1, 1)


def test_k_comes_from_the_environment_and_one_means_one_answer_per_round(tmp_path, monkeypatch):
    out = _calc(tmp_path, TWO_BUGS)
    monkeypatch.setattr(F, "ROUNDS", 2)
    monkeypatch.setenv("LITHA_FIX_K", "1")
    calls = []
    ok, _, rounds = F.repair(tmp_path, "calc", F.failures(out), out, ["tests/test_calc.py"], sys.executable,
                             asker=lambda p: calls.append(p) or "not json")
    assert (ok, rounds, len(calls)) == (False, 2, 2)
    assert "not valid JSON" in calls[1]


def test_undoing_a_candidate_keeps_uncommitted_changes_like_the_benchs_planted_bug(tmp_path, monkeypatch):
    """A round used to be undone with a git checkout of the whole tree: on the bench that erased the planted bug
    itself, so the next round 'solved' it with no fix at all."""
    if not shutil.which("git"):
        pytest.skip("no git")
    good = "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n"
    _calc(tmp_path, good)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    for args in (["init", "-q"], ["add", "."], ["commit", "-qm", "ok"]):
        subprocess.run([*git, *args], cwd=tmp_path, check=True, capture_output=True)
    src = tmp_path / "star" / "calc.py"
    src.write_text(good.replace("a + b", "a - b"), encoding="utf-8")                  # the planted bug, uncommitted
    ok, out = F.run_tests(tmp_path, ["tests/test_calc.py"], sys.executable)
    monkeypatch.setattr(F, "ROUNDS", 2)
    ok, _, rounds = F.repair(tmp_path, "add", F.failures(out), out, ["tests/test_calc.py"], sys.executable,
                             asker=lambda p: _edit("no-op", "def mul(a, b):", "def mul(a, b):  # looked"), k=2)
    assert (ok, rounds) == (False, 2)
    assert src.read_text(encoding="utf-8") == good.replace("a + b", "a - b")


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
    (tmp_path / "litha").mkdir()                   # CI lints litha/ too: a lint error there is not "CI-only"
    (tmp_path / "litha" / "x.py").write_text("import os\n", encoding="utf-8")
    assert [e[0] for e in F.lint(tmp_path, sys.executable)] == ["litha/x.py"]


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


def test_an_addition_next_to_the_other_sides_change_merges_without_her_model():
    text = ("mod a;\n<<<<<<< pr\npub use instance::edit;\npub use instance::{Changes, World};\n||||||| base\n"
            "pub use instance::{Changes, World};\n=======\npub use instance::{\n    Changes, TagChange, World,\n};\n"
            ">>>>>>> main\nmod b;\n")
    merged, why = F.resolve_text("crates/core/src/lib.rs", text, "t", asker=lambda p: pytest.fail("no model needed"))
    assert why == "" and merged == ("mod a;\npub use instance::edit;\npub use instance::{\n    Changes, TagChange, World,\n"
                                    "};\nmod b;\n")                                    # Studio #317's real shape
    assert F.adjacent("x\n", "x\n", "x\ny\n") is None                                # nothing changed on one side
    assert F.adjacent("y\nx\n", "x\n", "x\nz\n") is None                             # both only added: order unknown


def test_a_conflict_too_big_for_her_window_is_refused_without_asking_her():
    side = "".join(f"- line {i} of a long design note\n" for i in range(400))
    text = f"<<<<<<< pr\nA{side}||||||| base\n{side}=======\nB{side}>>>>>>> main\n"   # both change line 0
    merged, why = F.resolve_text("ARCHITECTURE.md", text, "t", asker=lambda p: pytest.fail("no model call"))
    assert merged is None and "too big for her 4096-token window" in why


def test_a_pyright_gate_failure_goes_to_her_type_fixer_not_a_rerun(monkeypatch):
    log = ("Python types\tCheck\t2026-11-01T07:50:00Z New pyright errors (fix them; the baseline only shrinks):\n"
           "Python types\tCheck\t2026-11-01T07:50:00Z   litha/pr_fixer.py:411: No overloads for \"run\" [reportCallIssue]\n")
    monkeypatch.setattr(F, "failed_logs", lambda sha: log)
    monkeypatch.setattr(F, "rerun_failed", lambda *a: pytest.fail("a type error is not flaky"))
    monkeypatch.setattr(F, "sh", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    monkeypatch.setattr(F, "gh", lambda *a, **k: "")
    called = []
    monkeypatch.setattr(F, "fix_types", lambda tree, python, asker: called.append(tree) or (False, "no npx", 0))
    row = F.fix({"headRefOid": "abc", "number": 848, "headRefName": "x"}, "python")
    assert called and row["result"] == "failed" and row["kind"] == "types"
    assert row["why"].startswith("new pyright errors: litha/pr_fixer.py:411: No overloads") and "(no npx)" in row["why"]
    monkeypatch.setattr(F, "fix_types", lambda tree, python, asker: (True, "narrowed the Optional", 1))
    row = F.fix({"headRefOid": "abc", "number": 848, "headRefName": "x"}, "python", dry=True)
    assert row["result"] == "fixed" and row["tests"] == ["pyright baseline gate"]


def _typed_repo(tmp_path, baseline=None):
    (tmp_path / "star").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "pyright_baseline.json").write_text(json.dumps(baseline or {}), encoding="utf-8")
    (tmp_path / "star" / "m.py").write_text("def f(x: str | None) -> str:\n    return x.upper()  # BAD\n",
                                            encoding="utf-8")

    def checker(tree, python, files=None):      # pyright stand-in: one error per line marked BAD, in every star/ file
        checker.calls.append(files)
        return [{"file": f"star/{p.name}", "line": i + 1, "rule": "reportOptionalMemberAccess",
                 "message": '"upper" is not a known attribute of "None"'}
                for p in sorted((tree / "star").glob("*.py")) if files is None or f"star/{p.name}" in files
                for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines()) if "BAD" in ln]
    checker.calls = []
    return checker


GOOD = {"why": "narrow the Optional", "edits": [{"file": "star/m.py", "find": "    return x.upper()  # BAD\n",
                                                 "replace": "    return x.upper() if x is not None else \"\"\n"}]}


def test_type_errors_above_the_baseline_are_fixed_by_her_edits(tmp_path):
    checker = _typed_repo(tmp_path)
    asked = []
    ok, why, rounds = F.fix_types(tmp_path, sys.executable, lambda p: asked.append(p) or json.dumps(GOOD), checker)
    assert ok and why == "narrow the Optional" and rounds == 1
    assert "star/m.py:2:" in asked[0] and "baseline allows 0" in asked[0] and "return x.upper()" in asked[0]
    assert "BAD" not in (tmp_path / "star" / "m.py").read_text(encoding="utf-8")


def test_rounds_recheck_only_the_files_above_the_baseline_and_a_full_run_decides_success(tmp_path):
    checker = _typed_repo(tmp_path)
    (tmp_path / "star" / "other.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "star" / "m.py").write_text("a  # BAD\nb  # BAD\nc  # BAD\n", encoding="utf-8")
    one = {"why": "first", "edits": [{"file": "star/m.py", "find": "a  # BAD", "replace": "a"}]}
    two = {"why": "second", "edits": [{"file": "star/m.py", "find": "b  # BAD", "replace": "b"},
                                      {"file": "star/m.py", "find": "c  # BAD", "replace": "c"},
                                      {"file": "star/other.py", "find": "x = 1", "replace": "x = 1  # BAD"}]}
    fix = {"why": "third", "edits": [{"file": "star/other.py", "find": "x = 1  # BAD", "replace": "x = 1"}]}
    answers = iter([one, two, fix])
    ok, why, rounds = F.fix_types(tmp_path, sys.executable, lambda p: json.dumps(next(answers)), checker)
    assert ok and why == "third" and rounds == 3
    # full, probe, round 1 (m.py only), round 2 (m.py clean -> the full run finds the new error in other.py, 1 above
    # the baseline instead of 2: kept), round 3 (other.py clean -> full run: done)
    assert checker.calls == [None, ["star/m.py"], ["star/m.py"], ["star/m.py"], None, ["star/other.py"], None]


def test_when_per_file_counts_differ_from_the_full_run_every_round_is_a_full_run(tmp_path):
    checker = _typed_repo(tmp_path)

    def odd(tree, python, files=None):          # a checker whose per-file answer is not the full run's
        return checker(tree, python) + ([dict(checker(tree, python)[0], line=9)] if files else [])
    odd_calls = []
    ok, _, rounds = F.fix_types(tmp_path, sys.executable, lambda p: json.dumps(GOOD),
                                lambda t, p, files=None: odd_calls.append(files) or odd(t, p, files))
    assert ok and rounds == 1 and odd_calls == [None, ["star/m.py"], None]


def test_an_ignore_comment_or_no_progress_is_undone_and_she_is_told(tmp_path):
    checker = _typed_repo(tmp_path)
    original = (tmp_path / "star" / "m.py").read_text(encoding="utf-8")
    hide = {"why": "x", "edits": [{"file": "star/m.py", "find": "  # BAD\n", "replace": "  # BAD  # type: ignore\n"}]}
    same = {"why": "x", "edits": [{"file": "star/m.py", "find": "def f(", "replace": "def  f("}]}
    answers, asked = [hide, same, GOOD], []

    def ask(prompt):
        asked.append(prompt)
        if len(asked) == 3:      # the no-progress round was undone before she is asked again
            assert (tmp_path / "star" / "m.py").read_text(encoding="utf-8") == original
        return json.dumps(answers[len(asked) - 1])

    ok, _, rounds = F.fix_types(tmp_path, sys.executable, ask, checker)
    assert ok and rounds == 3
    assert "ignore comment" in asked[1] and "did not reduce" in asked[2]


def test_a_type_fix_that_breaks_the_syntax_is_undone_even_if_the_error_count_drops(tmp_path):
    checker = _typed_repo(tmp_path)          # the stand-in counts BAD lines, so this edit "lowers" the count
    original = (tmp_path / "star" / "m.py").read_text(encoding="utf-8")
    broken = {"why": "x", "edits": [{"file": "star/m.py", "find": "    return x.upper()  # BAD\n",
                                     "replace": "    return x.upper() if x else\n        \"\"\n"}]}
    answers, asked = [broken, GOOD], []

    def ask(prompt):
        asked.append(prompt)
        if len(asked) == 2:
            assert (tmp_path / "star" / "m.py").read_text(encoding="utf-8") == original
        return json.dumps(answers[len(asked) - 1])

    ok, _, rounds = F.fix_types(tmp_path, sys.executable, ask, checker)
    assert ok and rounds == 2 and "syntax error in star/m.py" in asked[1]


def test_the_type_fixer_respects_the_baseline_and_cannot_move_it(tmp_path):
    checker = _typed_repo(tmp_path, {"star/m.py::reportOptionalMemberAccess": 1})
    ok, why, rounds = F.fix_types(tmp_path, sys.executable, lambda p: pytest.fail("nothing is new"), checker)
    assert (ok, rounds) == (False, 0) and "passes locally" in why
    assert F.fix_types(tmp_path, sys.executable, lambda p: "", lambda t, p, files=None: None)[2] == 0   # no npx
    problems = F.apply_edits(tmp_path, [{"file": "scripts/pyright_baseline.json", "find": "1", "replace": "2"}])
    assert problems and "may not edit" in problems[0]


def test_a_type_fix_that_breaks_the_modules_tests_is_not_kept(tmp_path):
    checker = _typed_repo(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_m.py").write_text(
        "from star.m import f\n\n\ndef test_none():\n    assert f(None) == 'none'\n", encoding="utf-8")
    assert F.related_tests(tmp_path, ["star/m.py"]) == ["tests/test_m.py"]
    ok, why, _ = F.fix_types(tmp_path, sys.executable, lambda p: json.dumps(GOOD), checker)
    assert not ok and "tests/test_m.py::test_none" in why


def test_an_old_failure_superseded_by_later_passes_is_not_a_failure(monkeypatch):
    runs = [{"name": "Offline Python checks", "status": "completed", "conclusion": "failure",
             "started_at": "2026-10-27T12:00:00Z", "details_url": "https://x/actions/runs/1/job/11"},
            {"name": "Offline Python checks", "status": "completed", "conclusion": "success",
             "started_at": "2026-11-01T09:00:00Z", "details_url": "https://x/actions/runs/2/job/22"}]
    assert [c["conclusion"] for c in F.latest_runs(runs)] == ["success"]           # Star-AI-Project #700
    monkeypatch.setattr(F, "gh", lambda *a, **k: json.dumps({"check_runs": runs}))
    assert F.failed_logs("abc") == ""
    monkeypatch.setattr(F, "rerun_failed", lambda *a: 0)
    row = F.fix({"headRefOid": "abc", "number": 700, "headRefName": "x"}, "python")
    assert row["result"] == "skip"                    # recorded as tried: no rerun loop every 10 minutes


def test_recording_an_attempt_keeps_a_requeue_made_meanwhile(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "STATE", tmp_path / "tried.json")
    F.STATE.write_text(json.dumps({"o/r#1": "a", "o/r#2": "b"}), encoding="utf-8")
    F.STATE.write_text(json.dumps({"o/r#2": "b"}), encoding="utf-8")       # someone re-queued #1 during her run
    assert F.mark("o/r#3", "c") == {"o/r#2": "b", "o/r#3": "c"}           # #1 stays re-queued


def test_compiler_errors_in_a_file_she_merged_make_her_redo_that_merge(monkeypatch):
    hints = []
    monkeypatch.setattr(F, "resolve_text", lambda path, raw, title, asker=None, hint="":
                        hints.append(hint) or ("fixed\n", ""))
    monkeypatch.setattr(F, "broken", lambda tree, path, text: "")
    monkeypatch.setattr(F, "tidy", lambda tree, path, text: text)
    out = "error[E0063]: missing field `limit` in initializer of `Batch`\n   --> crates/s/src/host.rs:511:31\n"
    results = iter([(False, "", ["s"], out), (True, "", ["s"], "")])
    monkeypatch.setattr(F.rust_fix, "crate_tests", lambda tree, files: next(results))
    errs = F.rust_fix.errors(out)
    assert errs[0]["file"] == "crates/s/src/host.rs"                 # the error points into her merged file (#397)
    assert hints == []                                               # (resolve() wiring is covered by the live run)


def test_both_sides_only_adding_merge_by_code_and_same_spot_only_in_docs():
    base, ours, theirs = "a\nb\nc\n", "a\nX\nb\nc\n", "a\nb\nc\nY\n"
    assert F.both_added(ours, base, theirs, docs=False) == "a\nX\nb\nc\nY\n"        # different places: exact
    same = F.both_added("a\nX\nb\n", "a\nb\n", "a\nY\nb\n", docs=True)
    assert same == "a\nX\nY\nb\n" and F.both_added("a\nX\nb\n", "a\nb\n", "a\nY\nb\n", docs=False) is None
    assert F.both_added("a\nX\n", "a\nb\n", "a\nb\nY\n", docs=True) is None         # an ancestor line went away


def test_brackets_in_strings_comments_and_char_literals_do_not_count():
    rust = "let c = '{'; // a ( here\nfn f<'a>(x: &'a str) -> &'a str { x }\nlet s = r#\"((\"#; let t = \"[\";\n"
    assert F.balance(rust, "x.rs") == (0, 0, 0) and F.balance(rust) != (0, 0, 0)
    assert F.balance("x = '('  # ) [\ny = \"\"\"{\n\"\"\"\n", "a.py") == (0, 0, 0)
    assert F.balance("local s = \"(\" -- {\nlocal t = [[ [ ]]\n", "a.luau") == (0, 0, 0)
    block = ('<<<<<<< HEAD\n    a.push("(");\n||||||| base\n=======\n    b.push("(");\n>>>>>>> origin/main\n')
    good = '    a.push("(");\n    b.push("(");\n'                 # all brackets counted: (0, 2, 0) vs each side (0, 1, 0)
    assert F.slips("x.rs", block, good) == ""
    assert "{}" in F.slips("x.rs", block, '    a.push("(";\n    b.push("(");\n')        # a real lost bracket still is


STUDIO_421 = ("    pub fn gui_event(&mut self, event: GuiEvent) {\n<<<<<<< HEAD\n        if keep(len) {\n"
              "||||||| base\n        if self.run_client {\n=======\n        if self.role != Server {\n>>>>>>> main\n"
              "            self.gui_events.push(event);\n        }\n    }\n")


def test_lines_she_copies_from_around_the_block_are_cut_not_held_against_her():
    block = STUDIO_421.split("{\n", 1)[1].split("            self.gui", 1)[0]
    before, after = "    pub fn gui_event(&mut self, event: GuiEvent) {\n", STUDIO_421.split(">>>>>>> main\n")[1]
    merged = "        if self.role != Server && keep(len) {\n"
    tail = merged + after                                        # her merge, then the rest of the function again
    assert F.echoed(tail, block, before, after) == merged
    assert F.echoed("    /// her redo of the doc comment\n" + before + merged, block,
                    "    /// doc\n>>>>>>> main\n" + before, after) == merged          # after the previous conflict
    assert F.echoed(merged + "        }\n", block, before, after) == merged + "        }\n"   # no real line: kept
    answers = iter([json.dumps({"resolved": tail})])
    got, why = F.resolve_text("h.rs", STUDIO_421, "t", lambda p: next(answers))
    assert why == "" and got == STUDIO_421.split("<<<<<<<")[0] + merged + after
    use = "<<<<<<< HEAD\npub use api::{A, B};\n||||||| base\npub use api::A;\n=======\npub use api::{A, C};\n>>>>>>> m\n"
    assert F.echoed("pub use api{A, B, C};\n", use, "", "", "lib.rs") == "pub use api::{A, B, C};\n"   # #317, #421


def test_the_block_limit_counts_only_the_blocks_she_is_asked_about():
    add = "<<<<<<< HEAD\nfn a{n}() {{}}\n||||||| base\n=======\nfn b{n}() {{}}\n>>>>>>> main\nfn x{n}() {{}}\n"
    text = "".join(add.format(n=n) for n in range(9)) + DIFF3.replace("keep", "kept")
    answers = iter([json.dumps({"resolved": "fn kept() {}\nfn pr_added() {}\nfn main_added() {}\n"})])
    merged, why = F.resolve_text("s.rs", text, "t", lambda p: next(answers))          # Studio #412: 9 blocks
    assert why == "" and merged.count("fn a") == merged.count("fn b") == 9 and "main_added" in merged
    many = "".join(DIFF3.replace("keep", f"k{n}") for n in range(9))
    assert "9 of 9 conflict blocks need her" in F.resolve_text("s.rs", many, "t", lambda p: 1 / 0)[1]


def test_code_one_side_deleted_and_the_other_changed_is_a_persons_call():
    text = "<<<<<<< HEAD\nfn a() { new(); }\n||||||| base\nfn a() { old(); }\n=======\n>>>>>>> main\n"
    with patch.object(F, "BASE", "main"):
        merged, why = F.resolve_text("g.rs", text, "t", lambda p: pytest.fail("no model call"))   # Studio #401
    assert merged is None and "main deleted these lines and the PR changed them" in why
    assert "no conflict lines" in F.resolve_text("classes.rs", "fn a() {}\n", "t", lambda p: 1 / 0)[1]


def _repo(tmp_path):
    def git(*a):
        return subprocess.run(["git", *F.IDENTITY, *a], cwd=tmp_path, capture_output=True, text=True)
    git("init", "-q", "-b", "main")
    git("config", "core.autocrlf", "false")
    return git


CODE = "".join(f"fn f{i}() {{\n    step({i});\n}}\n\n" for i in range(8))


def _split(tmp_path, moved: str):
    """main moves classes.rs into classes/mod.rs among much new code (too little alike for git to see a rename), the
    PR changes f3 in classes.rs: modify/delete."""
    moved = "".join(f"pub fn new{i}() -> u32 {{\n    {i}\n}}\n\n" for i in range(40)) + moved
    git = _repo(tmp_path)
    (tmp_path / "classes.rs").write_text(CODE, encoding="utf-8")
    git("add", "-A"), git("commit", "-qm", "base")
    git("checkout", "-qb", "pr")
    (tmp_path / "classes.rs").write_text(CODE.replace("step(3);", "step(3);\n    more(3);"), encoding="utf-8")
    git("commit", "-qam", "pr changes f3")
    git("checkout", "-q", "main"), git("rm", "-q", "classes.rs")
    (tmp_path / "classes").mkdir()
    (tmp_path / "classes" / "mod.rs").write_text(moved, encoding="utf-8")
    git("add", "-A"), git("commit", "-qm", "main splits it")
    git("update-ref", "refs/remotes/origin/main", "main")
    git("checkout", "-q", "pr"), git("-c", "merge.conflictStyle=diff3", "merge", "--no-commit", "origin/main")
    return git


def test_a_change_to_a_file_the_base_only_moved_is_applied_where_the_code_now_is(tmp_path):
    moved = "// the classes, one module now\n" + CODE.replace("fn f0", "pub fn f0") + "fn extra() {}\n"
    git = _split(tmp_path, moved)
    with patch.object(F, "BASE", "main"):
        why, wrote = F.whole_file(tmp_path, "classes.rs", (tmp_path / "classes.rs").read_text(encoding="utf-8"))
    assert why == "" and wrote == ["classes/mod.rs"]                 # Studio #421/#275 shape, but a pure move
    got = (tmp_path / "classes" / "mod.rs").read_text(encoding="utf-8")
    assert "    step(3);\n    more(3);\n" in got and "pub fn f0" in got and "fn extra" in got
    assert not (tmp_path / "classes.rs").exists() and git("diff", "--name-only", "--diff-filter=U").stdout == ""


def test_a_change_to_code_the_base_rewrote_is_refused_with_where_it_went(tmp_path):
    _split(tmp_path, CODE.replace("step(3);", "step(3, ctx);"))         # main also changed f3: no exact place
    with patch.object(F, "BASE", "main"):
        why, wrote = F.whole_file(tmp_path, "classes.rs", (tmp_path / "classes.rs").read_text(encoding="utf-8"))
    assert wrote == [] and "deleted on main and changed by this PR (modify/delete)" in why
    assert "(classes/mod.rs)" in why and "only 0 of the 1 hunks" in why and "a person's call" in why
    assert (tmp_path / "classes.rs").exists()                          # nothing written: resolve() aborts the merge


def test_a_file_without_conflict_blocks_is_not_a_whole_file_case_unless_git_wrote_none(tmp_path):
    assert F.whole_file(tmp_path, "a.rs", "<<<<<<< HEAD\na\n||||||| b\n=======\nb\n>>>>>>> main\n") == (None, [])
    git = _repo(tmp_path)
    (tmp_path / "logo.bin").write_bytes(b"\x00\x01base")
    git("add", "-A"), git("commit", "-qm", "base")
    git("checkout", "-qb", "pr")
    (tmp_path / "logo.bin").write_bytes(b"\x00\x01pr")
    git("commit", "-qam", "pr")
    git("checkout", "-q", "main")
    (tmp_path / "logo.bin").write_bytes(b"\x00\x01main")
    git("commit", "-qam", "main"), git("checkout", "-q", "pr"), git("merge", "main")
    why, wrote = F.whole_file(tmp_path, "logo.bin", "")
    assert wrote == [] and "binary file" in why and "a person's call" in why


def test_hunks_are_read_from_a_unified_diff():
    diff = ("diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1,3 +1,3 @@ fn a\n a\n-b\n+B\n c\n"
            "@@ -9,2 +9,3 @@\n x\n y\n+z\n\\ No newline at end of file\n")
    assert F.hunks(diff) == [("a\nb\nc\n", "a\nB\nc\n"), ("x\ny\n", "x\ny\nz\n")]
    files = {"m.rs": "a\nb\nc\n", "n.rs": "x\ny\nx\ny\n"}
    assert F.place(F.hunks(diff), files) == ({}, 1)                   # x/y stands twice: no reliable place
    assert F.place(F.hunks(diff)[:1], files) == ({"m.rs": "a\nB\nc\n"}, 1)


def test_a_big_block_is_shown_with_less_code_around_it_before_it_is_refused():
    side = "".join(f"    let v{i} = {i};\n" for i in range(55))
    far = "".join(f"// context line {i} padding padding padding\n" for i in range(60))
    text = (far + f"<<<<<<< pr\n    a();\n{side}||||||| base\n{side}=======\n    b();\n{side}>>>>>>> main\n"
            + far.replace("context", "after"))
    shown = []
    answer = json.dumps({"resolved": "    a();\n    b();\n" + side})
    merged, why = F.resolve_text("x.rs", text, "t", lambda p: shown.append(p) or answer)
    assert why == "" and len(shown) == 1 and "context line 0 " not in shown[0] and "context line 59" in shown[0]
    assert "after line 0 " in shown[0] and "after line 59" not in shown[0]


def test_a_rejected_file_is_redone_with_the_mechanical_blocks_kept(monkeypatch):
    text = ("<<<<<<< HEAD\nfn a() {}\n||||||| base\n=======\nfn b() {}\n>>>>>>> main\nfn x() {}\n"
            "<<<<<<< HEAD\n    y(1);\n||||||| base\n    y(0);\n=======\n    y(2);\n>>>>>>> main\n")
    answers = iter([json.dumps({"resolved": "    y(1)?\n"}), json.dumps({"resolved": "    y(3);\n"})])
    asked = []
    monkeypatch.setattr(F, "broken", lambda tree, path, text: "rustfmt rejects it" if "?" in text else "")
    merged, why = F.merge_file(Path("."), "s.rs", text, "t", lambda p: asked.append(p) or next(answers))
    assert why == "" and merged == "fn a() {}\nfn b() {}\nfn x() {}\n    y(3);\n" and len(asked) == 2
    assert "conflict 2 of 2" in asked[1] and "rustfmt rejects it" in asked[1]       # only her block again (#208)


def test_an_empty_pr_side_is_read_as_empty_not_as_the_ancestor():
    block = "<<<<<<< HEAD\n||||||| base\nfn old() {}\n=======\nfn old() { changed(); }\n>>>>>>> main\n"
    assert F.sides(block) == ("", "fn old() {}", "fn old() { changed(); }\n")          # Studio #275 instance.rs
    with patch.object(F, "BASE", "main"):
        why = F.resolve_text("i.rs", block, "t", lambda p: pytest.fail("no model call"))[1]
    assert "the PR deleted these lines and main changed them" in why


def test_her_dropped_macro_bang_and_the_blank_line_before_a_copy_are_put_right():
    block = ("<<<<<<< HEAD\n        let a = A { b: 1, c: true };\n||||||| base\n        let a = A { b: 1 };\n=======\n"
             "        let a = A::new(1);\n>>>>>>> main\n")
    after = "        assert_eq!(f(&[a]), Err(E::Cycle));\n    }\n"
    answer = "\n        let a = A::new(1);\n        assert_eq(f(&[a]), Err(E::Cycle));\n    }\n"   # Studio #275 shape
    got = F.echoed(answer.replace("assert_eq(", "assert_eq!("), block, "", after, "r.rs")
    assert got == "        let a = A::new(1);\n"
    assert F.echoed("        assert_eq(x, 1);\n", block, "", after, "r.rs") == "        assert_eq!(x, 1);\n"
    assert F.echoed("        f(x);\n", block, "", after, "r.rs") == "        f(x);\n"     # f( is a call in the code


def test_a_line_copied_from_around_the_block_is_refused_and_a_name_imported_twice_too():
    block = "<<<<<<< HEAD\n//! PR note.\n||||||| base\n=======\n//! main note.\n>>>>>>> main\n"
    after = "#![warn(missing_docs)]\n\npub use project::ProjectConfig;\n"
    merged = "//! PR note.\n//! main note.\n"
    assert F.slips("lib.rs", block, merged, "", after) == ""
    assert "copies a line" in F.slips("lib.rs", block, merged + "pub use project::ProjectConfig;\n", "", after)  # #210
    two = ("pub use game::{\n    FrameOutput, Game, TICK,\n};\n#[cfg(feature = \"presentation\")]\n"
           "pub use game::{FrameOutput, Game};\n#[cfg(a)]\nuse x::Y;\n#[cfg(not(a))]\nuse z::Y;\n"
           "fn f() {\n    use std::path::PathBuf;\n}\nuse std::path::PathBuf;\n")
    assert F.double_uses(two) == {"FrameOutput", "Game"}


# The React job's log as GitHub serves it (#857, 2026-11-01): tsc stops the `&&` chain, so vitest never ran there.
REACT_LOG = (
    "2026-11-01T04:54:29.1022341Z ##[group]Run sh scripts/ci_heavy.sh sh -c 'npm run typecheck --prefix frontend && "
    "npm run test --prefix frontend && npm run build --prefix frontend'\n"
    "2026-11-01T04:54:29.1301146Z > star-intelligence-interface@2.0.0 typecheck\n"
    "2026-11-01T04:54:29.1301822Z > tsc -b\n"
    "2026-11-01T04:54:31.5403118Z ##[error]src/SettingsPage.tsx(27,2): error TS2300: Duplicate identifier 'companions'.\n"
    "2026-11-01T04:54:31.5408811Z ##[error]src/SettingsPage.tsx(29,2): error TS2300: Duplicate identifier 'companions'.\n"
    "2026-11-01T04:54:31.5605233Z ##[error]Process completed with exit code 1.\n")
# vitest 5's output for a failing test (captured from `npm run test --prefix frontend` on star/next with a planted bug).
VITEST_OUT = """ ❯ src/activity.test.ts (18 tests | 1 failed) 38ms
     × settles open and queued steps truthfully when a run ends 7ms

 Test Files  1 failed | 1 passed (2)
      Tests  1 failed | 21 passed (22)

⎯⎯⎯⎯⎯⎯⎯ Failed Tests 1 ⎯⎯⎯⎯⎯⎯⎯

 FAIL  src/activity.test.ts > activity timeline is driven only by backend events > settles open and queued steps \
truthfully when a run ends
AssertionError: expected 'Stopped after 9s' to be 'Stopped after 9.0s' // Object.is equality

 ❯ src/activity.test.ts:155:37
    154|     expect(stateWord(stopped.steps[1])).toBe('Not started')
    155|     expect(headline(stopped, 9000)).toBe('Stopped after 9.0s')
       |                                     ^
    156|     expect(states(settleRun(live, 'failed', 9000))[0]).toBe('Evidence:…

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[1/1]⎯
"""


def test_the_react_jobs_tsc_and_vitest_failures_are_read_from_the_log():
    got = F.frontend_failures(REACT_LOG)
    assert got is not None
    assert [(e["file"], e["line"], e["code"]) for e in got["tsc"]] == [
        ("frontend/src/SettingsPage.tsx", 27, "TS2300"), ("frontend/src/SettingsPage.tsx", 29, "TS2300")]
    assert got["tsc"][0]["message"] == "Duplicate identifier 'companions'." and got["vitest"] == []
    pretty = F.frontend_failures("src/App.tsx:12:5 - error TS2322: Type 'string' is not assignable to type 'number'.\n")
    assert pretty is not None and pretty["tsc"][0]["line"] == 12                 # tsc --pretty form too
    tests = F.vitest_sections(VITEST_OUT)
    assert [(t["file"], t["test"].split(" > ")[-1]) for t in tests] == [
        ("frontend/src/activity.test.ts", "settles open and queued steps truthfully when a run ends")]
    assert "Stopped after 9.0s" in tests[0]["section"] and "[1/1]" not in tests[0]["section"]
    assert F.frontend_failures("FAILED tests/test_x.py::test_y - assert 1 == 2\n") is None


def _front_repo(tmp_path):
    src = tmp_path / "frontend" / "src"
    src.mkdir(parents=True)
    (src / "activity.ts").write_text(
        "export function headline(run: Run, now: number): string {\n"
        "  const time = formatElapsed(runElapsed(run, now), run.outcome)  // BAD\n"
        "  return 'Stopped after ' + time  // WRONG\n}\n", encoding="utf-8")
    (src / "activity.test.ts").write_text("expect(headline(stopped, 9000)).toBe('Stopped after 9.0s')\n",
                                          encoding="utf-8")
    calls = []

    def runner(tree, files):                 # tsc + vitest stand-in: BAD = a tsc error, WRONG = a failing test
        calls.append(files)
        text = (tree / "frontend" / "src" / "activity.ts").read_text(encoding="utf-8")
        return {"tsc": [{"file": "frontend/src/activity.ts", "line": 2, "code": "TS2345",
                         "message": "Argument of type 'RunOutcome' is not assignable"}] * text.count("BAD"),
                "vitest": [{"file": "frontend/src/activity.test.ts", "test": "headline",
                            "section": VITEST_OUT.split(" FAIL  ", 1)[1]}] * text.count("WRONG")}
    return runner, calls


FIX_BAD = {"file": "frontend/src/activity.ts", "find": "run.outcome)  // BAD", "replace": "run.outcome === 'running')"}
FIX_WRONG = {"file": "frontend/src/activity.ts", "find": "  return 'Stopped after ' + time  // WRONG",
             "replace": "  return 'Stopped after ' + time"}


def _answers(*answers):
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return json.dumps(answers[len(asked) - 1])
    return ask, asked


def test_her_react_rounds_must_lower_the_errors_and_the_whole_suite_runs_at_the_end(tmp_path):
    runner, calls = _front_repo(tmp_path)
    ask, asked = _answers({"why": "x", "edits": [{"file": "frontend/src/activity.ts", "find": "string {",
                                                   "replace": "string  {"}]},
                          {"why": "a RunOutcome went where a boolean belongs", "edits": [FIX_BAD]},
                          {"why": "keep the decimal", "edits": [FIX_WRONG]})
    ok, why, rounds = F.fix_frontend(tmp_path, ask, runner, title="t")
    assert ok and rounds == 3 and why == "keep the decimal"
    assert "frontend/src/activity.ts(2): error TS2345" in asked[0] and "2 in all" in asked[0]
    assert "string {" in (tmp_path / "frontend" / "src" / "activity.ts").read_text(encoding="utf-8")   # undone
    assert "did not lower the errors (2 -> 2)" in asked[1] and "were kept: 2 -> 1" in asked[2]
    assert calls[0] is None and calls[-1] is None and calls[1] == ["frontend/src/activity.test.ts"]  # full, few, full


def test_she_may_not_silence_errors_or_edit_the_tests_and_configs(tmp_path):
    runner, _ = _front_repo(tmp_path)
    ask, asked = _answers(
        {"why": "x", "edits": [{"file": "frontend/src/activity.ts", "find": "  const time",
                                "replace": "  // @ts-ignore\n  const time"}]},
        {"why": "x", "edits": [{"file": "frontend/src/activity.ts", "find": "run.outcome)",
                                "replace": "run.outcome as any)"}]},
        {"why": "x", "edits": [{"file": "frontend/src/activity.test.ts", "find": "9.0s", "replace": "9s"}]},
        {"why": "y", "edits": [FIX_BAD, FIX_WRONG]})
    ok, _, rounds = F.fix_frontend(tmp_path, ask, runner)
    assert ok and rounds == 4
    assert "silenced an error" in asked[1] and "silenced an error" in asked[2] and "may not edit" in asked[3]
    assert (tmp_path / "frontend" / "src" / "activity.test.ts").read_text(encoding="utf-8").endswith("9.0s')\n")
    for path in ("frontend/tsconfig.json", "frontend/package.json", "frontend/vite.config.ts",
                 "frontend/src/test-animation-event.ts", "frontend/src/a.test.tsx", "frontend/package-lock.json"):
        assert F.FRONT_SPEC.match(path), path
    assert not F.FRONT_SPEC.match("frontend/src/activity.ts")


def test_round_zero_and_a_fix_that_breaks_another_test(tmp_path):
    runner, _ = _front_repo(tmp_path)
    assert F.fix_frontend(tmp_path, lambda p: pytest.fail("cannot run"), lambda t, f: None)[::2] == (False, 0)
    clean = {"tsc": [], "vitest": []}
    assert F.fix_frontend(tmp_path, lambda p: pytest.fail("passes"), lambda t, f: clean)[::2] == (True, 0)
    other = {"tsc": [], "vitest": [{"file": "frontend/src/other.test.tsx", "test": "renders", "section": ""}]}

    def full(tree, files):                   # the whole suite at the end finds a test her fix broke
        fixed = "WRONG" not in (tree / "frontend" / "src" / "activity.ts").read_text(encoding="utf-8")
        return other if files is None and fixed else runner(tree, files)

    ok, why, _ = F.fix_frontend(tmp_path, lambda p: json.dumps({"why": "y", "edits": [FIX_BAD, FIX_WRONG]}), full)
    assert not ok and "frontend/src/other.test.tsx > renders" in why


def test_a_find_copied_with_diff_markers_or_listing_numbers_is_read_as_the_file_has_it(tmp_path):
    _front_repo(tmp_path)
    f, line2 = "frontend/src/activity.ts", "  const time = formatElapsed(runElapsed(run, now), run.outcome)  // BAD"
    from_diff = {"file": f, "find": "-  const time = 0\n+" + line2, "replace": "  const time = 1"}   # live trial 1
    assert F.as_in_file(tmp_path, from_diff)["find"] == line2
    numbered = {"file": f, "find": "   2: " + line2 + "\n    3:  return 'Stopped after ' + time  // WRONG",
                "replace": "    3:   return 'x'"}                                                  # seen on #857
    got = F.as_in_file(tmp_path, numbered)
    assert got["find"].startswith("  const time") and got["find"].endswith("// WRONG") and got["replace"] == "  return 'x'"
    assert F.as_in_file(tmp_path, {"file": f, "find": "nothing like it", "replace": ""})["find"] == "nothing like it"


def test_she_sees_the_source_of_what_the_failing_assertion_calls(tmp_path):
    _front_repo(tmp_path)
    (tmp_path / "frontend" / "src" / "time.ts").write_text(
        "export function formatElapsed(ms: number, live = false): string {\n  return live ? 's' : '0.0s'\n}\n"
        "const local = 1\n", encoding="utf-8")
    text = "\n".join(F.ts_definitions(tmp_path, VITEST_OUT.split(" FAIL  ", 1)[1]))
    assert "export function headline" in text and "export function formatElapsed" in text     # and what it calls
    assert text.index("headline") < text.index("formatElapsed") and "const local" not in text


def test_a_react_failure_goes_to_her_frontend_lane_not_a_rerun(monkeypatch):
    monkeypatch.setattr(F, "failed_logs", lambda sha: F.STAMP.sub("", REACT_LOG))
    monkeypatch.setattr(F, "sh", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    monkeypatch.setattr(F, "gh", lambda *a, **k: "")
    reruns = []
    monkeypatch.setattr(F, "rerun_failed", lambda *a: reruns.append(a) or 1)
    pr = {"headRefOid": "abc", "number": 857, "headRefName": "x"}
    monkeypatch.setattr(F, "fix_frontend", lambda tree, asker, **k: (False, "the React checks cannot run here", 0))
    row = F.fix(pr, "python")
    assert row["result"] == "failed" and row["kind"] == "frontend" and not reruns
    assert row["why"].startswith("React UI fails: frontend/src/SettingsPage.tsx(27): TS2300 Duplicate identifier")
    monkeypatch.setattr(F, "fix_frontend", lambda tree, asker, **k: (True, "passes locally", 0))
    assert F.fix(pr, "python")["result"] == "flaky-rerun" and reruns          # vitest under load: one rerun
    monkeypatch.setattr(F, "fix_frontend", lambda tree, asker, **k: (True, "drop the doubled prop", 1))
    row = F.fix(pr, "python", dry=True)
    assert row["result"] == "fixed" and row["tests"] == ["tsc", "vitest"]


def test_the_node_modules_link_goes_and_the_shared_install_stays(tmp_path):
    shared = tmp_path / "cache" / "node_modules"
    (shared / "react").mkdir(parents=True)
    (tmp_path / "frontend").mkdir()

    def runner(tree, files):
        F._link(shared, tree / "frontend" / "node_modules")
        return {"tsc": [], "vitest": []}

    assert F.fix_frontend(tmp_path, lambda p: "", runner)[::2] == (True, 0)
    assert not (tmp_path / "frontend" / "node_modules").exists() and (shared / "react").is_dir()
