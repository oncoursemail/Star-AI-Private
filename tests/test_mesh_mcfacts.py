"""Minecraft plugin/mod facts note (server/mesh/mcfacts): which questions get which platform's facts."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from mesh import mcfacts  # noqa: E402


def test_platform_routing():
    f = mcfacts.facts_for
    assert f("Make me a Paper 1.21.11 plugin with a /heal command")[0] == "paper"
    assert f("basic setup for a Minecraft Spigot/Paper plugin")[0] == "paper"
    assert f("I'm on plain Spigot (not Paper), make a plugin with /ping")[0] == "spigot"
    assert f("Velocity 3.5 proxy plugin with /hub")[0] == "velocity"
    assert f("Fabric mod for Minecraft 1.21.11: /hello")[0] == "fabric"
    assert f("NeoForge mod: add an item")[0] == "neoforge"
    for q in ("How do I make a Roblox obby?", "my fabric shirt is torn", "make a /give command datapack",
              "What is the difference between a Minecraft mod, a plugin and a datapack?", ""):
        assert f(q) == (None, "")


def test_apply_appends_to_last_user_turn_only():
    req = {"messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "Paper plugin with /fly"}]}
    assert mcfacts.apply(req) == {"X-Mesh-MCJava": "paper"}
    assert req["messages"][0]["content"] == "sys"
    assert req["messages"][1]["content"].startswith("Paper plugin with /fly\n\n(Facts for Litha")
    assert "LifecycleEvents.COMMANDS" in req["messages"][1]["content"]
    other = {"messages": [{"role": "user", "content": "Roblox door script"}]}
    assert mcfacts.apply(other) == {} and other["messages"][0]["content"] == "Roblox door script"


def test_router_has_the_hook_on():
    from mesh import router
    assert router.DEFAULTS["mc_java_facts"] is True and router.mcfacts is mcfacts
