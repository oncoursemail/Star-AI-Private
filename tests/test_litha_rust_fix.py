from __future__ import annotations

import json

import litha.rust_fix as R

LOG = """##[group]Run cargo fmt --check
##[group]Run cargo test -p metallic_runtime --no-default-features --lib --test simulation -j 4 -- --test-threads=1
   Compiling metallic_runtime v0.1.0
error[E0432]: unresolved imports `metallic_runtime::FrameInput`, `metallic_runtime::Game`
 --> crates\\metallic_runtime\\tests\\camera_api.rs:4:24
  |
4 | use metallic_runtime::{FrameInput, Game};
error[E0609]: no field `scripts` on type `&Game`
   --> crates/metallic_runtime/src/game.rs:126:14
error: could not compile `metallic_runtime` (test "camera_api") due to 2 previous errors
##[group]Run cargo clippy --workspace --all-targets -- -D warnings
##[group]Run cargo nextest run --workspace --profile ci
##[group]Run cargo deny check licenses
"""


def test_rustc_errors_and_the_ci_commands_are_read_from_the_log():
    assert R.errors(LOG) == [
        {"error": "error[E0432]: unresolved imports `metallic_runtime::FrameInput`, `metallic_runtime::Game`",
         "file": "crates/metallic_runtime/tests/camera_api.rs", "line": 4},
        {"error": "error[E0609]: no field `scripts` on type `&Game`", "file": "crates/metallic_runtime/src/game.rs",
         "line": 126}]
    assert R.checks(LOG) == [
        ["fmt", "--check"],
        ["test", "--no-run", "-p", "metallic_runtime", "--no-default-features", "--lib", "--test", "simulation", "-j", "4"],
        ["clippy", "--workspace", "--all-targets", "--", "-D", "warnings"],
        ["test", "--no-run", "--workspace"]]                      # nextest: compile the tests; deny is not hers


def test_her_edits_may_not_remove_tests_or_assertions(tmp_path):
    (tmp_path / "t.rs").write_text("#[test]\nfn a() {\n    assert_eq!(f(), 1);\n}\n", encoding="utf-8")
    assert "removes a test" in R.apply(tmp_path, [{"file": "t.rs", "find": "    assert_eq!(f(), 1);\n",
                                                   "replace": ""}])[0]
    assert R.apply(tmp_path, [{"file": "t.rs", "find": "#[test]\n", "replace": "#![cfg(feature = \"game\")]\n#[test]\n"}]) == []
    assert R.apply(tmp_path, [{"file": "src/../../x.rs", "find": "a", "replace": "b"}])[0].endswith("may not edit this file")


def test_repair_loops_until_the_same_checks_pass(tmp_path, monkeypatch):
    (tmp_path / "game.rs").write_text("fn f(g: &Game) {\n    g.scripts.run();\n}\n", encoding="utf-8")
    runs = []

    def fake_run(tree, args, timeout=0):
        runs.append(args)
        text = (tree / "game.rs").read_text(encoding="utf-8")
        if args[0] == "test" and "g.scripts" in text:
            return False, "error[E0609]: no field `scripts` on type `&Game`\n --> game.rs:2:7\n"
        return True, ""

    monkeypatch.setattr(R, "run", fake_run)
    asked = []
    answer = {"why": "the field moved", "edits": [{"file": "game.rs", "find": "    g.scripts.run();\n",
                                                    "replace": "    g.host().scripts.run();\n"}]}
    ok, why = R.repair(tmp_path, "o/r", "t", LOG.split("##[group]Run cargo clippy")[0],
                       lambda p: asked.append(p) or json.dumps(answer))
    assert ok and why.startswith("the field moved (checked: ") and "1 round" in why and len(asked) == 1
    assert "game.rs:2" in asked[0] and "2:     g.scripts.run();" in asked[0]       # the real code, numbered
    assert ["fmt"] in runs                                                         # formatting fixed without her
    ok, why = R.repair(tmp_path, "o/r", "t", "no cargo here", lambda p: "{}")
    assert not ok and "no cargo command" in why


def test_the_repos_clippy_steps_run_after_her_fix_too(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("steps:\n  - run: cargo fmt --check\n  - run: cargo clippy --workspace --all-targets -- -D "
                               "warnings\n", encoding="utf-8")
    assert R.later_checks(tmp_path) == [["clippy", "--workspace", "--all-targets", "--", "-D", "warnings"]]
