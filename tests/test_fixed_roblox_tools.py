"""With "Start thinking while I type" on, a Roblox chat keeps one tool list from its first Roblox message.

The Qwen template writes the tool list first, so a tool added in the middle of a chat means the server reads the
whole prompt again (the owner's draft was read for nothing). Off, nothing changes: tools still follow each message.
"""
import json

from star.turn_memory import ROBLOX_FIXED_TOOLS, TurnMemory
from tests.test_model_routing import Source, clean_process_memory, desk, fleet_settings, reply  # noqa: F401

FIRST = "Write a Luau script for my Roblox game that spins a part"
# Words that single messages of a code edit pick tools up from (checked against the 20 edit tasks).
LATER = ["In my Roblox game: audit this module and fix the bug", "Roblox: how many days until the update? Calculate 3 * 4",
         "Roblox: look for the devforum discussion about this"]
EXTRA = {"star_calculate", "star_clock", "star_roblox_craft_audit", "star_roblox_craft_recipe",
         "star_roblox_forum_search", "star_roblox_forum_topic", "star_roblox_forum_latest"}


def names(request):
    return [item["function"]["name"] for item in request.get("tools") or []]


def test_on_every_message_of_a_roblox_chat_sends_the_same_tool_bytes(desk):  # noqa: F811
    settings = fleet_settings(prefill_while_typing=True)
    first = desk.turn(FIRST, "Done.", mode="agent", settings=settings)
    assert EXTRA <= set(names(first))
    for text in LATER:
        later = desk.turn(text, "Ok.", mode="agent", settings=settings)
        assert json.dumps(later["tools"]) == json.dumps(first["tools"])
        assert later["messages"][0] == first["messages"][0]


def test_a_tool_that_follows_a_message_runs_when_it_was_pinned(desk):  # noqa: F811
    # The authorisation of the calculator and the clock follows the same fixed list, not only the message's words.
    settings = fleet_settings(prefill_while_typing=True)
    desk.turn(FIRST, "Done.", mode="agent", settings=settings)
    call = reply(None, [type("C", (), {"id": "c1", "function": type("F", (), {
        "name": "star_calculate", "arguments": json.dumps({"expression": "3 * 4"})})()})()])
    desk.turn("Roblox: and the total for the update?", [call, reply("12")], mode="agent", settings=settings)
    assert not any(e.get("event") == "tool_finished" and e.get("is_error") for e in desk.events)
    assert any(e.get("event") == "tool_finished" and e.get("tool") == "star_calculate" for e in desk.events)


def test_off_the_tools_follow_each_message_as_before(desk):  # noqa: F811
    settings = fleet_settings()
    first = desk.turn(FIRST, "Done.", mode="agent", settings=settings)
    assert not EXTRA & set(names(first))
    later = desk.turn(LATER[0], "Ok.", mode="agent", settings=settings)
    assert {"star_roblox_craft_audit", "star_roblox_craft_recipe"} <= set(names(later))
    assert json.dumps(later["tools"]) != json.dumps(first["tools"])


def test_a_chat_that_is_not_about_roblox_gets_no_pinned_tools(desk):  # noqa: F811
    settings = fleet_settings(prefill_while_typing=True)
    sent = desk.turn("Use a skill and delegate research to a team of agents", "Done.", mode="agent", settings=settings)
    assert not EXTRA & set(names(sent))


def test_a_pinned_text_selects_through_each_source_so_a_switched_off_source_drops_out():
    source = Source({"roblox": ["tool_a"], "audit": ["tool_b"]})
    memory = TurnMemory(sticky=True)
    memory.pin("roblox audit")
    memory.pin("roblox audit")                      # pinning twice changes nothing
    assert memory.pinned == ["roblox audit"]
    assert [t["name"] for t in memory.choose(source.definitions, "thanks")] == ["tool_a", "tool_b"]
    source.enabled = False
    assert memory.choose(source.definitions, "thanks") == []
    plain = TurnMemory(sticky=False)
    plain.pin("x")                                  # without stickiness the list follows the message alone
    assert [t["name"] for t in plain.choose(Source({"x": ["t"], "y": ["u"]}).definitions, "y")] == ["u"]


def test_the_fixed_text_triggers_the_calculator_and_the_clock():
    from star import clock, calc
    assert calc.numerical_request(ROBLOX_FIXED_TOOLS) and clock.wants_clock(ROBLOX_FIXED_TOOLS)
