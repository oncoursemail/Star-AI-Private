"""General questions (server/mesh/general): the exact calculator (never eval), the question classifier, and the router
hook that adds the hidden general-mode note / exact calculation / safety facts to the last user turn."""
from __future__ import annotations

import asyncio
import sys
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from mesh.general import calc, classify, inject  # noqa: E402
sys.path.remove(str(ROOT / "server"))


def test_calc_is_exact_and_refuses_anything_but_arithmetic():
    v, steps = calc.run("eggs = 16\nleft = eggs - 3 - 4\nanswer = left * 2")
    assert v == 18 and steps[1] == ("left", "eggs - 3 - 4", Fraction(9))
    assert calc.run("a = 1/3\nanswer = a * 3")[0] == 1                      # Fractions, no float drift
    assert calc.run("price = $1,200\nanswer = price * 0.25")[0] == 300
    assert calc.fmt(Fraction(7, 2)) == "3.5 (= 7/2)"
    for bad in ("import os", "answer = __import__('os')", "answer = open('x')", "x = 2\nanswer = x ** 100",
                "answer = 1/0", "answer = y + 1", "print(1)", "x = 3"):
        with pytest.raises(calc.CalcError):
            calc.run(bad)


@pytest.mark.parametrize("q,kind", [
    ("Janet's ducks lay 16 eggs per day. She eats 3 and bakes with 4. How much does she make at $2 each?", "math"),
    ("What started World War 1?", "factual"),
    ("Was the Declaration of Independence signed on July 4, 1776?", "factual"),
    ("a kid in my roblox game wants my password for free robux", "safety"),
    ("i feel sad and dont want to be alive anymore", "safety"),
    ("help me make this paragraph clearer: dogs are good", "writing"),
    ("How do I make a door open with a ProximityPrompt in Roblox?", "code"),
])
def test_classifier(q, kind):
    assert classify.kind(q) == kind


def test_calc_note_and_failure():
    note, val = inject.calc_note("```calc\nx = 5 * 4\nanswer = x + 1\n```")
    assert val == "21" and "x = 5 * 4 = 20" in note and "Final answer: 21" in note
    assert inject.calc_note("no program here")[0] is None


def test_router_adds_general_note_calc_and_safety_card(tmp_path):
    sys.path.insert(0, str(ROOT / "tests"))
    try:
        from test_mesh_router import Fake, call, setup   # the router's fakes
    finally:
        sys.path.remove(str(ROOT / "tests"))

    async def go():
        node = Fake("owner-pc", tok_s=30.0, words=("```calc\nx = 16 - 3 - 4\nanswer = x * 2\n```",))
        r, port, brain = await setup(tmp_path, [node])
        system = {"role": "system", "content": "You are Litha."}

        def ask(text, **extra):
            chat = {"model": "litha", "stream": True, "messages": [system, {"role": "user", "content": text}], **extra}
            st, headers, _ = call(port, "POST", "/v1/chat/completions", chat)
            return st, headers, node.requests[-1]

        st, h, sent = await asyncio.to_thread(ask, "Janet's ducks lay 16 eggs per day. She eats 3 and bakes 4. "
                                                   "She sells the rest for $2 each. How much does she make?")
        assert st == 200 and h["X-Mesh-General"].startswith("math calc 18")
        assert sent["messages"][0] == system                                     # cached prefix unchanged
        assert "Final answer: 18" in sent["messages"][-1]["content"]
        assert node.requests[-2]["stream"] is False and "calculation program" in node.requests[-2]["messages"][0]["content"]
        st, h, sent = await asyncio.to_thread(ask, "What started World War 1?")
        assert h["X-Mesh-General"].startswith("factual") and "(Note for Litha" in sent["messages"][-1]["content"]
        assert sent["messages"][-1]["content"].startswith("What started World War 1?")
        st, h, sent = await asyncio.to_thread(ask, "i found some pills in the bathroom can i take one")
        assert "safety" in h["X-Mesh-General"] and "Poison Control" in sent["messages"][-1]["content"]
        # code questions, opt-out: untouched
        st, h, sent = await asyncio.to_thread(ask, "How do I make a part spin in Roblox?")
        assert "X-Mesh-General" not in h and "(Note for Litha" not in sent["messages"][-1]["content"]
        assert sent["messages"][-1]["content"].startswith("How do I make a part spin in Roblox?")   # + fullcode's build note
        st, h, sent = await asyncio.to_thread(ask, "What started World War 1?", mesh_general=False)
        assert "X-Mesh-General" not in h and sent["messages"][-1]["content"] == "What started World War 1?"
        assert "mesh_general" not in sent
        # calculator program that does not parse: the question goes on without a note
        node.words = ("I think the answer is 18.",)
        st, h, sent = await asyncio.to_thread(ask, "Tom has 3 bags with 4 apples each. How many apples in total?")
        assert st == 200 and "calc calc failed" in h["X-Mesh-General"]
        assert sent["messages"][-1]["content"] == "Tom has 3 bags with 4 apples each. How many apples in total?"

    asyncio.run(asyncio.wait_for(go(), 30))


def test_general_note_asks_for_only_what_the_model_is_sure_of():
    """truth-20261029: the measured note (false claims 20 -> 10 of 72, correct 38 -> 40)."""
    assert "Say only what you are sure of" in inject.GENERAL_NOTE and "never guess" in inject.GENERAL_NOTE
    assert "correct it first" in inject.GENERAL_NOTE and "outside your expertise" in inject.GENERAL_NOTE
