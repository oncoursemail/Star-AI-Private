"""The anti-slop checker (star/slop.py) and its opt-in wiring: night school, the chat answer, evaluation records."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from star import slop

ROOT = Path(__file__).resolve().parents[1]


def rules(answer, **kwargs):
    return slop.score_answer(answer, use_api_dump=False, **kwargs).rules


# --- prose --------------------------------------------------------------------------------------------------

def test_filler_openers_and_closers_are_found_by_line_and_trimmed_outside_code():
    answer = ("Certainly! Here is the updated script:\n\n```luau\nlocal x = 1 -- Here is the code:\n```\n\n"
              "It sets x.\n\nI hope this helps! Let me know if you need anything else.\n")
    report = slop.score_answer(answer, use_api_dump=False)
    assert [(f.rule, f.line) for f in report.findings] == [("P01.filler_opener", 1), ("P02.closing_offer", 9)]
    trimmed, removed = slop.trim_filler(answer)
    assert len(removed) == 2 and "Here is the code:" in trimmed and trimmed.startswith("```luau")
    assert trimmed.rstrip().endswith("It sets x.")
    assert slop.trim_filler("```luau\nlocal y = 2\n```\n") == ("```luau\nlocal y = 2\n```\n", [])


def test_what_star_appended_is_never_scored():
    answer = ("```luau\nlocal x = 1\n```\n\n**Luau check by STAR:** The code block compiles. Roblox API names and "
              "types were not verified, and the code was not run.")
    assert rules(answer) == []


def test_unverified_claims_are_hard_but_evidence_clears_them():
    claim = "I tested this and it works perfectly.\n\n```luau\nlocal x = 1\n```\n"
    report = slop.score_answer(claim, use_api_dump=False)
    assert report.rules == ["P06.unverified_claim"] and report.hard and report.slop
    assert rules("I ran it; expected output: 3\n\n```luau\nprint(1 + 2)\n```\n") == []
    assert "claims the code was tested" in slop.answer_note(report)


def test_restating_the_request_hedging_generic_advice_and_vague_words():
    prompt = "Write a Luau ModuleScript named Inventory with add, remove and count functions that validate counts"
    restated = ("Here is a Luau ModuleScript named Inventory with add, remove and count functions that validate counts.\n\n"
                "```luau\nlocal M = {}\nreturn M\n```\n")
    assert "P03.restates_request" in rules(restated, prompt=prompt)
    assert "P03.restates_request" not in rules("The fix is a snapshot of the handlers before the loop runs them.\n\n"
                                                "```luau\nlocal M = {}\nreturn M\n```\n", prompt=prompt)
    hedged = ("Note that it depends on your setup. Keep in mind that typically, generally speaking, in most cases "
              "you might want to adjust it as needed, etc.")
    assert "P04.hedge_density" in rules(hedged)
    assert "P05.generic_advice" in rules("Make sure to test thoroughly and follow best practices.")
    vague = "A robust, seamless, scalable, elegant and comprehensive solution that leverages cutting-edge power."
    assert "P10.vague_words" in rules(vague)
    assert rules("The loop skips an element because table.remove shifts the rest down.") == []


def test_overlong_prose_is_judged_against_the_code_and_a_summary_that_repeats_is_an_echo():
    words = " ".join(f"word{i}" for i in range(450))
    assert "P07.overlong" in rules(words + "\n\n```luau\nlocal x = 1\n```\n")
    assert "P07.overlong" not in rules(words)            # a prose-only answer may need 450 words
    assert "P07.overlong" in rules(" ".join(f"word{i}" for i in range(650)))
    body = ("The handler list is copied before the loop so removals cannot shift elements.\n"
            "Each handler then runs once even when it disconnects itself.\n\n"
            "## Summary\n\n- The handler list is copied before the loop so removals cannot shift elements.\n"
            "- Each handler then runs once even when it disconnects itself.\n")
    assert "P08.summary_echo" in rules(body)
    assert "P09.meta_ai" in rules("As an AI I cannot run code, but this should work.")


# --- code ---------------------------------------------------------------------------------------------------

def test_todo_stubs_empty_bodies_and_placeholders_in_luau():
    code = ("```luau\nlocal function giveItem(player, itemId)\n\t-- implement according to your items\nend\n\n"
            "-- TODO: handle the shot\nlocal key = YOUR_API_KEY\nreturn giveItem\n```\n")
    report = slop.score_answer(code, use_api_dump=False)
    assert report.rules == ["C01.todo_stub", "C02.empty_body", "C03.placeholder_value"] and report.hard
    assert [f.line for f in report.findings if f.rule == "C02.empty_body"] == [2]
    assert "placeholder or empty function" in slop.answer_note(report)
    # The word "placeholder" in an ordinary comment is not a stub.
    assert rules("```luau\n-- We use a placeholder font size to get the scale factor\nlocal s = 14\n```\n") == []


def test_tests_that_assert_nothing_and_always_true_assertions_in_three_languages():
    py = "```python\ndef test_add():\n    add(1, 2)\n\ndef test_ok():\n    assert add(1, 2) == 3\n```\n"
    report = slop.score_answer(py, use_api_dump=False)
    assert [(f.rule, f.message) for f in report.findings] == [("C06.test_without_assert", "test test_add asserts nothing")]
    ts = "```ts\nit('adds', () => {\n  add(1, 2);\n});\ntest('ok', async () => {\n  expect(add(1, 2)).toBe(3);\n});\n```\n"
    assert rules(ts) == ["C06.test_without_assert"]
    luau = ("```luau\nit(\"adds\", function()\n\tadd(1, 2)\nend)\nit(\"ok\", function()\n\texpect(add(1, 2)).toBe(3)\nend)\n```\n")
    assert rules(luau) == ["C06.test_without_assert"]
    assert "C07.vacuous_assert" in rules("```python\ndef test_x():\n    assert True\n```\n")
    assert "C07.vacuous_assert" in rules("```ts\nit('x', () => { expect(true).toBe(true); });\n```\n")
    assert "a test asserts nothing" in slop.answer_note(slop.score_answer(py, use_api_dump=False))


def test_python_stubs_and_swallowed_errors():
    code = ("```python\ndef load(path):\n    pass\n\ndef save(path):\n    raise NotImplementedError\n\n"
            "def read(path):\n    try:\n        return open(path).read()\n    except Exception:\n        pass\n```\n")
    assert rules(code) == ["C02.empty_body", "C10.swallowed_error"]
    assert rules("```python\ndef area(w, h):\n    return w * h\n```\n") == []


def test_dead_code_commented_code_debug_prints_and_duplicate_blocks():
    unreachable = "```luau\nlocal function f(t)\n\treturn t * 2 -- wait\n\treturn t * 3\nend\n```\n"
    report = slop.score_answer(unreachable, use_api_dump=False)
    assert [(f.rule, f.line) for f in report.findings] == [("C05.unreachable", 4)]
    commented = "```luau\nlocal a = 1\n-- local b = 2\n-- print(b)\n-- reach(guard, knob)\n```\n"
    assert rules(commented) == ["C04.commented_out_code"]
    illustrated = "```luau\nlocal a = 1\n-- Result:\n-- data = {\n--   coins = 100,\n--   version = 3,\n-- }\n```\n"
    assert rules(illustrated) == []
    assert rules("```luau\nprint(\"debug\")\nlocal a = 1\n```\n") == ["C09.debug_leftover"]
    block = "```luau\n" + "\n".join(f"local v{i} = {i}" for i in range(12)) + "\n```\n"
    assert rules(block + "\n" + block) == ["C11.duplicate_block"]


def test_invented_roblox_apis_use_the_bundled_dump_and_known_names_pass():
    answer = ("```luau\nlocal Players = game:GetService(\"Playerz\")\nlocal part = Instance.new(\"Partt\")\n"
              "local atm = Instance.new(\"Atmosphere\")\natm.SunInfluence = 0.5\n```\n")
    report = slop.score_answer(answer)
    assert [(f.rule, f.line, f.hard) for f in report.findings] == [
        ("C08.invented_api", 2, True), ("C08.invented_api", 3, True), ("C08.unknown_member", 5, False)]
    assert "Partt, Playerz" in slop.answer_note(report)
    fine = ("```luau\nlocal Players = game:GetService(\"Players\")\nlocal part = Instance.new(\"Part\")\n"
            "part.Transparency = 0.5\npart.Parent = workspace\n```\n")
    assert slop.score_answer(fine).findings == []


# --- UI -----------------------------------------------------------------------------------------------------

def test_generic_ai_looking_ui_tells():
    html = ("```html\n<section class=\"bg-gradient-to-r from-purple-500 to-pink-500\">\n<h1>Your Company Name</h1>\n"
            "<p>Lorem ipsum dolor</p>\n<div class=\"backdrop-blur\">✨ Feature 1</div><div class=\"backdrop-blur-lg\">🚀 Feature 2</div>\n"
            "<a>Get started →</a><a>Learn more →</a>\n</section>\n```\n")
    found = rules(html)
    assert {"U01.placeholder_copy", "U02.emoji_icons", "U03.gradient_violet", "U04.glass", "U05.generic_cta"} <= set(found)
    plain = "```html\n<section><h1>Bakery hours</h1><p>Open 7-15, closed Monday.</p></section>\n```\n"
    assert rules(plain) == []


# --- report, numbers, CLI -------------------------------------------------------------------------------------

def test_score_is_bounded_and_the_record_is_plain_data():
    many = "\n".join("Make sure to test thoroughly." for _ in range(30)) + "\nI tested it and it works perfectly."
    report = slop.score_answer(many, use_api_dump=False)
    assert report.score <= slop.MAX_SCORE and report.hard and report.slop
    record = json.loads(json.dumps(report.record()))
    assert set(record) == {"score", "hard", "slop", "rules", "prose_words", "code_chars", "findings"}
    assert report.summary().startswith("slop ") and "HARD" in report.summary()
    with pytest.raises(TypeError):
        slop.score_answer(None)


def test_measure_splits_by_outcome_and_the_cli_reads_results_and_jsonl(tmp_path, capsys):
    rows = [{"answer": "I tested it, works perfectly.\n\n```luau\nlocal x = 1\n```\n", "passed": False, "id": "A"},
            {"answer": "```luau\nlocal x = 1\n```\n", "passed": True, "id": "B"},
            {"answer": "```luau\nlocal y = 2\n```\n", "passed": None, "id": "C"}]
    numbers = slop.measure(rows, use_api_dump=False)
    assert numbers["answers"] == 3 and numbers["hard_share"] == round(1 / 3, 3)
    assert numbers["by_outcome"]["fail"]["slop_share"] == 1.0 and numbers["by_outcome"]["pass"]["slop_share"] == 0.0
    result = tmp_path / "r.json"
    result.write_text(json.dumps({"tasks": {"A": {"status": "fail", "passed": False, "answer": rows[0]["answer"]},
                                            "B": {"status": "pass", "passed": True, "answer": rows[1]["answer"]}}}),
                      encoding="utf-8")
    lines = tmp_path / "rows.jsonl"
    lines.write_text(json.dumps({"id": "C", "response": rows[2]["answer"]}) + "\n", encoding="utf-8")
    sample = tmp_path / "sample.jsonl"
    assert slop.main([str(result), str(lines), "--no-api-dump", "--sample", "5", "--out", str(sample)]) == 0
    out = json.loads(capsys.readouterr().out.split("\nwrote")[0])
    assert out["answers"] == 3 and out["rules"] == {"P06.unverified_claim": 1}
    assert [json.loads(l)["rule"] for l in sample.read_text(encoding="utf-8").splitlines()] == ["P06.unverified_claim"]


# --- wiring: evaluation records, the chat answer, night school ------------------------------------------------

def test_evaluation_records_carry_a_slop_score_without_touching_pass_or_fail():
    from star import eval_checks as ec
    from star import eval_runner as er
    score = ec.TaskScore()
    score.checks.append(ec.Check("luau_block", True))
    asked = er.Asked("I tested this, works perfectly.\n\n```luau\nlocal x = 1\n```\n", [], 2.0)
    record = er.record_for({"id": "T", "prompt": "p"}, asked, score)
    assert record["status"] == "pass" and record["slop"] == {"score": 8, "hard": True, "rules": ["P06.unverified_claim"]}
    summary = er.summarize({"T": record, "U": {**record, "slop": {"score": 0, "hard": False, "rules": []}}})
    assert summary["pass"] == 2 and summary["slop_mean"] == 4.0 and summary["slop_hard"] == 1
    assert "slop_mean" not in er.summarize({"E": {"status": "error", "seconds": 0.0}})


def test_the_setting_is_validated_and_off_by_default():
    from star.desktop_core import Settings
    assert Settings().slop_check == "off"
    Settings(slop_check="trim").validate()
    with pytest.raises(ValueError, match="Slop check"):
        Settings(slop_check="yes").validate()


def run_finalize(answer, mode, prompt=""):
    from star.doc_grounding import Grounding, GroundingPlan, finalize
    found = Grounding(status="off", plan=GroundingPlan(retrieve="none", passages=0, max_chars=0, check_luau=False),
                      client=None, passages=[])
    route = SimpleNamespace(quick=True, task_timeout=600, model="m", response_tokens=1600)
    messages = [{"role": "assistant", "content": answer}]
    return asyncio.run(finalize(found, route, (answer, messages, []), settings=SimpleNamespace(slop_check=mode),
                                prompt=prompt))


def test_the_chat_answer_is_untouched_when_off_flagged_when_asked_and_trimmed_only_in_trim_mode():
    answer = ("Sure! Here is the script:\n\n```luau\nlocal s = game:GetService(\"Playerz\")\n```\n\n"
              "Let me know if you need anything else!\n")
    off, _, archive = run_finalize(answer, "off")
    assert off == answer and archive == []
    flagged, messages, archive = run_finalize(answer, "flag")
    assert flagged.startswith("Sure! Here is the script:") and "Slop check by STAR: the code names Roblox API(s)" in flagged
    assert "Playerz" in flagged and messages[-1]["content"] == flagged
    assert archive[-1]["star_slop"]["hard"] and archive[-1]["star_slop"]["trimmed_lines"] == 0
    trimmed, _, archive = run_finalize(answer, "trim")
    assert trimmed.startswith("```luau") and "Let me know" not in trimmed and "Slop check by STAR" in trimmed
    assert archive[-1]["star_slop"]["trimmed_lines"] == 2
    clean, _, archive = run_finalize("```luau\nlocal x = 1\n```\n", "trim")
    assert clean == "```luau\nlocal x = 1\n```\n" and archive[-1]["star_slop"]["score"] == 0


def test_night_school_measures_or_gates_slop_only_when_asked(tmp_path):
    sys.path.insert(0, str(ROOT / "server" / "night_school"))
    from nightschool import fake
    from nightschool.config import Settings
    from nightschool.real import RealModel
    settings = Settings(home=tmp_path, brain_url="http://127.0.0.1:9", key_file=str(tmp_path / "k"), slop="off")
    (tmp_path / "k").write_text("STAR_SERVER_KEY=test\n", encoding="utf-8")
    task = fake.practice_task("X-1", "limitX1")
    answer = ("I tested this and it works perfectly.\n\n```lua\nlocal function limitX1(value: number): number\n"
              "\treturn math.clamp(value, 0, 100)\nend\n\nreturn limitX1\n```\n")

    def scored(mode):
        settings.slop = mode
        model = RealModel.__new__(RealModel)
        model.settings, model._luau_check, model._sandbox, model.prelude = settings, fake.luau_ok, None, ""
        return model.score(task, answer)

    assert "slop" not in [c.id for c in scored("off").checks]
    measured = scored("measure")
    recorded = next(c for c in measured.checks if c.id == "slop")
    assert recorded.ok and recorded.detail.startswith("slop ") and "P06.unverified_claim" in recorded.detail
    gated = scored("gate")
    assert not gated.passed and any(r.startswith("slop: slop") and "HARD" in r for r in gated.reasons)
