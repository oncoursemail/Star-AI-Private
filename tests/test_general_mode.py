"""STAR's own general-question helper (star/general_mode.py): exact calculator, classifier, hidden notes, and parity
with the router's copy (server/mesh/general) so the two never drift apart."""
from __future__ import annotations

import sys
from fractions import Fraction
from pathlib import Path

import pytest

from star import general_mode as G

ROOT = Path(__file__).resolve().parents[1]


def _mesh():
    sys.path.insert(0, str(ROOT / "server"))
    try:
        from mesh.general import calc, classify
    finally:
        sys.path.remove(str(ROOT / "server"))
    return calc, classify


def test_calc_is_exact_and_refuses_anything_but_arithmetic():
    v, steps = G.calc_run("eggs = 16\nleft = eggs - 3 - 4\nanswer = left * 2")
    assert v == 18 and steps[1] == ("left", "eggs - 3 - 4", Fraction(9))
    assert G.calc_run("a = 1/3\nanswer = a * 3")[0] == 1
    assert G.calc_run("price = $1,200\nanswer = price * 0.25")[0] == 300
    for bad in ("import os", "answer = __import__('os')", "answer = open('x')", "x = 2\nanswer = x ** 100",
                "answer = 1/0", "answer = y + 1", "print(1)", "x = 3"):
        with pytest.raises(G.CalcError):
            G.calc_run(bad)


def test_calc_matches_the_router_copy():
    calc, _ = _mesh()
    for src in ("a = 7\nb = a * 3 / 4\nanswer = round(b, 1) + min(2, 5)", "x = 10 // 3\nanswer = x % 2 - -1"):
        assert G.calc_run(src)[0] == calc.run(src)[0]
    assert G.calc_fmt(Fraction(7, 2)) == calc.fmt(Fraction(7, 2)) == "3.5 (= 7/2)"


@pytest.mark.parametrize("q", [
    "Janet's ducks lay 16 eggs per day. She eats 3 and bakes with 4. How much does she make at $2 each?",
    "What started World War 1?",
    "a kid in my game wants my password for free robux",
    "i feel sad and dont want to be alive anymore",
    "help me make this paragraph clearer: dogs are good",
    "How do I make a door open with a ProximityPrompt in Roblox?",
    "hi star",
])
def test_classifier_agrees_with_the_router(q):
    _, classify = _mesh()
    assert G.kind(q) == classify.kind(q)


def test_studio_words_count_as_code_for_star():
    assert G.kind("why does my Studio plugin show nothing when I open it?") == "code"


def test_sections_by_kind():
    assert G.sections("hi star") == []
    assert G.sections("How do I make a door open with a ProximityPrompt in Roblox?") == []
    assert G.sections("Janet has 3 apples and buys 4 more. How many apples does she have in total?") == []
    (head, text), = G.sections("Who was the third person to walk on the moon?")
    assert head == G.HEADING and "never guess" in text and "911" not in text
    (_, text), = G.sections("i found some pills at the park, can i take one?")
    assert "Poison Control" in text and "988" in text


def test_calc_section_from_a_program_reply():
    head, text = G.calc_section("```calc\nper_day = 16 - 3 - 4\nanswer = per_day * 2\n```")
    assert head == G.HEADING and "Final answer: 18" in text
    assert G.calc_section("I think it is 18") is None
    assert G.calc_messages("q")[0]["content"] == G.CALC_SYS


@pytest.mark.parametrize("q", ["what time is it", "hey star how is night school going?", "what are you doing right now?",
                               "do you remember what we talked about yesterday?", "tell me a joke",
                               "i had a rough day at work", "and what about the second one?"])
def test_conversation_with_star_is_not_a_general_question(q):
    assert G.kind(q) == "chat" and G.sections(q) == []


def test_safety_wins_over_the_conversation_rules():
    assert G.kind("i think i swallowed something poisonous") == "safety"


def test_gpu_lane_endpoint(monkeypatch):
    from types import SimpleNamespace
    s = SimpleNamespace(provider="star_server", allow_cgnat=False, general_gpu=True)
    assert G.gpu_endpoint(s) == ""                                    # conftest: STAR_MESH_URL=off
    monkeypatch.setenv("STAR_MESH_URL", "http://10.1.2.3:8100")  # star:allow
    assert G.gpu_endpoint(s) == "http://10.1.2.3:8100/v1"  # star:allow
    assert G.gpu_endpoint(SimpleNamespace(**{**s.__dict__, "general_gpu": False})) == ""
    monkeypatch.setenv("STAR_MESH_URL", "http://example.com:8100")       # never a public address
    assert G.gpu_endpoint(s) == ""


def _discord(monkeypatch, gpu_answer, question):
    """DiscordBrain.reply with the brain path and the GPU lane both faked; returns (answer, brain calls, lane calls)."""
    import asyncio
    from types import SimpleNamespace
    from star.discord_bot import brain as B
    monkeypatch.setattr(B, "plan_route", lambda settings, prompt, research=False: B.ChatRoute("star-voice", True, "fast"))
    monkeypatch.setattr(G, "gpu_endpoint", lambda settings: "http://10.1.2.3:8100/v1")  # star:allow
    lane = []

    async def fake_gpu(settings, endpoint, messages, **kw):
        lane.append(messages)
        return await gpu_answer(kw.get("on_delta"))
    monkeypatch.setattr(G, "gpu_answer", fake_gpu)

    async def fake_calc(settings, endpoint, q):
        return (G.HEADING, "Final answer: 18")
    monkeypatch.setattr(G, "gpu_calc", fake_calc)
    brain = []

    async def fake_complete(self, settings, route, messages, on_delta, tools=None, tool_handler=None):
        brain.append(messages)
        return "from the brain"
    monkeypatch.setattr(B.DiscordBrain, "_complete", fake_complete)
    monkeypatch.setattr(B.DiscordBrain, "_learn_roles", lambda self, s: asyncio.sleep(0))
    settings = SimpleNamespace(provider="star_server", validate=lambda: None, general_help=True, general_gpu=True)
    from star import server_roles
    monkeypatch.setattr(server_roles, "effective", lambda s: s)
    shown = []

    async def on_delta(t):
        shown.append(t)
    answer = asyncio.run(B.DiscordBrain(settings=settings).reply(question, [], live="Now: Thursday", on_delta=on_delta))
    return answer, brain, lane, shown


def test_discord_general_question_goes_to_the_gpu_lane_with_the_note(monkeypatch):
    async def ok(on_delta):
        await on_delta("Pete Conrad, Apollo 12.")
        return "Pete Conrad, Apollo 12."
    answer, brain, lane, shown = _discord(monkeypatch, ok, "Who was the third person to walk on the Moon?")
    assert answer == "Pete Conrad, Apollo 12." and not brain and shown == ["Pete Conrad, Apollo 12."]
    user = lane[0][-1]["content"]
    assert user.startswith("Who was the third person") and G.NOTE in user and user.endswith("Now: Thursday")


def test_discord_gpu_lane_failure_before_a_word_falls_back_to_the_brain(monkeypatch):
    async def down(on_delta):
        raise TimeoutError
    answer, brain, lane, shown = _discord(monkeypatch, down, "Who was the third person to walk on the Moon?")
    assert answer == "from the brain" and len(brain) == 1 and G.NOTE in brain[0][-1]["content"]


def test_discord_maths_gets_the_exact_calculation_and_chat_stays_on_the_brain(monkeypatch):
    async def ok(on_delta):
        return "18"
    _, brain, lane, _ = _discord(monkeypatch, ok, "Janet has 16 eggs, eats 3 and bakes 4. How much at $2 each?")
    assert "Final answer: 18" in lane[0][-1]["content"] and not brain
    _, brain, lane, _ = _discord(monkeypatch, ok, "hey star how is night school going?")
    assert not lane and brain and G.HEADING not in brain[0][-1]["content"]
