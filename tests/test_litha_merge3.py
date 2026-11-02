import json

import pytest

from litha import merge3
from litha import pr_fixer as F

STUDIO_255 = ("    let x = 1;\n<<<<<<< HEAD\n    let callback = lua.create_function(f)?;\n    // Recognize Rust errors.\n"
              "    let guard: Function = lua\n||||||| base\n    // The guard runs every thread.\n"
              "    let guard: Function = lua\n=======\n    // The guard runs every thread.\n"
              "    let (guard, bind_guard): (Function, Function) = lua\n>>>>>>> origin/main\n        .load(G)\n")


def test_edits_on_neighbouring_lines_merge_without_her_model():
    merged, why = F.resolve_text("t.rs", STUDIO_255, "t", lambda p: pytest.fail("no model call"))   # Studio #255
    assert why == "" and merged == ("    let x = 1;\n    let callback = lua.create_function(f)?;\n    // Recognize Rust "
                                    "errors.\n    let (guard, bind_guard): (Function, Function) = lua\n        .load(G)\n")
    assert merge3.merge("y(1);\n", "y(0);\n", "y(2);\n") is None                     # a real overlap stays hers
    assert merge3.merge("a\nX\nb\n", "a\nb\n", "a\nY\nb\n") is None                  # same-place additions too
    assert merge3.merge("a\nB\nc\n", "a\nb\nc\n", "a\nB\nc\nd\n") == ["a\n", "B\n", "c\n", "d\n"]   # same edit once


def test_only_the_overlapping_part_of_a_block_goes_to_her():
    text = ("fn f() {\n<<<<<<< HEAD\n    a(1);\n    b();\n    c();\n    d(1);\n||||||| base\n    a(0);\n    b();\n"
            "    c();\n    d(0);\n=======\n    a(0);\n    b();\n    c();\n    d(2);\n    e();\n>>>>>>> origin/main\n}\n")
    asked = []
    answer = json.dumps({"resolved": "    d(3);\n    e();\n"})
    merged, why = F.resolve_text("x.rs", text, "t", lambda p: asked.append(p) or answer)
    assert why == "" and merged == "fn f() {\n    a(1);\n    b();\n    c();\n    d(3);\n    e();\n}\n"
    assert len(asked) == 1 and "    d(1);\n||||||| base\n    d(0);\n=======\n    d(2);\n    e();\n>>>>>>>" in asked[0]
    assert "<<<<<<< HEAD\n    a(1)" not in asked[0]                         # the merged lines are context only
    redo = iter([json.dumps({"resolved": "    a(1);\n    b();\n    c();\n    d(3);\n    e();\n"})])
    assert F.resolve_text("x.rs", text, "t", lambda p: next(redo), hint="x\n")[0] == merged   # a redo: git's block


def test_whitespace_only_sides_and_use_lists_merge_by_rule():
    assert merge3.formatting_only("f(a,\n  b)\n", "f(a, b)\n", "g(a, b)\n") == "g(a, b)\n"
    assert merge3.formatting_only("f(a, c)\n", "f(a, b)\n", "g(a, b)\n") is None
    block = ("<<<<<<< HEAD\nuse crate::classes::{self, PropDef, class_def, find_property};\n||||||| base\n"
             "use crate::classes::{self, class_def, find_property};\n=======\n"
             "use crate::classes::{self, ClassFlags, registry};\n>>>>>>> main\n")          # Studio #412 instance.rs
    merged, why = F.resolve_text("i.rs", block, "t", lambda p: pytest.fail("no model call"))
    assert why == "" and merged == "use crate::classes::{self, PropDef, ClassFlags, registry};\n"
    assert merge3.use_lists("use a::b;\nfn x() {}\n", "use a::b;\n", "use a::c;\n") is None   # not only imports


def test_her_bracket_echo_of_the_line_after_is_cut_and_misses_are_named():
    text = ("impl A {\n    fn f(&self) {\n<<<<<<< HEAD\n        if a {\n            x();\n||||||| base\n        if b {\n"
            "            x();\n=======\n        if c {\n            y();\n>>>>>>> main\n        }\n    }\n}\n")
    answers = iter([json.dumps({"resolved": "        if a && c {\n            x();\n            y();\n        }\n"})])
    merged, why = F.resolve_text("a.rs", text, "t", lambda p: next(answers))      # one try: the `}` was a copy
    assert why == "" and merged.count("        }\n") == 1 and "if a && c" in merged
    assert "1 `}` too many" in F.deficit((1, 0, 0), (0, 0, 0)) and "lost 2 `)`" in F.deficit((0, 0, 0), (0, 2, 0))


def test_she_sees_earlier_blocks_merged_and_later_ones_as_a_note():
    two = ("fn f() {\n<<<<<<< HEAD\n    y(1);\n||||||| base\n    y(0);\n=======\n    y(2);\n>>>>>>> main\n    mid();\n"
           "<<<<<<< HEAD\n    z(1);\n||||||| base\n    z(0);\n=======\n    z(2);\n>>>>>>> main\n}\n")
    asked = []
    answers = iter([json.dumps({"resolved": "    y(3);\n"}), json.dumps({"resolved": "    z(3);\n"})])
    merged, why = F.resolve_text("x.rs", two, "t", lambda p: asked.append(p) or next(answers))   # Studio #174 shape
    assert why == "" and merged == "fn f() {\n    y(3);\n    mid();\n    z(3);\n}\n"
    assert "(conflict 2, merged on its own)" in asked[0] and "z(1)" not in asked[0]
    assert "    y(3);\n    mid();\n<<<<<<< HEAD\n    z(1);" in asked[1] and "y(1)" not in asked[1]


def test_tests_merge_only_by_rule_ci_never_and_the_file_limit_counts_her_files():
    add = "<<<<<<< HEAD\n  - run: a\n||||||| base\n=======\n  - run: b\n>>>>>>> main\n"
    hard = "<<<<<<< HEAD\n  - run: a\n||||||| base\n  - run: x\n=======\n  - run: b\n>>>>>>> main\n"
    assert F.triage(["tests/test_a.py"], {"tests/test_a.py": add}) == ""
    assert "need a judgement" in F.triage(["tests/test_a.py"], {"tests/test_a.py": hard})
    assert "CI workflows" in F.triage([".github/workflows/ci.yml"], {".github/workflows/ci.yml": add})  # AGENTS.md
    files = {f"src/m{i}.rs": add for i in range(7)} | {"src/hard.rs": hard}
    assert F.triage(list(files), files) == ""                                  # 8 files, 1 needs her
    many = {f"src/h{i}.rs": hard for i in range(6)}
    assert "6 files need her model" in F.triage(list(many), many)
    with pytest.raises(ValueError):
        F.mechanical_only("prompt")
    assert F.guarded(".github/workflows/ci.yml") and not F.guarded("crates/a/tests/t.rs")


def test_layout_is_not_meaning_where_indentation_or_strings_matter():
    """Litha's review of #912: a line moved into an `if` (Python, YAML) and a changed string are real changes."""
    base, moved, other = "if x:\n    a()\nb()\n", "if x:\n    a()\n    b()\n", "if x:\n    a()\nc()\n"
    assert merge3.formatting_only(moved, base, other, "m.py") is None
    assert merge3.formatting_only("k:\n  v: 1\n", "k:\nv: 1\n", "k:\nw: 1\n", "c.yaml") is None
    assert merge3.formatting_only('let s = "a  b";\n', 'let s = "a b";\n', 'let t = "a b";\n', "x.rs") is None
    assert merge3.formatting_only("f(a,\n  b)\n", "f(a, b)\n", "g(a, b)\n", "x.rs") == "g(a, b)\n"
    assert merge3.formatting_only("x = 1   \n", "x = 1\n", "y = 1\n", "m.py") == "y = 1\n"   # trailing spaces only
