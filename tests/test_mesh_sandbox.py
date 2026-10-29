"""Executable check (server/mesh/sandbox): block placement, property checks, the fix-pass guard and, when a Luau runtime
is available (STAR_SANDBOX_LUAU, `luau` or `lune` on PATH), real runs of the fake Roblox on good and broken answers.
Also the plan-then-code checker (server/mesh/plan)."""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from mesh.plan import planner  # noqa: E402
from mesh.sandbox import fix, harness, props  # noqa: E402
sys.path.remove(str(ROOT / "server"))

EXE = os.environ.get("STAR_SANDBOX_LUAU") or shutil.which("luau") or shutil.which("lune") or ""
needs_luau = pytest.mark.skipif(not EXE, reason="no Luau runtime (set STAR_SANDBOX_LUAU)")

# a tiny API index: enough classes for the scenarios below
INDEX = {"classes": {
    "Instance": {"super": "<<<ROOT>>>", "members": {"Name": {"k": "p"}, "Parent": {"k": "p"}, "Changed": {"k": "e"},
                                                     "Destroying": {"k": "e"}, "ChildAdded": {"k": "e"}}, "tags": ["NotCreatable"]},
    "PVInstance": {"super": "Instance", "members": {}, "tags": ["NotCreatable"]},
    "BasePart": {"super": "PVInstance", "members": {"Anchored": {"k": "p"}, "CanCollide": {"k": "p"},
                 "Transparency": {"k": "p"}, "Position": {"k": "p"}, "CFrame": {"k": "p"}, "Size": {"k": "p"},
                 "Color": {"k": "p"}, "Touched": {"k": "e"}}, "tags": ["NotCreatable"]},
    "Part": {"super": "BasePart", "members": {}},
    "Model": {"super": "PVInstance", "members": {"PrimaryPart": {"k": "p"}}},
    "Folder": {"super": "Instance", "members": {}},
    "ValueBase": {"super": "Instance", "members": {}, "tags": ["NotCreatable"]},
    "IntValue": {"super": "ValueBase", "members": {"Value": {"k": "p"}}},
    "Humanoid": {"super": "Instance", "members": {"Health": {"k": "p"}, "MaxHealth": {"k": "p"}, "Died": {"k": "e"},
                                                  "TakeDamage": {"k": "f"}, "WalkSpeed": {"k": "p"}}},
    "Animator": {"super": "Instance", "members": {}},
    "Player": {"super": "Instance", "members": {"UserId": {"k": "p"}, "Character": {"k": "p"},
                                                "CharacterAdded": {"k": "e"}, "Kick": {"k": "f"}}, "tags": ["NotCreatable"]},
    "Backpack": {"super": "Instance", "members": {}}, "PlayerGui": {"super": "Instance", "members": {}},
    "PlayerScripts": {"super": "Instance", "members": {}},
    "Players": {"super": "Instance", "members": {"PlayerAdded": {"k": "e"}, "PlayerRemoving": {"k": "e"},
                "LocalPlayer": {"k": "p"}, "GetPlayerFromCharacter": {"k": "f"}, "RespawnTime": {"k": "p"},
                "CharacterAutoLoads": {"k": "p"}}, "tags": ["NotCreatable", "Service"]},
    "DataModel": {"super": "Instance", "members": {"Workspace": {"k": "p"}}, "tags": ["NotCreatable"]},
    "Workspace": {"super": "Model", "members": {"Gravity": {"k": "p"}, "CurrentCamera": {"k": "p"}}, "tags": ["NotCreatable", "Service"]},
    "Terrain": {"super": "BasePart", "members": {}, "tags": ["NotCreatable"]},
    "Camera": {"super": "Instance", "members": {"CFrame": {"k": "p"}}},
    "ProximityPrompt": {"super": "Instance", "members": {"Triggered": {"k": "e"}, "ActionText": {"k": "p"}}},
    "RemoteEvent": {"super": "Instance", "members": {"OnServerEvent": {"k": "e"}, "OnClientEvent": {"k": "e"},
                    "FireServer": {"k": "f"}, "FireClient": {"k": "f"}}},
    "Script": {"super": "Instance", "members": {}}, "LocalScript": {"super": "Instance", "members": {}},
    "Tool": {"super": "Instance", "members": {"Activated": {"k": "e"}}},
    **{s: {"super": "Instance", "members": {}, "tags": ["NotCreatable", "Service"]} for s in (
        "ReplicatedStorage", "ServerStorage", "ServerScriptService", "StarterGui", "StarterPack", "StarterPlayer",
        "Lighting", "SoundService", "Teams", "ReplicatedFirst", "Chat", "TextChatService", "TweenService",
        "DataStoreService", "RunService", "UserInputService", "ContextActionService", "CollectionService", "Debris",
        "MarketplaceService", "HttpService", "BadgeService", "TeleportService", "PhysicsService",
        "PathfindingService", "TextService", "MessagingService", "MemoryStoreService", "ProximityPromptService",
        "GroupService", "PolicyService", "SocialService", "GuiService", "VRService", "HapticService",
        "LocalizationService", "AnalyticsService")},
    "StarterPlayerScripts": {"super": "Instance", "members": {}}, "StarterCharacterScripts": {"super": "Instance", "members": {}},
    "DataStore": {"super": "Instance", "members": {"GetAsync": {"k": "f"}, "SetAsync": {"k": "f"}}, "tags": ["NotCreatable"]},
}}
MEM = harness.members_luau(INDEX)


def lua(label: str, code: str) -> str:
    return f"{label}\n```lua\n{code.strip()}\n```\n"


# ---- placement / helpers (no runtime) ----------------------------------------------------------------------------------
def test_plan_blocks_places_by_label_and_adds_leaderstats_helper():
    text = (lua("**Script (inside the Coin part):**", "local coin = script.Parent\ncoin.Touched:Connect(function(hit)\n"
                "local p = game.Players:GetPlayerFromCharacter(hit.Parent)\nif p then p.leaderstats.Gems.Value += 1 end\nend)") +
            lua("**LocalScript (inside a TextButton):**", "script.Parent.MouseButton1Click:Connect(function() end)"))
    blocks = harness.plan_blocks(text)
    assert blocks[0]["label"] == "helper" and '"Gems"' in blocks[0]["src"]
    assert blocks[1]["kind"] == "server" and blocks[1]["place"] == "world" and blocks[1]["part"] == "Coin"
    assert blocks[2]["kind"] == "local" and blocks[2]["gui"] == "button"


def test_comparison_blocks_are_not_run():
    text = lua("Two scripts:", "-- Script in ServerScriptService\nprint(1)\n-- LocalScript in StarterPlayerScripts\nprint(2)")
    assert harness.plan_blocks(text) == []


def test_members_luau_marks_not_creatable_and_skips_odd_names():
    m = harness.members_luau({"classes": {"Part": {"super": "BasePart", "members": {"Anchored": {"k": "p"},
                                          "Bad Name": {"k": "p"}}}, "Players": {"super": "Instance", "members": {},
                                          "tags": ["Service"]}}})
    assert '["Part"]="BasePart|Anchored:p"' in m and '["Players"]="Instance|!"' in m


def test_props_seconds_and_checks():
    assert props.seconds("closes again after 3 seconds") == 3.0 and props.seconds("after a few seconds") == 3.0
    obs = {"touch_parts": 1, "total_join": 0, "total_touch": 5, "stats_join": {"Coins": 0}, "total_touch_1s": 5}
    found = props.check("How do I make a coin pad that gives 1 coin when touched?", "", {"obs": obs})
    assert [f["phase"] for f in found] == ["debounce"]
    ok = dict(obs, total_touch=1, total_touch_1s=1)
    assert props.check("How do I make a coin pad that gives 1 coin when touched?", "", {"obs": ok}) == []
    # a team-only door is never failed for staying shut for a player without the team
    door = {"touch_parts": 1, "parts_changed_touch": 0, "parts_changed_touch_1s": 0}
    assert props.check("Door that only the Red team can open when they touch it", "", {"obs": door}) == []
    assert [f["phase"] for f in props.check("Door that opens when touched", "", {"obs": door})] == ["opens"]
    evil = {"evil": 1, "total_hb": 0, "total_evil": 1e9}
    assert [f["phase"] for f in props.check("shop", "", {"obs": evil})] == ["trust"]


def test_failed_load_check():
    raw = {"writes": [{"how": "set", "failed_load": True}]}
    assert props.check_ds_fail(raw)[0]["phase"] == "failed-load"
    assert props.check_ds_fail({"writes": [{"how": "set", "failed_load": False}]}) == []


def test_fix_guard_keeps_original_unless_test_problems_drop():
    old = lua("**Script in ServerScriptService:**", "print(1)")
    new = lua("**Script in ServerScriptService:**", "print(2)")
    f1 = {"kind": "runtime", "phase": "join", "message": "attempt to index nil with 'Coins'"}
    f2 = {"kind": "runtime", "phase": "join", "message": "attempt to call a nil value"}
    keep, why = fix.judge(old, new, {"findings": [f1]}, {"ran": True, "findings": []}, "q", "stop")
    assert keep, why
    assert not fix.judge(old, new, {"findings": [f1]}, {"ran": True, "findings": [f2]}, "q", "stop")[0]
    assert not fix.judge(old, new, {"findings": [f1]}, {"ran": True, "findings": [f1]}, "q", "stop")[0]
    assert not fix.judge(old, new, {"findings": [f1]}, {"ran": False, "findings": []}, "q", "stop")[0]
    assert not fix.judge(old, "no code now", {"findings": [f1]}, {"ran": True, "findings": []}, "q", "stop")[0]


def test_fix_messages_quote_the_failing_line():
    text = lua("**Script in ServerScriptService:**", "local a = 1\nlocal b = nil\nprint(b.x)")
    lines = fix.problem_lines(text, [{"kind": "runtime", "block": 1, "line": 3, "phase": "start",
                                      "message": "attempt to index nil with 'x'"}])
    assert "print(b.x)" in lines[0] and "when the script started" in lines[0]


def test_fix_run_without_findings_does_not_call_the_model():
    async def model(body):
        raise AssertionError("must not be called")
    text, info = asyncio.run(fix.run("q", "a", model, lambda t, q: {"ran": True, "findings": []}))
    assert text == "a" and info["result"] == "no test problems"


# ---- real runs ---------------------------------------------------------------------------------------------------------
def run(text: str, question: str = "How do I do this in Roblox?") -> dict:
    return harness.run(text, question, harness.Runner(EXE, 20), members=MEM)


@needs_luau
def test_good_leaderstats_and_touch_reward_run_clean():
    text = (lua("**Script in ServerScriptService:**", """
local Players = game:GetService("Players")
Players.PlayerAdded:Connect(function(player)
	local ls = Instance.new("Folder")
	ls.Name = "leaderstats"
	local coins = Instance.new("IntValue")
	coins.Name = "Coins"
	coins.Parent = ls
	ls.Parent = player
end)""") + lua("**Script inside the Pad part:**", """
local pad = script.Parent
local Players = game:GetService("Players")
local cooldown = {}
pad.Touched:Connect(function(hit)
	local player = Players:GetPlayerFromCharacter(hit.Parent)
	if not player or cooldown[player] then return end
	cooldown[player] = true
	player.leaderstats.Coins.Value += 1
	task.wait(2)
	cooldown[player] = nil
end)"""))
    rep = run(text, "How do I make a pad that gives 1 coin when touched?")
    assert rep["ran"], rep
    assert rep["findings"] == [], rep["findings"]
    assert rep["obs"]["stats_join"] == {"Coins": 0} and rep["obs"]["total_touch"] == 1


@needs_luau
def test_missing_debounce_and_nil_index_are_found():
    text = lua("**Script inside the Pad part:**", """
local pad = script.Parent
pad.Touched:Connect(function(hit)
	local player = game.Players:GetPlayerFromCharacter(hit.Parent)
	player.leaderstats.Coins.Value += 1
end)""")
    rep = run(text, "How do I make a pad that gives 1 coin when touched?")
    kinds = {(f["kind"], f.get("phase")) for f in rep["findings"]}
    assert ("property", "debounce") in kinds, rep["findings"]
    bad = lua("**Script in ServerScriptService:**", "local p = game.Players.LocalPlayer\nprint(p.Name)")
    rep2 = run(bad)
    assert any("attempt to index nil" in f["message"] for f in rep2["findings"]), rep2


@needs_luau
def test_studio_objects_appear_and_server_firing_to_server_is_an_error():
    text = lua("**Script inside the Door part (with a ProximityPrompt):**", """
local door = script.Parent
local prompt = door:WaitForChild("ProximityPrompt")
prompt.Triggered:Connect(function(player)
	door.CanCollide = false
	door.Transparency = 0.5
	task.wait(3)
	door.CanCollide = true
	door.Transparency = 0
end)""")
    rep = run(text, "How do I make a door that opens when I press E and closes after 3 seconds?")
    assert rep["findings"] == [], rep["findings"]
    assert rep["obs"]["prompts"] == 1 and rep["obs"]["parts_changed_prompt"] == 1
    wrong = lua("**Script in ServerScriptService:**", 'game.ReplicatedStorage.BuyEvent:FireServer(5)')
    assert any("FireServer can only be called from the client" in f["message"] for f in run(wrong)["findings"])


@needs_luau
def test_loop_without_yield_is_a_hang():
    text = lua("**Script in ServerScriptService:**", "local n = 0\nwhile true do n = n + 1 end")
    rep = harness.run(text, "", harness.Runner(EXE, 3), members=MEM)
    assert rep["findings"] and rep["findings"][0]["kind"] == "hang"


# ---- plan-then-code ----------------------------------------------------------------------------------------------------
def test_plan_checker_finds_placement_trust_and_saving_problems():
    plan = {"files": [{"name": "Shop", "type": "LocalScript", "location": "ServerScriptService"},
                      {"name": "Server", "type": "Script", "location": "ReplicatedStorage"}],
            "remotes": [{"name": "Buy", "from": "client", "args": ["itemName", "price"], "server_checks": []}],
            "data": {"store": "Coins", "save_when": ["PlayerRemoving"]}}
    probs = " | ".join(planner.check_plan(plan, "shop that saves coins"))
    assert "never runs in ServerScriptService" in probs and "never runs; put it in ServerScriptService" in probs
    assert "server checks nothing" in probs and "BindToClose" in probs
    good = {"files": [{"name": "Shop", "type": "Script", "location": "ServerScriptService"}],
            "remotes": [{"name": "Buy", "from": "client", "args": ["itemName"], "server_checks": ["price from table"]}],
            "data": {"store": "Coins", "save_when": ["PlayerRemoving", "BindToClose"]}}
    assert planner.check_plan(good, "shop that saves coins") == []


def test_plan_build_and_assemble_with_a_fake_model():
    replies = iter([
        '{"summary": "A coin shop.", "setup": ["RemoteEvent BuyItem in ReplicatedStorage"], "files": ['
        '{"name": "ShopServer", "type": "Script", "location": "ServerScriptService", "does": "sells"}], '
        '"remotes": [{"name": "BuyItem", "from": "client", "args": ["item"], "server_checks": ["price"]}], '
        '"data": {}, "authority": ["The server owns prices."]}',
        "```lua\nprint('server')\n```"])

    async def model(body):
        return {"text": next(replies), "finish": "stop"}
    answer, info = asyncio.run(planner.build("Make a shop", model))
    assert info["calls"] == 2 and info["plan_problems"] == []
    assert "**Script `ShopServer` (in ServerScriptService):**" in answer and "print('server')" in answer
    assert planner.wanted("Make a shop for my Roblox game: a GUI with 3 items, buying is checked on the server, coins "
                          "are saved with DataStore, and items are given again on respawn.")
    assert not planner.wanted("How do I make a part spin?")
