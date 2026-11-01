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


def test_a_pyright_gate_failure_is_reported_not_rerun(monkeypatch):
    log = ("Python types\tCheck\t2026-11-01T07:50:00Z New pyright errors (fix them; the baseline only shrinks):\n"
           "Python types\tCheck\t2026-11-01T07:50:00Z   litha/pr_fixer.py:411: No overloads for \"run\" [reportCallIssue]\n")
    monkeypatch.setattr(F, "failed_logs", lambda sha: log)
    monkeypatch.setattr(F, "rerun_failed", lambda *a: pytest.fail("a type error is not flaky"))
    row = F.fix({"headRefOid": "abc", "number": 848, "headRefName": "x"}, "python")
    assert row["result"] == "failed" and row["kind"] == "types" and row["why"].startswith("new pyright errors: litha/pr_fixer.py:411: No overloads")


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


def test_mark_serializes_concurrent_attempts(tmp_path, monkeypatch):
    """Parallel runs must not lose updates or leave invalid JSON behind."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    monkeypatch.setattr(F, "STATE", tmp_path / "tried.json")
    barrier = Barrier(12)

    def attempt(index):
        barrier.wait()
        return F.mark(f"owner/repo#{index}", str(index))

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(attempt, range(12)))
    assert json.loads(F.STATE.read_text(encoding="utf-8")) == {
        f"owner/repo#{index}": str(index) for index in range(12)
    }


def test_mark_rejects_corrupt_state_without_overwriting(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "STATE", tmp_path / "tried.json")
    F.STATE.write_text('{"queued":', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        F.mark("owner/repo#1", "head")
    assert F.STATE.read_text(encoding="utf-8") == '{"queued":'
    F.STATE.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid PR-fixer state"):
        F.mark("owner/repo#2", "head")
    assert F.STATE.read_text(encoding="utf-8") == "[]"


def test_mark_atomic_replace_failure_preserves_state(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "STATE", tmp_path / "tried.json")
    original = '{"requeued":"head"}'
    F.STATE.write_text(original, encoding="utf-8")

    def fail_replace(*_args):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(F.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated rename failure"):
        F.mark("another", "new-head")
    assert F.STATE.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob(".tried-*.json")) == []


def test_mark_serializes_concurrent_processes(tmp_path, monkeypatch):
    """Independent operating-system processes share the same attempt-state lock."""
    monkeypatch.setattr(F, "STATE", tmp_path / "tried.json")
    code = (
        "from pathlib import Path; import sys; import litha.pr_fixer as fixer; "
        "fixer.STATE = Path(sys.argv[1]); fixer.mark(sys.argv[2], sys.argv[3])"
    )
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(F.STATE), f"repo#{i}", str(i)],
            cwd=Path(__file__).resolve().parents[1],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for i in range(6)
    ]
    for proc in procs:
        _out, err = proc.communicate(timeout=30)
        assert proc.returncode == 0, err
    assert json.loads(F.STATE.read_text(encoding="utf-8")) == {
        f"repo#{i}": str(i) for i in range(6)
    }
