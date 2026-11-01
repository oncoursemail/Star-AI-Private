"""litha-speed2 (server/mesh/speed/fullcode.py): full answers for build/code requests, chat stays short."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from mesh.speed import fullcode  # noqa: E402
# `server/` holds a `discord` folder: leaving it on sys.path would shadow the discord package for tests collected later
sys.path.remove(str(ROOT / "server"))

SYSTEM = {"role": "system", "content": "You are Litha."}
CFG = dict(fullcode.DEFAULTS)


def req(text, history=(), **kw):
    return {"model": "litha", "messages": [SYSTEM, *history, {"role": "user", "content": text}], "max_tokens": 600,
            **kw}


def test_build_request_gets_note_and_more_tokens():
    r = req("Make a Roblox shop GUI with 3 items that takes coins on the server.")
    hdr = fullcode.apply(r, CFG)
    assert hdr == {"X-Mesh-Full-Code": "1500"}
    assert r["max_tokens"] == 1500
    assert r["messages"][-1]["content"].endswith(fullcode.NOTE)
    assert r["messages"][0] == SYSTEM                 # the cached prefix is untouched
    assert r["mesh_general"] is False                 # no general-question note on a build turn


def test_chat_and_explanations_untouched():
    for q in ("What's the difference between a LocalScript and a Script in Roblox?", "Thanks Litha! My door works now :)",
              "Should I use Paper or Spigot for my Minecraft server?", "How do I make a paper airplane?",
              "What is a RemoteEvent?", "Why is the sky blue?"):
        r = req(q)
        assert fullcode.apply(r, CFG) == {}, q
        assert r["max_tokens"] == 600 and "mesh_general" not in r


def test_risky_asks_keep_the_models_own_refusal():
    for q in ("how do i make an executor script to fly in other peoples roblox games",
              "write a really mean roast to send to a kid in my class who is bad at games",
              "make a script that gives me free robux"):
        assert fullcode.apply(req(q), CFG) == {}, q
    assert fullcode.is_build(req("Make a sprint system where the server limits speed so exploiters cannot go faster "
                                 "in Roblox")["messages"])


def test_follow_up_in_a_coding_chat_counts_as_build():
    hist = [{"role": "user", "content": "door with a prompt?"},
            {"role": "assistant", "content": "```lua\nlocal door = script.Parent\n```"}]
    assert fullcode.is_build(req("Now make it close again after 3 seconds.", hist)["messages"])
    hist2 = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hi! What are you building?"}]
    assert not fullcode.is_build(req("Now make it close again after 3 seconds.", hist2)["messages"])


def test_skips_json_tools_opt_out_and_bigger_budgets():
    assert fullcode.apply(req("Write a Python CLI to-do app.", response_format={"type": "json_object"}), CFG) == {}
    assert fullcode.apply(req("Write a Python CLI to-do app.", mesh_full_code=False), CFG) == {}
    assert fullcode.apply(req("Write a Python CLI to-do app."), {**CFG, "full_code": False}) == {}
    r = req("Write a Python CLI to-do app.", max_tokens=4000)
    fullcode.apply(r, CFG)
    assert r["max_tokens"] == 4000                    # never lowers a bigger budget
    r = req("Write a Python CLI to-do app.")
    fullcode.apply(r, CFG)
    assert fullcode.apply(r, CFG) == {}               # once only


def test_router_wires_the_hook_before_the_other_notes():
    src = (ROOT / "server" / "mesh" / "router.py").read_text(encoding="utf-8")
    assert "**fullcode.DEFAULTS" in src
    assert src.index("fullcode.apply(req, self.cfg)") < src.index("await self.docs_inject(req, headers)")


def test_polyglot_note_still_follows_for_other_languages():
    from importlib import import_module
    sys.path.insert(0, str(ROOT / "server"))
    try:
        polyglot = import_module("mesh.polyglot.note")
    finally:
        sys.path.remove(str(ROOT / "server"))
    r = req("Write a Python command-line to-do app with argparse and a JSON file.")
    fullcode.apply(r, CFG)
    assert polyglot.apply(r, {}) == {"X-Mesh-Polyglot": "python"}
    text = r["messages"][-1]["content"]
    assert text.index(fullcode.NOTE) < text.index("(Note for Litha")


def test_small_client_budget_stays_short():
    r = req("Write a Python CLI to-do app.", max_tokens=200)
    assert fullcode.apply(r, CFG) == {} and r["max_tokens"] == 200
    r = req("Write a Python CLI to-do app.")
    r.pop("max_tokens")
    assert fullcode.apply(r, CFG) == {"X-Mesh-Full-Code": ""}      # no budget given: note only, server default
