"""Diff-only answers for edit requests (star/edit_format.py) and the opt-in desktop turn that uses them."""
import json
from pathlib import Path

import pytest

from star import edit_format as ef
from star.edit_match import EditMismatch, apply_edit
from star.luau_lint import Finding
from star.react_shell import PERMITTED_SETTINGS
from tests.test_model_routing import Client, Models, clean_process_memory, desk, reply  # noqa: F401  (fixtures)

FENCE = "`" * 3
SOURCE = (
    "local Players = game:GetService(\"Players\")\n"
    "local Ammo = {}\n"
    "\n"
    "local MAX_AMMO = 30\n"
    "local counts = {}\n"
    "\n"
    "function Ammo.give(player, amount)\n"
    "\tlocal now = counts[player] or 0\n"
    "\tcounts[player] = now + amount\n"
    "\treturn counts[player]\n"
    "end\n"
    "\n"
    "function Ammo.take(player)\n"
    "\tcounts[player] = (counts[player] or 0) - 1\n"
    "\treturn counts[player]\n"
    "end\n"
    "\n"
    "Players.PlayerRemoving:Connect(function(player)\n"
    "\tcounts[player] = nil\n"
    "end)\n"
    "\n"
    "return Ammo\n"
)
PROMPT = ("My paintball ammo module lets ammo go above MAX_AMMO and below zero. Fix it.\n\n"
          + FENCE + "lua\n" + SOURCE + FENCE + "\n")
EDIT_ANSWER = (
    "`give` never capped the total and `take` never stopped at zero; both now clamp.\n\n"
    + FENCE + "lua\n"
    "<<<<<<< SEARCH\n"
    "\tcounts[player] = now + amount\n"
    "=======\n"
    "\tcounts[player] = math.min(MAX_AMMO, now + amount)\n"
    ">>>>>>> REPLACE\n"
    "<<<<<<< SEARCH\n"
    "\tcounts[player] = (counts[player] or 0) - 1\n"
    "=======\n"
    "\tcounts[player] = math.max(0, (counts[player] or 0) - 1)\n"
    ">>>>>>> REPLACE\n"
    + FENCE + "\n"
)


def no_lint(code):
    return []


# ------------------------------------------------------------------ which prompts are edit requests

def test_a_fenced_script_with_a_change_request_is_an_edit():
    request = ef.find_edit(PROMPT)
    assert request is not None and request.source == SOURCE and request.lang == "lua"
    assert request.prompt.startswith(PROMPT.rstrip()) and request.prompt.endswith(ef.INSTRUCTION)


def test_a_bug_report_without_an_edit_verb_is_an_edit_too():
    # EDIT-16's wording: no "fix" or "change", only what the code must do instead.
    prompt = "take() returns the wrong count. It must stop at zero.\n\n" + FENCE + "lua\n" + SOURCE + FENCE
    assert ef.find_edit(prompt) is not None


@pytest.mark.parametrize("prompt", [
    "Explain what this module does.\n\n" + FENCE + "lua\n" + SOURCE + FENCE,              # no change asked
    "Fix this:\n\n" + FENCE + "lua\nlocal x = 1\nreturn x\n" + FENCE,                      # too short to gain
    "Fix these two files.\n\n" + FENCE + "lua\n" + SOURCE + FENCE + "\n\n" + FENCE + "lua\n" + SOURCE + FENCE,
    "Make me a door that opens with a ProximityPrompt.",                                    # no code at all
])
def test_other_prompts_keep_the_normal_answer(prompt):
    assert ef.find_edit(prompt) is None


def test_unfenced_code_after_the_request_is_found_as_in_the_golden_tasks():
    root = Path(__file__).resolve().parents[1]
    tasks = json.loads((root / "evals/roblox/golden-tasks-creation-v1.json").read_text(encoding="utf-8"))
    task = next(t for t in tasks if t["id"] == "ENG-01")
    request = ef.find_edit(task["prompt"])
    assert request is not None and request.lang == "luau"
    assert request.source.startswith("local function addItem(stacks, name, amount, maxStack)\n")
    assert request.source.rstrip().endswith("return addItem")


def test_a_sentence_after_unfenced_code_is_not_guessed_at():
    prompt = "Fix this.\n" + SOURCE + "Also tell me whether this is the right way to store ammo per player.\n"
    assert ef.find_edit(prompt) is None


# ------------------------------------------------------------------ parsing and applying

def test_search_replace_blocks_apply_and_the_full_code_is_shown():
    request = ef.find_edit(PROMPT)
    done = ef.finish(request, EDIT_ANSWER, lint=no_lint)
    assert done.ok and done.reason == "applied" and done.edits == 2
    assert "<<<<<<<" not in done.answer and ">>>>>>>" not in done.answer
    assert done.answer.startswith("`give` never capped the total")
    code = done.answer.split(FENCE + "lua\n", 1)[1].rsplit(FENCE, 1)[0]
    assert code == SOURCE.replace("now + amount", "math.min(MAX_AMMO, now + amount)").replace(
        "(counts[player] or 0) - 1", "math.max(0, (counts[player] or 0) - 1)")


def test_a_block_with_other_indentation_lands_with_the_files_indentation():
    answer = "<<<<<<< SEARCH\n    counts[player] = now + amount\n=======\n    counts[player] = now\n>>>>>>> REPLACE\n"
    done = ef.finish(ef.find_edit(PROMPT), answer, lint=no_lint)
    assert done.ok and "\n\tcounts[player] = now\n" in done.answer


def test_a_unified_diff_is_accepted_too():
    answer = (FENCE + "diff\n@@ -7,4 +7,4 @@\n function Ammo.give(player, amount)\n \tlocal now = counts[player] or 0\n"
              "-\tcounts[player] = now + amount\n+\tcounts[player] = math.min(MAX_AMMO, now + amount)\n"
              " \treturn counts[player]\n" + FENCE + "\nCapped at MAX_AMMO.")
    done = ef.finish(ef.find_edit(PROMPT), answer, lint=no_lint)
    assert done.ok and "math.min(MAX_AMMO, now + amount)" in done.answer and "@@" not in done.answer
    assert done.answer.startswith("Capped at MAX_AMMO.")


@pytest.mark.parametrize("answer, reason", [
    ("<<<<<<< SEARCH\n\tcounts[player] = now + 2\n=======\n\tx\n>>>>>>> REPLACE\n", "did not apply"),
    ("<<<<<<< SEARCH\n\treturn counts[player]\n=======\n\treturn 0\n>>>>>>> REPLACE\n", "did not apply"),  # 2 places
    ("<<<<<<< SEARCH\n=======\nlocal y = 2\n>>>>>>> REPLACE\n", "did not apply"),                             # empty
    ("I would clamp both values.", "no SEARCH/REPLACE blocks"),
    # seen from star-fast: a second separator inside a block would put "=======" into the code
    ("<<<<<<< SEARCH\n\tcounts[player] = now + amount\n=======\n\tcounts[player] = now\n=======\n\tcounts[player] = now\n"
     ">>>>>>> REPLACE\n", "malformed"),
])
def test_an_edit_that_cannot_be_placed_safely_falls_back(answer, reason):
    done = ef.finish(ef.find_edit(PROMPT), answer, lint=no_lint)
    assert not done.ok and done.answer == "" and done.reason.startswith(reason)


def test_a_whole_file_answer_without_blocks_is_kept_as_it_is():
    answer = "Here is the fixed module.\n\n" + FENCE + "lua\n" + SOURCE.replace("now + amount", "now") + FENCE
    done = ef.finish(ef.find_edit(PROMPT), answer, lint=no_lint)
    assert done.ok and done.reason == "full" and done.answer == answer


def test_whole_line_matching_never_edits_part_of_a_line():
    source = "local x = 10\nlocal y = 2\n"
    assert apply_edit(source, "local x = 1", "local x = 2").text == "local x = 20\nlocal y = 2\n"   # the old tool way
    with pytest.raises(EditMismatch):
        apply_edit(source, "local x = 1", "local x = 2", whole_lines=True)
    assert apply_edit(source, "local x = 10", "local x = 2", whole_lines=True).text == "local x = 2\nlocal y = 2\n"


def test_a_block_whose_first_line_is_deeper_than_its_last_still_matches():
    # Found while building this: the whitespace strategy took the first line's whole indentation as the shift.
    source = "local function f()\n\tif a then\n\t\treturn 1\n\tend\nend\n"
    done = apply_edit(source, "\t\treturn 1\n\tend\nend", "\t\treturn 2\n\tend\nend", whole_lines=True)
    assert done.text == source.replace("return 1", "return 2")
    shifted = apply_edit(source, "\treturn 1\nend", "\treturn 3\nend")         # the tool path, one level shallower
    assert shifted.strategy == "whitespace" and "\t\treturn 3\n\tend\n" in shifted.text


# ------------------------------------------------------------------ checks: never worse than the original

def checker(bad_text):
    def check(code):
        bad = bad_text in code
        return {"ran": True, "ok": not bad, "error_count": 1 if bad else 0}
    return check


def test_an_edit_that_adds_a_luau_error_falls_back():
    answer = "<<<<<<< SEARCH\n\treturn counts[player]\nend\n\nfunction Ammo.take(player)\n=======\n" \
             "\treturn counts[player]\nend\n\nfunction Ammo.take(player\n>>>>>>> REPLACE\n"
    done = ef.finish(ef.find_edit(PROMPT), answer, check=checker("Ammo.take(player\n"), lint=no_lint)
    assert not done.ok and done.reason.startswith("Luau check: 1 error(s) after the edit, 0 before")


def test_errors_the_original_already_had_do_not_block_the_edit():
    def check(code):
        return {"ran": True, "ok": False, "error_count": 2 if "now + amount" in code else 1}
    assert ef.finish(ef.find_edit(PROMPT), EDIT_ANSWER, check=check, lint=no_lint).ok


def test_a_check_that_cannot_run_makes_no_claim():
    def down(code):
        raise OSError("knowledge service unavailable")
    assert ef.finish(ef.find_edit(PROMPT), EDIT_ANSWER, check=down, lint=no_lint).ok


def test_a_new_lint_finding_falls_back():
    def lint(code):
        return [Finding("deprecated-wait", 1, "wait()", "task.wait()", "warning")] if "wait()" in code else []
    answer = "<<<<<<< SEARCH\nend)\n\nreturn Ammo\n=======\nend)\n\nwait()\nreturn Ammo\n>>>>>>> REPLACE\n"
    done = ef.finish(ef.find_edit(PROMPT), answer, lint=lint)
    assert not done.ok and done.reason == "lint: new deprecated-wait"


def test_the_real_linter_runs_by_default():
    assert ef.finish(ef.find_edit(PROMPT), EDIT_ANSWER).ok


# ------------------------------------------------------------------ the desktop turn (offline fake server)

def last_answer(desk):
    rows = desk.chats.recent("STAR", 2, chat_id=desk.chat, include_events=False)
    return next(part for row in reversed(rows) for part in map(str, tuple(row)) if FENCE in part)


def test_setting_is_off_by_default_validated_and_settable_from_the_app():
    from star.desktop_core import Settings
    assert Settings().edit_diff is False
    with pytest.raises(ValueError):
        Settings(edit_diff="yes").validate()
    assert "edit_diff" in PERMITTED_SETTINGS


def test_with_the_setting_on_the_model_writes_only_the_changes(desk):
    desk.settings.edit_diff = True
    request = desk.turn(PROMPT, EDIT_ANSWER)
    assert len(desk.models.requests) == 1
    assert "STAR edit mode" in json.dumps(request["messages"][-1])
    answer = last_answer(desk)
    assert "math.min(MAX_AMMO, now + amount)" in answer and "Players.PlayerRemoving" in answer
    assert "<<<<<<<" not in answer
    finished = [e for e in desk.events if e.get("event") == "edit_diff_finished"]
    assert finished and finished[-1]["ok"] is True and finished[-1]["edits"] == 2


def test_an_edit_that_does_not_apply_is_answered_again_in_full(desk):
    desk.settings.edit_diff = True
    bad = "<<<<<<< SEARCH\n\tcounts[player] = now + 99\n=======\n\tx = 1\n>>>>>>> REPLACE\n"
    full = "Clamped both.\n\n" + FENCE + "lua\n" + SOURCE.replace("now + amount", "math.min(MAX_AMMO, now + amount)") + FENCE
    request = desk.turn(PROMPT, [reply(bad), reply(full)])
    assert len(desk.models.requests) == 2
    assert "STAR edit mode" in json.dumps(desk.models.requests[0]["messages"][-1])
    assert "STAR edit mode" not in json.dumps(request["messages"][-1])
    assert "math.min(MAX_AMMO, now + amount)" in last_answer(desk)
    finished = [e for e in desk.events if e.get("event") == "edit_diff_finished"]
    assert finished[-1]["ok"] is False and finished[-1]["reason"].startswith("did not apply")


def test_with_the_setting_off_the_prompt_is_unchanged(desk):
    request = desk.turn(PROMPT, "Clamped.\n\n" + FENCE + "lua\n" + SOURCE + FENCE)
    assert "STAR edit mode" not in json.dumps(request["messages"])
    assert not [e for e in desk.events if str(e.get("event", "")).startswith("edit_diff")]
