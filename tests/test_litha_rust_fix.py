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


def test_a_ci_command_with_its_own_jobs_flag_is_not_given_a_second_one(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "away", lambda: False)
    seen = []
    monkeypatch.setattr(R.subprocess, "run", lambda cmd, **k: seen.append(cmd) or
                        type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    R.run(tmp_path, ["test", "--no-run", "-p", "x", "-j", "4"])
    R.run(tmp_path, ["clippy", "--all-targets", "--", "-D", "warnings"])
    assert seen[0][1:].count("-j") == 1                     # cargo refuses a second --jobs (seen on Studio #484)
    assert seen[1][1:] == ["clippy", "--all-targets", "-j", "4", "--", "-D", "warnings"]
    monkeypatch.setattr(R, "away", lambda: True)                 # owner away: more of the PC
    R.run(tmp_path, ["build"])
    assert seen[2][1:] == ["build", "-j", "8"]


def test_she_is_shown_where_the_names_live_with_their_cfg_and_the_features(tmp_path):
    crate = tmp_path / "crates" / "rt"
    (crate / "src").mkdir(parents=True)
    (crate / "tests").mkdir()
    (crate / "Cargo.toml").write_text('[package]\nname = "rt"\n\n[features]\ndefault = ["presentation"]\n'
                                      'presentation = []\n\n[dependencies]\n', encoding="utf-8")
    (crate / "src" / "lib.rs").write_text('mod game;\n#[cfg(feature = "presentation")]\npub use game::{Game};\n',
                                          encoding="utf-8")
    (crate / "tests" / "cam.rs").write_text("use rt::Game;\n", encoding="utf-8")
    errs = [{"error": "error[E0432]: unresolved import `rt::Game`", "file": "crates/rt/tests/cam.rs", "line": 1}]
    shown = R.declarations(tmp_path, errs)
    assert 'presentation = []' in shown and '#[cfg(feature = "presentation")]\npub use game::{Game};' in shown
    assert "cam.rs" not in shown                                  # the failing test itself is already shown


def test_a_merge_that_compiles_but_breaks_a_crate_test_is_caught(tmp_path, monkeypatch):
    (tmp_path / "crates" / "phys" / "src").mkdir(parents=True)
    (tmp_path / "crates" / "phys" / "Cargo.toml").write_text('[package]\nname = "phys"\n', encoding="utf-8")
    out = ("---- raycast_from_inside stdout ----\n\nthread 'raycast_from_inside' panicked at tests/p.rs:9:5:\n"
           "assertion `left == right` failed\nfailures:\n")
    calls = []
    monkeypatch.setattr(R, "run", lambda tree, args, timeout=0: calls.append(args) or (False, out))
    ok, fails, crates, _ = R.crate_tests(tmp_path, ["crates/phys/src/lib.rs", "README.md"])
    assert not ok and crates == ["phys"] and calls == [["test", "-p", "phys"]]
    assert fails == "raycast_from_inside: assertion `left == right` failed"
    assert R.crate_tests(tmp_path, ["README.md"]) == (True, "", [], "")


def test_a_merged_build_that_breaks_is_read_as_her_repair_job():
    out = ("error[E0560]: struct `Shared` has no field named `step_handler_limit`\n   --> crates\metallic_script\src\\"
           "host.rs:284:21\n")
    log = "Run cargo test -p metallic_script -p metallic_core\n" + out       # what resolve() hands rust_fix.repair
    assert R.checks(log) == [["test", "--no-run", "-p", "metallic_script", "-p", "metallic_core"]]
    assert R.errors(log)[0]["file"] == "crates/metallic_script/src/host.rs"


def test_tests_that_fail_only_under_load_pass_when_run_alone(monkeypatch):
    out = ("---- trim_pattern_on_100kb_works stdout ----\nthread 'x' panicked at tests/vm.rs:9:5:\nScript timeout\n"
           "---- trim_pattern_on_100kb_works stdout ----\n")
    assert R.failed_names(out) == ["trim_pattern_on_100kb_works"]          # Studio #389 and #235
    calls = []
    monkeypatch.setattr(R, "run", lambda tree, args, timeout=0: calls.append(args) or (True, ""))
    assert R.pass_alone(None, ["metallic_script"], ["trim_pattern_on_100kb_works"])
    assert calls == [["test", "-p", "metallic_script", "--no-fail-fast", "--", "--exact", "--skip",
                      "trim_pattern_on_100kb_works"],                     # everything else still has to pass
                     ["test", "-p", "metallic_script", "--", "--exact", "--test-threads=1",
                      "trim_pattern_on_100kb_works"]]
    monkeypatch.setattr(R, "run", lambda tree, args, timeout=0: (args[-1] != "--test-threads=1" and
                                                                   "--skip" in args, ""))
    assert not R.pass_alone(None, ["s"], ["t"])                         # fails alone too: a real failure
    assert not R.pass_alone(None, ["s"], ["a", "b", "c", "d"])          # many failures are no load problem


def test_claudes_repair_sees_whole_files_full_errors_type_bodies_and_the_base_diff(tmp_path, monkeypatch):
    import subprocess
    src = tmp_path / "crates" / "render" / "src"
    src.mkdir(parents=True)
    (src / "views.rs").write_text("use crate::Uniforms;\n" + "// filler\n" * 30 +
                                  "fn make() -> Uniforms {\n    Uniforms {\n        material: [0.0; 4],\n    }\n}\n",
                                  encoding="utf-8")
    (src / "lib.rs").write_text("/// What the shader reads.\npub struct Uniforms {\n    pub material: u32,\n}\n",
                                encoding="utf-8")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run([*git, "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run([*git, "commit", "-qm", "x"], cwd=tmp_path, check=True)
    out = ("warning: unused variable\n --> crates/render/src/views.rs:1:1\n\n"
           "error[E0308]: mismatched types\n   --> crates/render/src/views.rs:34:19\n    |\n34  |"
           "         material: [0.0; 4],\n    |                   ^^^^^^^^ expected `u32`, found `[{float}; 4]`\n")
    errs = R.errors(out)
    prompt = R.wide_prompt(tmp_path, "o/r", "Debug views", [["test", "--no-run", "-p", "render"]], out, errs,
                           "HEAD", "")
    assert "\n// filler\n" not in prompt and "31: // filler" in prompt and "36: }" in prompt  # whole file, numbered
    assert "expected `u32`, found `[{float}; 4]`" in prompt and "unused variable" not in prompt
    assert "/// What the shader reads.\npub struct Uniforms {\n    pub material: u32,\n}" in prompt  # Studio #428
    assert "--no-default-features does not see items" in prompt and "gate the test" in prompt  # (#428's clippy)
    seen = []
    monkeypatch.setattr(R, "verify", lambda tree, cmds: (False, out))
    R.repair(tmp_path, "o/r", "t", "Run cargo test -p render\n" + out, lambda p: seen.append(p) or "{}",
             rounds=1, wide="HEAD")
    assert seen and "Every file with an error, in full" in seen[0]
    seen.clear()
    R.repair(tmp_path, "o/r", "t", "Run cargo test -p render\n" + out, lambda p: seen.append(p) or "{}", rounds=1)
    assert seen and "Every file with an error, in full" not in seen[0]      # her own 4K-window prompt unchanged


def test_a_long_erroring_file_shows_its_error_regions_so_every_file_fits(tmp_path):
    (tmp_path / "big.rs").write_text("".join(f"// line {i}\n" for i in range(1, 3001)), encoding="utf-8")
    (tmp_path / "t.rs").write_text("use rt::Game;\n", encoding="utf-8")
    errs = [{"file": "big.rs", "line": 1500, "error": "e"}, {"file": "t.rs", "line": 1, "error": "e"}]
    shown = R.whole_files(tmp_path, errs, budget=20000)
    assert "1500: // line 1500" in shown and "1: // line 1\n" not in shown and "--- t.rs\n1: use rt::Game;" in shown
