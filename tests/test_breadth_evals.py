"""Breadth suites: evals/gdscript (headless Godot graders) and evals/instruction-following (code checkers).

Nothing here needs a model or the server. The Godot runs themselves happen only when STAR_EVAL_GODOT_SSH or
STAR_EVAL_GODOT_BIN is set (see test_godot_selftest); everything else uses fakes or pure checkers.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil

import pytest

from star import breadth_evals as be
from star import breadth_ifbench as ifb
from star import eval_checks as ec
from star import eval_runner as er
from star import evals

ROOT = Path(__file__).resolve().parents[1]
GD = ROOT / "evals" / "gdscript"
IF = ROOT / "evals" / "instruction-following"
SUITES = {"gd-dev": GD / "golden-tasks-v1.json", "gd-holdout": GD / "holdout-v1.json",
          "if-dev": IF / "golden-tasks-v1.json", "if-holdout": IF / "holdout-v1.json"}
PRIVATE_ADDRESS = re.compile(r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b")
FUZZY_LIMIT = 0.5


def _tasks(key: str) -> list[dict]:
    return json.loads(SUITES[key].read_text(encoding="utf-8"))


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]{3,}", text.lower()))


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# --- shape of the four suite files --------------------------------------------------------------------------

@pytest.mark.parametrize("key,count,split", [("gd-dev", 18, "dev"), ("gd-holdout", 9, "holdout"),
                                              ("if-dev", 24, "dev"), ("if-holdout", 12, "holdout")])
def test_suites_load_with_the_harness_loader(key, count, split):
    suite = er.load_suite(SUITES[key])
    assert len(suite.tasks) == count == len(suite.runnable())
    assert {t["split"] for t in suite.tasks} == {split}
    assert be.suite_kind(SUITES[key]) == ("gdscript" if key.startswith("gd") else "ifbench")
    assert be.breadth_problems(suite.tasks, suite.directory) == []


def test_holdout_is_a_third_of_the_gdscript_suite():
    assert len(_tasks("gd-holdout")) * 3 == len(_tasks("gd-dev")) + len(_tasks("gd-holdout"))


def test_ids_prompts_and_goals_are_unique_across_dev_and_holdout():
    for left, right in (("gd-dev", "gd-holdout"), ("if-dev", "if-holdout")):
        a, b = _tasks(left), _tasks(right)
        ids = [t["id"] for t in a + b]
        assert len(ids) == len(set(ids))
        assert all(t["id"].startswith("HO-") for t in b) and not any(t["id"].startswith("HO-") for t in a)
        for x in a:
            for y in b:
                wx, wy = _words(x["prompt"]), _words(y["prompt"])
                assert len(wx & wy) / max(1, len(wx | wy)) < FUZZY_LIMIT, (x["id"], y["id"])


def test_gdscript_tasks_have_tests_references_and_a_correct_assertion_count():
    assert (GD / "harness.gd").is_file()
    for key in ("gd-dev", "gd-holdout"):
        for t in _tasks(key):
            test = GD / t["auto"]["unit_test"]["file"]
            body = test.read_text(encoding="utf-8")
            assert body.count("H.check(") == t["auto"]["unit_test"]["checks"] >= 5, t["id"]
            assert "H.finish(self)" in body and "extends SceneTree" in body
            assert "```gdscript" in (GD / "reference" / f"{t['id']}.md").read_text(encoding="utf-8")
            assert (GD / "reference" / f"{t['id']}.bad.md").is_file()
            assert "gdscript" in t["prompt"] and "Godot 4" in t["prompt"]
    on_disk = {p.stem for p in (GD / "tests").glob("*.gd")}
    assert on_disk == {t["id"] for k in ("gd-dev", "gd-holdout") for t in _tasks(k)}


def test_instruction_tasks_have_references_and_no_orphans():
    ids = {t["id"] for k in ("if-dev", "if-holdout") for t in _tasks(k)}
    on_disk = {p.name for p in (IF / "reference").glob("*.md")}
    assert on_disk == {f"{i}{k}.md" for i in ids for k in ("", ".bad")}
    for k in ("if-dev", "if-holdout"):
        for t in _tasks(k):
            assert 1 <= len(t["auto"]["breadth"]["constraints"]) <= 4, t["id"]


def test_no_private_address_or_secret_in_the_suite_files():
    for folder in (GD, IF):
        for path in folder.rglob("*"):
            if path.is_file():
                assert not PRIVATE_ADDRESS.search(path.read_text(encoding="utf-8")), path


@pytest.mark.parametrize("folder", [GD, IF])
def test_frozen_holdout_files_still_have_the_recorded_hashes(folder):
    recorded = {}
    for line in (folder / "holdout-v1.sha256").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            digest, name = line.split(None, 1)
            recorded[name.strip()] = digest
    holdout_ids = [t["id"] for t in json.loads((folder / "holdout-v1.json").read_text(encoding="utf-8"))]
    expected = {"holdout-v1.json"}
    for tid in holdout_ids:
        expected |= {f"reference/{p.name}" for p in (folder / "reference").glob(f"{tid}.*md")}
        if folder == GD:
            expected.add(f"tests/{tid}.gd")
    assert set(recorded) == expected
    for name, digest in recorded.items():
        assert _lf_sha256(folder / name) == digest, f"{name} changed after the freeze"


# --- instruction-following checkers --------------------------------------------------------------------------

def _score_if(task, answer):
    return be.score_ifbench(task, answer)


@pytest.mark.parametrize("key", ["if-dev", "if-holdout"])
def test_every_reference_passes_and_every_bad_answer_fails(key):
    for t in _tasks(key):
        good = (IF / "reference" / f"{t['id']}.md").read_text(encoding="utf-8")
        bad = (IF / "reference" / f"{t['id']}.bad.md").read_text(encoding="utf-8")
        assert _score_if(t, good).passed, (t["id"], _score_if(t, good).reasons)
        assert not _score_if(t, bad).passed, t["id"]
        assert not _score_if(t, "").passed
        assert not _score_if(t, "   \n").passed


def test_the_bad_answers_fail_for_the_intended_constraint_not_by_accident():
    # A bad answer should miss at least one real constraint of its task; an empty-text pass would mean nothing was tested.
    for key in ("if-dev", "if-holdout"):
        for t in _tasks(key):
            bad = (IF / "reference" / f"{t['id']}.bad.md").read_text(encoding="utf-8")
            failed = [c.id for c in _score_if(t, bad).checks if not c.ok]
            assert failed and "answer" not in failed, t["id"]


def test_star_footers_are_not_part_of_the_answer():
    t = _tasks("if-dev")[9]                                    # IF-10: exactly five bullet lines
    answer = (IF / "reference" / "IF-10.md").read_text(encoding="utf-8")
    footer = "\n\n---\n**Sources retrieved by STAR**\n1. Page · cited\n"
    assert _score_if(t, answer + footer).passed


def test_every_constraint_type_has_a_passing_and_a_failing_example():
    cases = {
        "word_count": ({"min": 2, "max": 3}, "one two three", "one"),
        "sentence_count": ({"min": 2, "max": 2}, "One. Two.", "One."),
        "paragraph_count": ({"n": 2}, "a\n\nb", "a"),
        "line_count": ({"min": 2, "max": 2}, "a\nb", "a"),
        "contains_all": ({"words": ["red apple"]}, "A Red Apple.", "red"),
        "forbidden_words": ({"words": ["cat"]}, "category", "a cat"),
        "keyword_count": ({"word": "go", "min": 2, "max": 2}, "go go", "go"),
        "letter_count": ({"letter": "q", "max": 0}, "abc", "quit"),
        "char_count": ({"char": "!", "min": 2}, "a!b!", "a!"),
        "starts_with": ({"text": "Hi"}, " Hi there", "Oh Hi"),
        "ends_with": ({"text": "Bye."}, "ok Bye.\n", "Bye. ok"),
        "all_lowercase": ({}, "abc 1", "aBc"),
        "all_uppercase": ({}, "ABC 1", "ABc"),
        "no_char": ({"chars": ",;"}, "a b", "a;b"),
        "capital_words": ({"min": 2, "max": 2}, "TCP and UDP", "TCP I"),
        "digit_count": ({"min": 2}, "a1b2", "a1"),
        "max_word_length": ({"n": 4}, "tiny word", "enormous"),
        "no_repeat_words": ({}, "a b c", "a A"),
        "sentence_max_words": ({"n": 3}, "a b c. d e.", "a b c d."),
        "distinct_sentence_starts": ({}, "Alpha. Beta.", "Alpha. Apple."),
        "nth_word": ({"n": 2, "word": "two"}, "one two", "two one"),
        "quote_wrap": ({}, '"hi"', 'hi "there"'),
        "line_end": ({"char": ";"}, "a;\nb;", "a;\nb"),
        "acrostic": ({"word": "HI"}, "Hello\nIt", "Hello\nBye"),
        "title_brackets": ({}, "<<T>>\nbody", "T\n<<x>>"),
        "placeholders": ({"min": 2}, "[a] and [b c]", "[a]"),
        "postscript": ({"marker": "P.S."}, "x\n\nP.S. y", "P.S. x\n\ny"),
        "bold_count": ({"min": 1}, "a **b** c", "a *b*"),
        "bullets": ({"n": 2, "marker": "-"}, "- a\n- b", "- a\n* b"),
        "bullet_max_words": ({"n": 2}, "- a b\n- c", "- a b c"),
        "alphabetical_bullets": ({}, "- Apple\n- banana", "- b\n- a"),
        "numbered_list": ({"n": 2}, "1. a\n2. b", "1. a\n3. b"),
        "sections": ({"n": 2, "label": "PART"}, "PART 1\nx\nPART 2\ny", "PART 2\nPART 1"),
        "paragraph_sep": ({"n": 2}, "a\n***\nb", "a\n***\nb\n***\nc"),
        "repeat_prompt": ({"text": "Why?"}, "Why? Because it is so.", "Because. Why?"),
        "markdown_table": ({"cols": 2, "rows": 1, "header": ["A", "B"]}, "| A | B |\n|---|---|\n| 1 | 2 |", "| A | B |\n| 1 | 2 |"),
        "csv": ({"header": ["a", "b"], "rows": 1}, "a,b\n1,2", "a,b\n1"),
        "json_only": ({"keys": {"k": "integer"}}, '{"k": 1}', '{"k": true}'),
        "language": ({"lang": "de"}, "Das ist ein Haus und die Katze ist nicht im Garten mit dem Hund.", "This is a house and the cat is in the garden with a dog."),
    }
    assert set(cases) == set(ifb.CHECKS), set(ifb.CHECKS) ^ set(cases)
    for kind, (params, good, bad) in cases.items():
        assert ifb.CHECKS[kind](good, **params) == "", (kind, ifb.CHECKS[kind](good, **params))
        assert ifb.CHECKS[kind](bad, **params) != "", kind


def test_json_checker_accepts_one_wrapping_fence_and_rejects_prose_around_json():
    spec = {"keys": {"a": "integer"}}
    assert ifb.json_only('```json\n{"a": 1}\n```', **spec) == ""
    assert ifb.json_only('Sure: {"a": 1}', **spec) != ""
    assert ifb.json_only('{"a": 1.5}', **spec) != ""            # not an integer
    assert ifb.json_only('{"a": true}', **spec) != ""            # a bool is not an integer
    assert ifb.json_only('{"a": 1, "b": 2}', **spec) != ""       # extra keys
    assert ifb.json_only('{"a": 1, "b": 2}', exact_keys=False, **spec) == ""
    arr = {"shape": "array", "length": 2, "items": {"x": "string"}}
    assert ifb.json_only('[{"x": "a"}, {"x": "b"}]', **arr) == ""
    assert ifb.json_only('[{"x": "a"}]', **arr) != "" and ifb.json_only('{"x": "a"}', **arr) != ""


def test_language_checker_tells_the_languages_apart():
    es = "El gato come pescado en la cocina y los niños juegan con una pelota muy grande."
    fr = "Le chat mange du poisson dans la cuisine et les enfants jouent avec une très grande balle."
    de = "Die Katze frisst Fisch in der Küche und die Kinder spielen mit einem sehr großen Ball."
    en = "The cat eats fish in the kitchen and the children play with a very big ball for the day."
    ru = "Кошка ест рыбу на кухне, а дети играют с очень большим мячом."
    for lang, text in (("es", es), ("fr", fr), ("de", de), ("ru", ru)):
        assert ifb.language(text, lang=lang) == "", lang
    for wrong in ("es", "fr", "de", "ru"):
        assert ifb.language(en, lang=wrong) != ""
    assert ifb.language(fr, lang="es") != "" and ifb.language(es, lang="fr") != "" and ifb.language(de, lang="fr") != ""


def test_constraint_validation_names_the_problem():
    assert ifb.validate_constraints([{"type": "word_count", "min": 3}]) == []
    problems = ifb.validate_constraints([{"type": "nope"}, {"type": "word_count"}, {"type": "bullets", "n": 3},
                                         {"type": "json_only"}, {"type": "language", "lang": "xx"}])
    assert len(problems) == 5
    assert "unknown type" in problems[0] and "needs min or max" in problems[1] and "missing marker" in problems[2]


def test_check_ids_repeat_with_a_counter():
    out = ifb.check_all("a b", [{"type": "word_count", "min": 1}, {"type": "word_count", "max": 5}])
    assert [c for c, _ in out] == ["word_count", "word_count#2"]


# --- GDScript reading, policy and runner ---------------------------------------------------------------------

def test_extract_prefers_labelled_blocks_and_picks_the_script():
    answer = ("Intro\n```gdscript\nextends Node\nvar a = 1\n```\nUsage:\n```gdscript\nvar n = Foo.new()\n```\n"
              "```python\nprint(1)\n```")
    blocks = be.extract_gdscript_blocks(answer)
    assert len(blocks) == 2
    assert be.pick_script(blocks).startswith("extends Node")
    assert be.extract_gdscript_blocks("```\nextends Node\nfunc f():\n    pass\n```") != []   # unlabelled but GDScript
    assert be.extract_gdscript_blocks("```\nprint('hi')\n```") == []
    assert be.extract_gdscript_blocks("no code") == []


def test_strip_removes_comments_and_string_contents_but_keeps_lines():
    code = 'var a = "OS.execute" # OS here\nvar b = """OS\nOS"""\nvar c = \'x\\\'y\'\nOS.quit()\n'
    stripped = be.strip_gdscript(code)
    assert stripped.count("\n") == code.count("\n")
    assert "execute" not in stripped and stripped.count("OS") == 1


@pytest.mark.parametrize("code,expected", [
    ("extends Node\nfunc f():\n    OS.execute('ls', [])", ["OS"]),
    ("var f = FileAccess.open('x', FileAccess.READ)", ["FileAccess"]),
    ("var s = GDScript.new()\ns.source_code = 'x'", ["GDScript.new", "source_code"]),
    ("var o = Engine.get_singleton('OS')", ["get_singleton"]),
    ("var c = ClassDB.instantiate('Node')", ["ClassDB"]),
    ("var h = HTTPRequest.new()", ["HTTPRequest"]),
    ("# OS.execute in a comment\nvar s = 'FileAccess'\nvar bonus := 1", []),
    ("func reload():\n    pass\nvar COST := 3\nvar MacOS := 1", []),
    ("extends Node\nvar t := Time.get_ticks_msec()\nfunc f():\n    get_tree().create_timer(1.0)", []),
])
def test_forbidden_api_scan(code, expected):
    assert be.forbidden_apis(code) == sorted(expected)


class FakeRunner:
    def __init__(self, stdout="", error="", timed_out=False):
        self.calls = []
        self.result = be.SandboxResult(rc=0, stdout=stdout, error=error, timed_out=timed_out)

    def run(self, files):
        self.calls.append(files)
        return self.result


GD_TASK = {"id": "X", "auto": {"unit_test": {"file": "tests/X.gd", "checks": 2}}}
GOOD_OUT = "Godot Engine\n@@T\tpass\ta\n@@T\tpass\tb\n@@DONE\n"


def _score_gd(answer, runner):
    return be.score_gdscript(GD_TASK, answer, test_body="extends SceneTree", harness="extends RefCounted", runner=runner)


def test_score_gdscript_sends_four_files_and_passes_on_all_assertions():
    runner = FakeRunner(GOOD_OUT)
    score = _score_gd("text\n```gdscript\nextends Node\n```\n", runner)
    assert score.passed and score.blocks == 1
    assert set(runner.calls[0]) == {"project.godot", "harness.gd", "answer.gd", "test.gd"}
    assert runner.calls[0]["answer.gd"].startswith("extends Node")


@pytest.mark.parametrize("stdout,needle", [
    ("@@T\tpass\ta\n@@T\tfail\tb\n@@DONE\n", "failed: b"),
    ("@@T\tpass\ta\n@@DONE\n", "1 of 2 assertions ran"),
    ("@@T\tpass\ta\nSCRIPT ERROR: Invalid call. Nonexistent function 'x' in base 'Nil'.\n", "Nonexistent function"),
    ("@@LOADERR\tanswer.gd does not parse\nSCRIPT ERROR: Parse Error: Identifier \"TYPE_REAL\" not declared\n", "TYPE_REAL"),
    ("", "harness did not finish"),
])
def test_score_gdscript_failure_reasons(stdout, needle):
    score = _score_gd("```gdscript\nextends Node\n```", FakeRunner(stdout))
    assert not score.passed and needle in "; ".join(score.reasons)


def test_score_gdscript_timeout_says_godot_not_luau():
    score = _score_gd("```gdscript\nextends Node\n```", FakeRunner("@@T\tpass\ta\n", timed_out=True))
    assert not score.passed and "headless Godot" in score.reasons[0] and "Luau" not in score.reasons[0]


def test_score_gdscript_refuses_hostile_code_without_running_it():
    runner = FakeRunner(GOOD_OUT)
    score = _score_gd("```gdscript\nextends Node\nfunc f():\n    OS.execute('rm', [])\n```", runner)
    assert not score.passed and runner.calls == [] and "sandbox_policy" in score.reasons[0]


def test_score_gdscript_without_a_block_or_runner():
    assert not _score_gd("sorry, I cannot", FakeRunner(GOOD_OUT)).passed
    with pytest.raises(ec.InfraError):
        _score_gd("```gdscript\nextends Node\n```", None)           # infrastructure: the task becomes `error`, not `fail`
    with pytest.raises(ec.InfraError):
        _score_gd("```gdscript\nextends Node\n```", FakeRunner(error="ssh failed"))


def test_remote_script_limits_isolation_and_encoding():
    runner = be.GodotRunner("user@host.example", wall_s=20, cpu_s=15, mem_mb=2048)
    script = runner.remote_script({"answer.gd": "extends Node\n# …", "test.gd": "x"})
    assert "ulimit -v 2097152" in script and "ulimit -t 15" in script and "timeout -s KILL 20" in script
    assert "nice -n 19" in script and "unshare -rn" in script and "--headless" in script
    assert 'BIN="$HOME/godot/godot"' in script and "rm -rf" in script and "@@RC" in script
    assert "extends Node" not in script                                   # files travel as base64
    assert not PRIVATE_ADDRESS.search(script)
    assert 'BIN="/opt/godot/godot"' in be.GodotRunner("u@h", "/opt/godot/godot").remote_script({"a.gd": "x"})
    assert 'BIN="$HOME/bin/godot"' in be.GodotRunner("u@h", "~/bin/godot").remote_script({"a.gd": "x"})


@pytest.mark.parametrize("kwargs", [{"ssh": "not a target"}, {"ssh": "u@h;rm -rf /"}, {"binary": "/x; reboot"},
                                    {"wall_s": 0}, {"mem_mb": 10 ** 6}])
def test_runner_rejects_unsafe_configuration(kwargs):
    with pytest.raises(ValueError):
        be.GodotRunner(**kwargs)
    with pytest.raises(ValueError):
        be.GodotRunner("u@h").remote_script({"../evil.gd": "x"})


def test_runner_from_env_needs_a_target(monkeypatch):
    monkeypatch.delenv("STAR_EVAL_GODOT_SSH", raising=False)
    monkeypatch.delenv("STAR_EVAL_GODOT_BIN", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert be.GodotRunner.from_env() is None
    monkeypatch.setenv("STAR_EVAL_GODOT_SSH", "user@host")
    assert be.GodotRunner.from_env().ssh == "user@host"


def test_runner_reports_ssh_problems_as_errors_not_failures():
    class Done:
        returncode, stdout = 255, b"ssh: could not resolve"
    runner = be.GodotRunner("user@host", runner=lambda *a, **k: Done())
    assert "ssh failed" in runner.run({"a.gd": "x"}).error
    ok = type("Ok", (), {"returncode": 0, "stdout": b"@@NOGODOT\n@@RC 96\n"})()
    assert "no Godot binary" in be.GodotRunner("user@host", runner=lambda *a, **k: ok).run({"a.gd": "x"}).error


# --- wiring into python -m star.evals ------------------------------------------------------------------------

def test_breadth_suites_are_routed_and_luau_suites_are_not():
    for key in SUITES:
        assert be.wants_breadth(["run", "--suite", str(SUITES[key]), "--out", "x.json"])
        assert be.wants_breadth(["selftest", f"--suite={SUITES[key]}"])
    assert not be.wants_breadth(["run", "--suite", str(ROOT / "evals" / "roblox" / "golden-tasks-v2.json"), "--out", "x"])
    assert not be.wants_breadth(["list", "--suite", str(SUITES["if-dev"])])
    assert not be.wants_breadth(["gate", "--baseline", "a"]) and not be.wants_breadth([])
    assert not be.wants_breadth(["run", "--suite", str(ROOT / "evals" / "godot" / "tasks.json")])


def test_python_m_star_evals_selftest_runs_the_instruction_suites(capsys):
    for key in ("if-dev", "if-holdout"):
        assert evals.main(["selftest", "--suite", str(SUITES[key])]) == 0
    out = capsys.readouterr().out
    assert out.count("selftest: all good") == 2 and "FAIL" not in out


def test_run_suite_with_the_breadth_scorer_and_fake_answers(tmp_path):
    suite = er.load_suite(SUITES["if-holdout"])
    answers = {t["id"]: (IF / "reference" / f"{t['id']}{'.bad' if i % 2 else ''}.md").read_text(encoding="utf-8")
               for i, t in enumerate(suite.tasks)}
    ask = lambda task, cancel=None: er.Asked(answers[task["id"]], [], 1.0)         # noqa: E731
    result = er.run_suite(suite, out=tmp_path / "r.json", ask=ask, scorer=be.make_scorer(suite, None),
                          run_info={"fingerprint": "f"}, log=lambda m: None)
    assert result["complete"] and result["summary"]["pass"] == 6 and result["summary"]["fail"] == 6
    record = result["tasks"]["HO-IF-02"]
    assert record["status"] == "fail" and any(c["id"] == "placeholders" and not c["ok"] for c in record["checks"])
    assert result["tasks"]["HO-IF-01"]["status"] == "pass"


def test_main_run_uses_the_breadth_scorer_and_records_its_fingerprint(tmp_path, monkeypatch, capsys):
    ref = {t["id"]: (IF / "reference" / f"{t['id']}.md").read_text(encoding="utf-8") for t in _tasks("if-holdout")}
    info = {"fingerprint": "abc123", "model": "star-fast"}
    monkeypatch.setattr(er, "build_real", lambda args, log=print: (dict(info), lambda t, c=None: er.Asked(ref[t["id"]], [], 1.0),
                                                                   None, None, []))
    monkeypatch.setattr("star.planner_client.PlannerClient", lambda **kw: type("P", (), {"enabled": False})())
    out = tmp_path / "r.json"
    assert be.main(["run", "--suite", str(SUITES["if-holdout"]), "--out", str(out), "--tasks", "HO-IF-01,HO-IF-03"]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["summary"]["pass"] == 2 and set(result["tasks"]) == {"HO-IF-01", "HO-IF-03"}
    assert result["run"]["breadth"]["kind"] == "ifbench" and len(result["run"]["breadth"]["grader_sha256"]) == 64
    assert result["run"]["fingerprint"] != "abc123"                 # grader code is part of the resume key
    assert be.main(["run", "--suite", str(SUITES["if-holdout"]), "--out", str(out)]) == 0   # resumes and finishes
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["pass"] == 12
    assert be.main(["rescore", "--suite", str(SUITES["if-holdout"]), "--result", str(out), "--out", str(tmp_path / "s.json")]) == 0


def test_breadth_grader_fingerprint_follows_the_harness(tmp_path):
    shutil.copy(GD / "harness.gd", tmp_path / "harness.gd")
    first = be.breadth_grader_sha256(tmp_path)
    assert first == be.breadth_grader_sha256(tmp_path) and first != be.breadth_grader_sha256(None)
    (tmp_path / "harness.gd").write_text("# changed\n", encoding="utf-8")
    assert be.breadth_grader_sha256(tmp_path) != first


# --- real Godot, only where one is configured --------------------------------------------------------------------

@pytest.mark.skipif(not (os.environ.get("STAR_EVAL_GODOT_SSH") or os.environ.get("STAR_EVAL_GODOT_BIN")),
                    reason="set STAR_EVAL_GODOT_SSH (user@host with Godot 4) or STAR_EVAL_GODOT_BIN to run the Godot graders")
@pytest.mark.parametrize("key", ["gd-dev", "gd-holdout"])
def test_godot_selftest_references_pass_and_bad_answers_fail(key, capsys):
    assert evals.main(["selftest", "--suite", str(SUITES[key])]) == 0
    assert "FAIL" not in capsys.readouterr().out
