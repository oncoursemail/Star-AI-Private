"""S2 mistake memory and self-written fixers (star/mistake_memory.py). No model, no network."""
import asyncio
import json

import pytest

from star import mistake_memory as mm, verify_ladder as vl
from star.desktop_core import Settings
from star.eval_runner import parse_sets


def row(before, after, task, sig="lint:deprecated-task-global", verified=True, **extra):
    return {"rung": "lint", "signature": sig, "message": "Deprecated global wait().", "verified": verified,
            "diff": f"-{before}\n+{after}", "src": f"run/file:{task}#1", **extra}


WAIT_ROWS = [row("\twait(1)", "\ttask.wait(1)", "T1"), row("wait(delay)", "task.wait(delay)", "T2"),
             row("\t\tspawn(function()", "\t\ttask.spawn(function()", "T3")]
GUARD = [("g1", "local x = task.wait(1)\nprint(x)\n"), ("g2", "-- wait(1) in a comment\nlocal s = 'wait(2)'\n"),
         ("g3", "local function run(wait: (number) -> ())\n\twait(1)\nend\n")]


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("STAR_MISTAKE_LOG", str(tmp_path / "mistakes.jsonl"))
    monkeypatch.setenv("STAR_FIXERS", str(tmp_path / "fixers.json"))
    for name in ("STAR_VERIFY_SSH", "STAR_EVAL_SANDBOX_SSH", "STAR_EVAL_SSH"):
        monkeypatch.delenv(name, raising=False)


def test_three_verified_fixes_of_one_signature_become_a_validated_rule():
    fixers, rejected = mm.synthesize(WAIT_ROWS, GUARD)
    assert not rejected and len(fixers) == 1
    fixer = fixers[0]
    assert fixer["active"] is True and fixer["support"] == 3
    assert fixer["validation"]["fixed"] == fixer["validation"]["cases"] == 3
    assert fixer["validation"]["false_changes"] == 0
    new, used = mm.apply("wait(0.5)\nspawn(f)\nlocal n = task.wait(1)\nself.wait(2)\nmodel:wait(3)\n", [fixer])
    assert new == "task.wait(0.5)\ntask.spawn(f)\nlocal n = task.wait(1)\nself.wait(2)\nmodel:wait(3)\n"
    assert used == [fixer["id"]]
    assert mm.lint("print(1)\nwait(2)\n", [fixer]) == [(2, "Deprecated global wait().")]


def test_rules_leave_comments_strings_and_names_the_script_defines_alone():
    fixer = mm.synthesize(WAIT_ROWS, GUARD)[0][0]
    for code in ("-- wait(1)\n", "print('wait(1)')\n", "local wait = function() end\nwait(1)\n",
                 "local function f(wait)\n\twait(1)\nend\n", "function wait() end\nwait()\n", "x.wait(1)\n"):
        assert mm.apply(code, [fixer]) == (code, [])


def test_a_rule_needs_three_tasks_and_must_not_change_the_guard_blocks():
    assert mm.synthesize(WAIT_ROWS[:2], GUARD) == ([], [])                      # under the support floor
    same_task = [row("wait(1)", "task.wait(1)", "T1"), row("wait(2)", "task.wait(2)", "T1"),
                 row("wait(3)", "task.wait(3)", "T1")]
    assert mm.synthesize(same_task, GUARD) == ([], [])                          # one task is one failure
    fixers, rejected = mm.synthesize(WAIT_ROWS, GUARD + [("keeps", "local e = foo.bar(wait(1))\n")])
    assert fixers == [] and "guard block" in rejected[0]["reasons"][-1]
    rejected = mm.synthesize(WAIT_ROWS, [])[1]
    assert rejected[0]["reasons"][-1] == "no guard blocks available to prove it changes nothing else"


def test_unverified_rows_and_rule_applications_never_train_a_rule():
    rows = [dict(r, verified=False) for r in WAIT_ROWS] + [dict(r, by="fixer:fx-1") for r in WAIT_ROWS]
    assert mm.synthesize(rows, GUARD) == ([], [])


def test_a_capture_matches_only_names_seen_in_the_cases():
    cases = [row("game.Players.PlayerAdded:Connect(f)", 'game:GetService("Players").PlayerAdded:Connect(f)', "A", sig="s"),
             row("require(game.ServerStorage.M)", 'require(game:GetService("ServerStorage").M)', "B", sig="s"),
             row("local x = game.Workspace", 'local x = game:GetService("Workspace")', "C", sig="s")]
    fixer = mm.synthesize(cases, GUARD)[0][0]
    new, _ = mm.apply("local a = game.Players\nlocal b = game.JobId\nlocal c = game.Lighting\n", [fixer])
    assert new == 'local a = game:GetService("Players")\nlocal b = game.JobId\nlocal c = game.Lighting\n'


def test_stored_rules_load_only_when_validated(tmp_path):
    fixer = mm.synthesize(WAIT_ROWS, GUARD)[0][0]
    path = tmp_path / "fixers.json"
    mm.save_fixers([fixer, dict(fixer, id="fx-bad", validation=dict(fixer["validation"], false_changes=1)),
                    dict(fixer, id="fx-off", active=False)], path)
    assert [f["id"] for f in mm.active_fixers(path)] == [fixer["id"]]


def test_retrieval_picks_only_verified_fixes_that_match_and_stays_small():
    rows = WAIT_ROWS + [row("x.Colour = c", "x.Color = c", "T9", sig="api:member", verified=False,
                            message="unknown member Colour")]
    note, used = mm.pitfalls("Write a loop that will wait for the player and then respawn them", rows)
    assert used == ["lint:deprecated-task-global"] and "task." in note and "Colour" not in note
    assert len(note) <= mm.MAX_CHARS
    assert mm.pitfalls("Sort a table of numbers", rows) == ("", [])
    assert mm.pitfalls("wait for the player", rows, max_chars=60) == ("", [])


def fence(code):
    return f"```luau\n{code}```"


def ok(code, strict=False):
    return {"ran": True, "ok": True, "errors": []}


def test_the_ladder_applies_a_rule_before_any_model_fix_call_and_records_it(tmp_path):
    fixer = mm.synthesize(WAIT_ROWS, GUARD)[0][0]
    calls = []

    async def fix(code, failure, members):
        calls.append(code)
        return ""
    tools = vl.Tools(checker=ok, fix=fix, fixers=[fixer], prompt="wait then print")
    answer, summary = asyncio.run(vl.review("Here:\n\n" + fence("wait(1)\nprint('go')\n"), tools))
    assert "task.wait(1)\nprint('go')" in answer and calls == []
    assert summary["fixed"] is True and "self-written rewrite rule" in answer
    rows = mm.read_rows(tmp_path / "mistakes.jsonl")
    assert rows and rows[0]["by"] == "fixer:" + fixer["id"] and rows[0]["verified"] is True
    assert rows[0]["task"] == "wait then print"
    # a rule application is not new evidence: it never feeds back into rule learning
    assert mm.synthesize(rows * 3, GUARD) == ([], [])


def test_a_rule_that_makes_the_block_worse_is_dropped():
    fixer = mm.synthesize(WAIT_ROWS, GUARD)[0][0]

    def checker(code, strict=False):          # the rewritten block "fails to compile"
        bad = "task.wait" in code
        errors = [{"line": 1, "column": 1, "kind": "SyntaxError", "message": "boom"}] if bad else []
        return {"ran": True, "ok": not bad, "errors": errors}
    answer, summary = asyncio.run(vl.review(fence("wait(1)\n"), vl.Tools(checker=checker, fixers=[fixer],
                                                                        deprecated=False)))
    assert "task.wait" not in answer and summary["fixed"] is False


def test_setting_defaults_to_retrieval_only_and_validates():
    assert Settings().mistake_memory == "retrieve"
    Settings(mistake_memory="fix").validate()
    Settings(mistake_memory="off").validate()
    with pytest.raises(ValueError):
        Settings(mistake_memory="on").validate()
    assert parse_sets(["mistake_memory=fix"]) == {"mistake_memory": "fix"}


def test_the_shipped_rules_are_validated_change_no_guard_block_and_reproduce_their_cases():
    shipped = mm.active_fixers()
    guard = mm.guard_blocks()
    assert len(shipped) >= 1
    for fixer in shipped:
        assert all(mm.apply_one(before, fixer).strip() == after.strip() for before, after in fixer["cases"])
        if guard:
            assert [label for label, code in guard if mm.apply_one(code, fixer) != code] == []
    assert json.loads(mm.SHIPPED_FIXERS.read_text(encoding="utf-8"))["version"] == 1
