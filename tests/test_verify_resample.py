"""Opt-in fresh answer after a compile failure (star/verify_ladder.py resample_answer, setting verify_resample).
Services are faked: no network, no model, no sandbox."""
import asyncio
from time import monotonic
from types import SimpleNamespace

import pytest

from star import best_of_n, slop, verify_ladder as vl
from star.desktop_core import Settings

BROKEN = "local Players = game:GetService(\"Players\")\nlocal x = \nprint(x)\n"
GOOD = "local Players = game:GetService(\"Players\")\nlocal x = 1\nprint(x)\n"
OTHER = "local Players = game:GetService(\"Players\")\nlocal y = 2\nprint(y)\n"


def checker(code, strict=False):
    for number, line in enumerate(code.splitlines(), 1):
        if line.rstrip().endswith("="):
            return {"ran": True, "ok": False, "errors": [{"line": number, "column": 1, "kind": "SyntaxError",
                                                        "message": "Expected identifier when parsing expression"}]}
    return {"ran": True, "ok": True, "errors": []}


def fence(code):
    return f"```luau\n{code}```"


def asker(*replies):
    calls = []

    async def resample(temperature):
        calls.append(temperature)
        reply = replies[min(len(calls), len(replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply
    return resample, calls


def fixer(*replies):
    calls = []

    async def fix(code, failure, members):
        calls.append(code)
        return replies[min(len(calls), len(replies)) - 1]
    return fix, calls


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    for name in ("STAR_VERIFY_SSH", "STAR_EVAL_SANDBOX_SSH", "STAR_EVAL_SSH", "STAR_CANDIDATE_POOL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STAR_MISTAKE_LOG", str(tmp_path / "mistakes.jsonl"))


def review(answer, tools, **kw):
    return asyncio.run(vl.review(answer, tools, **kw))


def test_a_compile_failure_is_replaced_by_the_first_fresh_answer_that_compiles():
    resample, asked = asker("A different take.\n\n" + fence(GOOD))
    fix, fixes = fixer(fence(OTHER))
    events = []
    answer, record = review("Here:\n\n" + fence(BROKEN), vl.Tools(checker=checker, resample=resample, fix=fix),
                            on_event=events.append)
    assert asked == [0.7] and fixes == []
    assert "A different take." in answer and fence(GOOD) in answer and BROKEN not in answer
    assert "The first version failed the compile check" in answer and "wrote the answer again (1 time(s))" in answer
    assert record["verified"] and record["resample"]["accepted"] and record["resample"]["tried"] == 1
    assert {"event": "verify_resampled", "accepted": True, "tried": 1, "rung": "compile"} in events


def test_a_clean_answer_is_never_resampled():
    resample, asked = asker(fence(OTHER))
    answer, record = review(fence(GOOD), vl.Tools(checker=checker, resample=resample))
    assert asked == [] and "resample" not in record and fence(GOOD) in answer


def test_an_invented_api_member_is_not_a_reason_to_resample():
    invented = 'local p = Instance.new("Part")\np.Colour = Color3.new(1, 0, 0)\n'
    resample, asked = asker(fence(GOOD))
    answer, record = review(fence(invented), vl.Tools(checker=checker, dump=slop.bundled_api_dump(), resample=resample))
    assert asked == [] and "resample" not in record      # it compiles; answers the API rung flags pass as often as the rest


def test_resample_is_off_without_the_callable():
    fix, fixes = fixer(fence(GOOD))
    answer, record = review(fence(BROKEN), vl.Tools(checker=checker, fix=fix))
    assert len(fixes) == 1 and "resample" not in record and "wrote the answer again" not in answer


def test_fresh_answers_that_still_fail_leave_the_original_and_the_fix_rounds_run():
    resample, asked = asker("Again.\n\n" + fence(BROKEN), "Third.\n\n" + fence(BROKEN))
    fix, fixes = fixer(fence(GOOD))
    answer, record = review("Original prose.\n\n" + fence(BROKEN), vl.Tools(checker=checker, resample=resample, fix=fix))
    assert asked == [0.7, 0.9] and len(asked) == vl.RESAMPLE_MAX
    assert record["resample"]["tried"] == 2 and not record["resample"]["accepted"]
    assert "Original prose." in answer and "Again." not in answer
    assert fixes == [BROKEN] and record["verified"] and record["fixed"]       # the ladder then fixed the original


def test_an_answer_without_a_luau_block_does_not_count_as_clearing():
    resample, asked = asker("No code here.", "Still none.")
    answer, record = review(fence(BROKEN), vl.Tools(checker=checker, resample=resample))
    assert asked == [0.7, 0.9] and not record["resample"]["accepted"] and fence(BROKEN) in answer


def test_not_enough_time_left_asks_for_nothing():
    resample, asked = asker(fence(GOOD))
    answer, record = review(fence(BROKEN), vl.Tools(checker=checker, resample=resample),
                            deadline=monotonic() + vl.FIX_RESERVE_SECONDS + vl.RESAMPLE_MIN_SECONDS - 5)
    assert asked == [] and record["resample"]["stopped"] == "time budget spent"
    assert fence(BROKEN) in answer


def test_a_failing_resample_call_is_not_an_error():
    resample, asked = asker(RuntimeError("server busy"))
    answer, record = review(fence(BROKEN), vl.Tools(checker=checker, resample=resample))
    assert asked == [0.7] and record["resample"]["stopped"] == "resample failed (RuntimeError)"
    assert fence(BROKEN) in answer


def test_the_setting_defaults_off_and_rejects_other_values():
    assert Settings().verify_resample == "off"
    Settings(verify_resample="on").validate()
    with pytest.raises(ValueError, match="resample"):
        Settings(verify_resample="maybe").validate()


def test_resample_tool_asks_the_same_request_at_the_given_temperature():
    seen = {}

    class Completions:
        async def create(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="fresh"))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    request = {"messages": [{"role": "user", "content": "write it"}], "tools": None}
    resample = best_of_n.resample_tool(client, Settings(), request, model="star-fast", max_tokens=900)
    assert asyncio.run(resample(0.9)) == "fresh"
    assert seen["messages"] == request["messages"] and seen["temperature"] == 0.9
    assert seen["model"] == "star-fast" and seen["max_tokens"] == 900 and "tools" not in seen
