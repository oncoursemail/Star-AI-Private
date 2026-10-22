"""S1 check-fix loop (star/verify_ladder.py). Services are faked: no network, no model, no sandbox."""
import asyncio
import json
from time import monotonic
from types import SimpleNamespace

import pytest

from star import slop, verify_ladder as vl
from star.desktop_core import Settings
from star.doc_grounding import CHECK_MARKER, Grounding, GroundingPlan, finalize
from star.eval_checks import split_answer
from star.eval_runner import parse_sets

BROKEN = "local Players = game:GetService(\"Players\")\nlocal x = \nprint(x)\n"
GOOD = "local Players = game:GetService(\"Players\")\nlocal x = 1\nprint(x)\n"
INVENTED = "local p = Instance.new(\"Part\")\np.Colour = Color3.new(1, 0, 0)\n"


def checker(code, strict=False):
    """A stand-in for /luau/check: `local x = ` with nothing after it is a syntax error on that line."""
    for number, line in enumerate(code.splitlines(), 1):
        if line.rstrip().endswith("="):
            return {"ran": True, "ok": False, "errors": [{"line": number, "column": 1, "kind": "SyntaxError",
                                                        "message": "Expected identifier when parsing expression"}]}
    return {"ran": True, "ok": True, "errors": []}


def fence(code):
    return f"```luau\n{code}```"


def fixer(*replies):
    calls = []

    async def fix(code, failure, members):
        calls.append((code, failure, members))
        return replies[min(len(calls), len(replies)) - 1]
    return fix, calls


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    for name in ("STAR_VERIFY_SSH", "STAR_EVAL_SANDBOX_SSH", "STAR_EVAL_SSH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STAR_MISTAKE_LOG", str(tmp_path / "mistakes.jsonl"))
    return tmp_path / "mistakes.jsonl"


def review(answer, tools, **kw):
    return asyncio.run(vl.review(answer, tools, **kw))


def test_a_failing_block_is_fixed_with_the_exact_error_and_shown_as_verified(isolated):
    fix, calls = fixer(fence(GOOD))
    answer, record = review("Here:\n\n" + fence(BROKEN), vl.Tools(checker=checker, fix=fix, prompt="print x"))
    assert len(calls) == 1
    code, failure, _ = calls[0]
    assert code == BROKEN and failure.rung == "compile" and failure.line == 2
    request = vl.fix_request("print x", code, failure)
    assert "Failing check (compile): line 2: Expected identifier" in request and "   2>" in request
    body, footer = split_answer(answer)
    assert fence(GOOD) in body and BROKEN not in body
    assert footer.startswith("\n\n" + CHECK_MARKER) and ": verified:" in footer and "fixed it in 1 round" in footer
    assert record["verified"] and record["fixed"]
    rows = [json.loads(line) for line in isolated.read_text(encoding="utf-8").splitlines()]
    assert rows == [{**rows[0], "rung": "compile", "verified": True}]
    assert "-local x =" in rows[0]["diff"] and "+local x = 1" in rows[0]["diff"]
    assert rows[0]["signature"] == "compile:Expected identifier when parsing expression"


def test_a_fix_that_does_not_help_keeps_the_original_and_says_unverified_plainly(isolated):
    fix, calls = fixer(fence(BROKEN.replace("print(x)", "print(x, 2)")))
    answer, record = review(fence(BROKEN), vl.Tools(checker=checker, fix=fix), rounds=2)
    assert len(calls) == 1                     # no progress: the second round is not tried
    assert fence(BROKEN) in answer
    assert "unverified: compile failed: line 2: Expected identifier" in answer and "1 fix round(s) tried" in answer
    assert not record["verified"] and record["blocks"][0]["stopped"] == "the fix did not get further up the ladder"
    row = json.loads(isolated.read_text(encoding="utf-8"))
    assert row["verified"] is False and row["diff"] == ""


def test_no_fix_call_without_time_or_rounds_and_an_unchanged_reply_stops():
    for kw in ({"rounds": 0}, {"budget": 10.0}):
        fix, calls = fixer(fence(GOOD))
        answer, _ = review(fence(BROKEN), vl.Tools(checker=checker, fix=fix), **kw)
        assert calls == [] and "unverified" in answer
    fix, calls = fixer(fence(BROKEN))
    _, record = review(fence(BROKEN), vl.Tools(checker=checker, fix=fix))
    assert len(calls) == 1 and record["blocks"][0]["stopped"] == "the fix changed nothing usable"


def test_invented_members_fail_the_api_rung_with_the_real_member_list():
    dump = slop.bundled_api_dump()
    assert dump is not None
    tools = vl.Tools(checker=checker, dump=dump)
    rung = vl.check_api(INVENTED, tools)
    assert rung.status == "fail" and rung.line == 2 and "Colour is not a member of Part" in rung.detail
    assert rung.signature == "api:unknown-member:Part.Colour" and rung.classes == ("Part",)
    assert "Color" in vl._members(rung.classes, dump).split(": ", 1)[1].split(", ")
    assert vl.check_api(INVENTED.replace("Colour", "Color"), tools).status == "pass"


def test_unknown_globals_in_a_usage_example_block_are_placeholders_as_in_the_grader():
    def check(code, strict=False):
        return {"ran": True, "ok": False, "errors": [{"line": 1, "column": 1, "kind": "TypeError",
                                                    "message": "Unknown global 'path'; consider assigning to it first"}]}
    example = "local M = require(path.to.Module)\n"
    assert vl.check_compile(example, vl.Tools(checker=check)).status == "fail"
    second = vl.check_compile(example, vl.Tools(checker=check, first_block=False))
    assert second.status == "pass" and second.context == ("path",)


def test_ranking_prefers_getting_further_then_fewer_errors():
    fail = lambda rung, n=1: vl.Rung(rung, "fail", errors=n)  # noqa: E731
    ok = lambda rung: vl.Rung(rung, "pass")                    # noqa: E731
    assert vl.ladder_rank([ok("compile"), fail("api")]) > vl.ladder_rank([fail("compile")])
    assert vl.ladder_rank([fail("compile", 1)]) > vl.ladder_rank([fail("compile", 3)])
    assert vl.ladder_rank([ok("compile"), vl.Rung("api", "skip"), ok("run")]) > vl.ladder_rank(
        [ok("compile"), ok("api"), fail("run")])


class Runner:
    def __init__(self, stdout="", timed_out=False, error=""):
        self.result = SimpleNamespace(stdout=stdout, timed_out=timed_out, error=error, rc=0)
        self.sources = []

    def run(self, source):
        self.sources.append(source)
        return self.result


def test_the_mock_harness_puts_the_block_where_errors_are_mapped_back():
    script, first = vl.mock_harness(GOOD)
    lines = script.splitlines()
    assert lines[first - 1] == GOOD.splitlines()[0] and lines[first + 1] == "print(x)"
    assert 'kind = "Script"' in script and "W.addPlayer" in script and script.rstrip().endswith("print('@@DONE')")
    module, _ = vl.mock_harness("local M = {}\nreturn M\n")
    assert 'kind = "ModuleScript"' in module and "StarModule" in module
    snippet, _ = vl.mock_harness("function Sight.canSee()\n\treturn true\nend\n", ("BuyItem",))
    assert 'local Sight = __unmocked("Sight")' in snippet and 'local BuyItem = __unmocked("BuyItem")' in snippet


def test_run_rung_reads_real_errors_mock_limits_and_timeouts():
    _, first = vl.mock_harness(GOOD)
    real = Runner(f"@@ERR\t./t.luau:{first + 2}: attempt to index nil with 'x' | ./t.luau:9 function f\n@@DONE\n")
    rung = vl.check_run(GOOD, vl.Tools(runner=real))
    assert rung.status == "fail" and rung.line == 3 and "line 3: attempt to index nil with 'x'" in rung.detail
    assert rung.signature == "run:line N: attempt to index nil with '*'"
    limited = Runner(f"@@ERR\t./t.luau:{first}: UNSUPPORTED global TweenInfo in twin mock\n@@DONE\n")
    assert vl.check_run(GOOD, vl.Tools(runner=limited)).status == "skip"
    assert vl.check_run(GOOD, vl.Tools(runner=Runner("", timed_out=True))).status == "fail"
    assert vl.check_run(GOOD, vl.Tools(runner=Runner("@@DONE\n"))).status == "pass"
    assert vl.check_run(GOOD, vl.Tools(runner=Runner(error="ssh failed"))).status == "skip"
    assert vl.check_run(GOOD, vl.Tools()).detail == "no server sandbox is configured"
    client = Runner("@@DONE\n")
    assert vl.check_run("local p = game.Players.LocalPlayer\n", vl.Tools(runner=client)).status == "skip"
    assert client.sources == []


def test_generated_tests_are_written_once_run_and_reported_as_generated():
    module = "local M = {}\nfunction M.add(a, b)\n\treturn a + b\nend\nreturn M\n"
    written = []

    async def write_tests(code):
        written.append(code)
        return "```luau\nassert(result.add(1, 2) == 3)\nassert(result.add(2, 2) == 5)\n```"
    runner = Runner("@@DONE\n@@T\tpass\t1\tassert(result.add(1, 2) == 3)\n"
                    "@@T\tfail\t2\tassert(result.add(2, 2) == 5)\t./t.luau:9: assertion failed!\n")
    state = {}
    rungs = asyncio.run(vl.run_rungs(module, vl.Tools(checker=checker, write_tests=write_tests, runner=runner),
                                     state))
    assert [r.status for r in rungs] == ["pass", "skip", "pass", "fail"]   # api: no dump given
    assert rungs[-1].detail == "generated test assert(result.add(2, 2) == 5) failed: assertion failed!"
    assert "local result = (function()" in runner.sources[-1] and "@@T" in runner.sources[-1]
    asyncio.run(vl.run_rungs(module, vl.Tools(checker=checker, write_tests=write_tests, runner=runner), state))
    assert len(written) == 1
    assert vl.parse_tests("```luau\nassert(#result.list({1, 2}) == 2)\nassert(result.add(1, 1) == 2)\n```")
    assert vl.parse_tests("```luau\nassert(result.a() == 1) -- a note\n-- Let's check more.\nassert(result.b() == 2)\n```"
                          ) == "assert(result.a() == 1)\nassert(result.b() == 2)\n"
    for bad in ("```luau\nassert(true)\n```", "```luau\nprint(1)\nassert(result.x == 1)\n```", "no fence"):
        with pytest.raises(ValueError):
            vl.parse_tests(bad)
    request = vl.fix_request("add", module, rungs[-1])
    assert "can be wrong" in request
    engine = asyncio.run(vl.run_rungs(GOOD, vl.Tools(checker=checker, write_tests=write_tests,
                                                     runner=Runner("@@DONE\n")), {}))
    assert engine[-1].status == "skip" and "not a pure module" in engine[-1].detail


def test_finalize_runs_the_ladder_instead_of_the_static_check_only_when_on():
    calls = []

    class Model:
        def __init__(self):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        async def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=fence(GOOD)))])
    client = SimpleNamespace(luau_check=checker)
    plan = GroundingPlan(retrieve="none", passages=0, max_chars=0, check_luau=True)
    route = SimpleNamespace(quick=False, task_timeout=900, model="star-fast", response_tokens=1600)

    def run(mode):
        found = Grounding(status="off", plan=plan, client=client, passages=[])
        answer = "Here:\n\n" + fence(BROKEN)
        return asyncio.run(finalize(found, route, (answer, [{"role": "assistant", "content": answer}], []),
                                    model_client=Model(), prompt="print x", started=monotonic(),
                                    settings=SimpleNamespace(slop_check="off", verify_ladder=mode, verify_rounds=2,
                                                             verify_budget_s=240)))
    answer, messages, archive = run("on")
    assert fence(GOOD) in answer and messages[-1]["content"] == answer
    assert archive[0]["star_verify"]["fixed"] is True
    assert calls[0]["messages"][0]["content"] == vl._FIX_SYSTEM
    calls.clear()
    answer, _, archive = run("off")
    assert not any("star_verify" in item for item in archive)
    assert calls and calls[0]["messages"][0]["content"] != vl._FIX_SYSTEM   # the old static repair


def test_settings_and_eval_switches():
    Settings(verify_ladder="on", verify_rounds=3, verify_budget_s=300).validate()
    assert Settings().verify_ladder == "on"
    for bad in ({"verify_ladder": "yes"}, {"verify_rounds": 9}, {"verify_budget_s": 5}):
        with pytest.raises(ValueError):
            Settings(**bad).validate()
    assert parse_sets(["verify_ladder=on", "verify_rounds=2"]) == {"verify_ladder": "on", "verify_rounds": 2}


def test_mistake_memory_keeps_no_addresses_or_keys(tmp_path):
    address = ".".join(("10", "20", "30", "40"))         # built here so no address sits in the source
    record = {"mistakes": [{"rung": "run", "signature": "run:x", "verified": False,
                            "message": f"ssh someone@{address} failed, api_key=abc123 token " + "A" * 40}]}
    path = tmp_path / "m.jsonl"
    assert vl.remember([record], path=path) == 1
    text = path.read_text(encoding="utf-8")
    assert address not in text and "abc123" not in text and "A" * 40 not in text
