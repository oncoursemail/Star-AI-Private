import asyncio
import json
from types import SimpleNamespace

import pytest

from star import providers, thinking_budget as tb
from star.verify_ladder import Rung, model_tools

SYSTEM = ("Build a full inventory system from scratch: a ModuleScript on the server, a LocalScript for the HUD, and "
          "remotes that validate every client request. Players must be able to buy, sell and trade items.")
CHAT = "Hey, what is a RemoteEvent?"
SMALL = "Rename the variable coins to gold in my script."
DEBUG = "My script fails with an error: attempt to index nil value 'leaderstats' on line 12. " * 3


def test_chat_and_small_edits_do_not_think():
    assert not tb.plan_turn("auto", CHAT).active
    assert not tb.plan_turn("auto", SMALL).active
    assert not tb.plan_turn("auto", "Make a part red.").active


def test_hard_turns_get_a_bigger_budget_than_easy_ones():
    hard, debug = tb.plan_turn("auto", SYSTEM), tb.plan_turn("auto", DEBUG)
    assert hard.active and debug.active
    assert hard.tokens >= tb.LEVELS["medium"]
    assert debug.tokens >= tb.LEVELS["medium"]
    medium_ask = tb.plan_turn("auto", "Write a datastore module that saves the coins of each player when they leave the game and loads them again "
                                    "when they join, with a retry and a short delay between tries so no coins are lost on a quick rejoin.")
    assert 0 < medium_ask.tokens < hard.tokens          # a low-pass-rate family alone gives only a small budget


def test_off_quick_and_plain_profiles_never_think():
    assert tb.plan_turn("off", SYSTEM) == tb.Plan(why="off")
    assert not tb.plan_turn("auto", SYSTEM, quick=True).active
    assert not tb.plan_turn("auto", SYSTEM, profile="fast").active
    assert not tb.plan_turn("auto", SYSTEM, profile="vision").active
    assert tb.plan_turn("always", CHAT).tokens == tb.LEVELS["large"]
    assert not tb.plan_turn("always", CHAT, quick=True).active


def test_low_pass_rate_family_raises_the_level():
    prompt = "Write a script that makes a shop where players spend coins on swords."
    flat = {"economy": (9, 10)}
    low = {"economy": (1, 10)}
    assert tb.score(prompt, rates=flat)[0] + 1 == tb.score(prompt, rates=low)[0]
    assert tb.low_pass_family(prompt, {"economy": (0, 3)}) == ""     # too few scored runs to trust
    assert tb.low_pass_family(prompt, low) == "economy"


def test_ladder_budget_grows_with_every_failed_round():
    budgets = [tb.rung_budget(n) for n in (1, 2, 3, 4, 9)]
    assert budgets == sorted(budgets) and budgets[0] > 0 and len(set(budgets)) == 4 and budgets[-1] == budgets[-2]
    assert tb.rung_budget(1, "off") == 0 and tb.rung_budget(0) == 0


def test_fields_merge_with_the_cache_fields():
    base = {"cache_prompt": True, "chat_template_kwargs": {"preserve_thinking": True}, "id_slot": 1}
    merged = tb.merge_fields(base, 768)
    assert merged["chat_template_kwargs"] == {"preserve_thinking": True, "enable_thinking": True}
    assert merged["reasoning_budget_tokens"] == 768 and merged["id_slot"] == 1
    assert "enable_thinking" not in base["chat_template_kwargs"]            # the input is not changed
    assert tb.merge_fields(base, 0) == base


def test_rates_from_results(tmp_path):
    suite = tmp_path / "suite.json"
    suite.write_text(json.dumps([{"id": "A", "category": "ui-layout"}, {"id": "B", "category": "ui-text"},
                                 {"id": "C", "category": "remote-security"}]))
    run = tmp_path / "run.json"
    run.write_text(json.dumps({"tasks": {"A": {"status": "pass"}, "B": {"status": "fail"}, "C": {"status": "error"}}}))
    assert tb.rates_from_results([run], [suite]) == {"ui": (1, 2)}


def test_settings_validates_the_setting():
    from star.desktop_core import Settings
    assert Settings().thinking_budget in tb.MODES
    for mode in tb.MODES:
        Settings(thinking_budget=mode).validate()
    with pytest.raises(ValueError):
        Settings(thinking_budget="sometimes").validate()


class _Completion:
    def __init__(self, calls):
        self.calls = calls

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content="```luau\nprint(1)\n```")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _client(calls):
    return SimpleNamespace(chat=SimpleNamespace(completions=_Completion(calls)))


def _failure():
    return Rung("compile", False, "line 1: bad", signature="compile:x", line=1)


def test_fix_calls_think_longer_each_round_on_a_slot_client():
    calls = []
    helper = providers._PinnedClient(_client(calls), lambda model: {"cache_prompt": True, "id_slot": 1})
    _, fix = model_tools(helper, "star-fast", "task", max_tokens=1600, thinking="auto")
    for _ in range(3):
        asyncio.run(fix("local x = 1\n" * 40, _failure(), ""))
    sent = [c["extra_body"]["reasoning_budget_tokens"] for c in calls]
    assert sent == [tb.rung_budget(1), tb.rung_budget(2), tb.rung_budget(3)]
    assert all(c["extra_body"]["chat_template_kwargs"]["enable_thinking"] and c["extra_body"]["id_slot"] == 1
               for c in calls)
    assert all("thinking_tokens" not in c for c in calls)
    assert calls[0]["max_tokens"] > sent[0]                       # the fix keeps its own room for the answer


def test_fix_calls_do_not_think_when_off_or_on_a_plain_client():
    calls = []
    helper = providers._PinnedClient(_client(calls), lambda model: {"cache_prompt": True})
    _, fix = model_tools(helper, "star-fast", "task", thinking="off")
    asyncio.run(fix("local x = 1\n" * 40, _failure(), ""))
    assert calls[0]["extra_body"] == {"cache_prompt": True}
    plain = []
    _, fix = model_tools(_client(plain), "gpt", "task", thinking="auto")
    asyncio.run(fix("local x = 1\n" * 40, _failure(), ""))
    assert "extra_body" not in plain[0] and "thinking_tokens" not in plain[0]
