"""Litha code verifier (server/mesh/verify): Roblox API names from a fake API-dump subset, deprecated members, closest
names, Minecraft command syntax, Unity C# light checks, the fix loop with a fake model, and the HTTP service."""
from __future__ import annotations

import http.client
import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from mesh.verify import core, csharp, minecraft, service  # noqa: E402
from mesh.verify.apidump import ApiIndex, build_index, closest  # noqa: E402
# `server/` holds a `discord` folder: leaving it on sys.path would shadow the discord package for tests collected later
sys.path.remove(str(ROOT / "server"))

KEY = "client-key-for-tests"


def _m(kind, name, value=None, tags=None, params=None, security="None"):
    m = {"MemberType": kind, "Name": name, "Security": security, "Tags": tags or []}
    if value:
        m["ValueType" if kind == "Property" else "ReturnType"] = {"Category": "Class", "Name": value}
    if params is not None:
        m["Parameters"] = [{"Name": "p", "Type": {"Category": "Class", "Name": p}} for p in params]
    return m


DEP = ["Deprecated"]
FAKE_DUMP = {"Version": 1, "Classes": [
    {"Name": "Instance", "Superclass": "<<<ROOT>>>", "Tags": ["NotCreatable"], "Members": [
        _m("Property", "Name"), _m("Property", "Parent", "Instance"), _m("Function", "Destroy"),
        _m("Function", "Clone", "Instance"), _m("Function", "WaitForChild", "Instance"),
        _m("Function", "FindFirstChild", "Instance"), _m("Function", "FindFirstChildOfClass", "Instance"),
        _m("Function", "IsA"), _m("Function", "GetChildren"), _m("Event", "Changed", params=[]),
        _m("Function", "remove", tags=DEP + [{"PreferredDescriptorName": "Destroy"}]),
        _m("Function", "findFirstChild", "Instance", tags=DEP)]},
    {"Name": "ServiceProvider", "Superclass": "Instance", "Tags": ["NotCreatable"], "Members": [
        _m("Function", "GetService", "Instance")]},
    {"Name": "DataModel", "Superclass": "ServiceProvider", "Tags": [], "Members": [
        _m("Property", "Workspace", "Workspace"), _m("Function", "BindToClose")]},
    {"Name": "Workspace", "Superclass": "Instance", "Tags": ["NotCreatable", "Service"], "Members": [
        _m("Property", "Gravity"), _m("Function", "Raycast"),
        _m("Function", "FindPartOnRay", tags=DEP + [{"PreferredDescriptorName": "Raycast"}])]},
    {"Name": "Players", "Superclass": "Instance", "Tags": ["NotCreatable", "Service"], "Members": [
        _m("Property", "LocalPlayer", "Player"), _m("Function", "GetPlayers"),
        _m("Event", "PlayerAdded", params=["Player"]), _m("Event", "PlayerRemoving", params=["Player"])]},
    {"Name": "TweenService", "Superclass": "Instance", "Tags": ["NotCreatable", "Service"], "Members": [
        _m("Function", "Create", "Tween")]},
    {"Name": "Tween", "Superclass": "Instance", "Tags": ["NotCreatable"], "Members": [_m("Function", "Play")]},
    {"Name": "Player", "Superclass": "Instance", "Tags": ["NotCreatable"], "Members": [
        _m("Property", "UserId"), _m("Property", "Character", "Model"),
        _m("Property", "userId", tags=DEP + [{"PreferredDescriptorName": "UserId"}]),
        _m("Event", "CharacterAdded", params=["Model"]), _m("Function", "Kick"),
        _m("Function", "SetSuperSecret", security="RobloxScriptSecurity")]},
    {"Name": "Model", "Superclass": "Instance", "Tags": [], "Members": [_m("Function", "PivotTo")]},
    {"Name": "BasePart", "Superclass": "Instance", "Tags": ["NotCreatable"], "Members": [
        _m("Property", "Anchored"), _m("Property", "CFrame"), _m("Event", "Touched", params=["BasePart"])]},
    {"Name": "Part", "Superclass": "BasePart", "Tags": [], "Members": []},
    {"Name": "Humanoid", "Superclass": "Instance", "Tags": [], "Members": [
        _m("Property", "Health"), _m("Function", "TakeDamage"), _m("Event", "Died", params=[]),
        _m("Function", "LoadAnimation", tags=DEP + [{"PreferredDescriptorName": "LoadAnimation"}])]},
    {"Name": "Animator", "Superclass": "Instance", "Tags": [], "Members": [_m("Function", "LoadAnimation")]},
    {"Name": "ProximityPrompt", "Superclass": "Instance", "Tags": [], "Members": [
        _m("Property", "KeyboardKeyCode"), _m("Event", "Triggered", params=["Player"])]},
    {"Name": "BodyVelocity", "Superclass": "Instance",
     "Tags": DEP + [{"PreferredDescriptorName": "LinearVelocity"}], "Members": []},
    {"Name": "LinearVelocity", "Superclass": "Instance", "Tags": [], "Members": []},
    {"Name": "Folder", "Superclass": "Instance", "Tags": [], "Members": []},
    {"Name": "IntValue", "Superclass": "Instance", "Tags": [], "Members": [_m("Property", "Value")]},
], "Enums": [
    {"Name": "KeyCode", "Items": [{"Name": "E", "Value": 101}, {"Name": "Space", "Value": 32}]},
    {"Name": "Material", "Items": [{"Name": "Plastic", "Value": 256}, {"Name": "Neon", "Value": 288},
                                   {"Name": "OldStone", "Value": 1, "Tags": ["Deprecated"]}]},
    {"Name": "EasingStyle", "Items": [{"Name": "Quad", "Value": 1, "LegacyNames": ["Quadratic"]}]},
]}

API = ApiIndex(build_index(FAKE_DUMP, "0.1.0.1", "2026-10-28T00:00:00Z"))
V = core.Verifier(API)            # no luau-analyze binary: API checks only


def problems(code, lang="luau"):
    return V.verify(code, lang)["blocks"][0]["problems"]


def kinds(code, lang="luau"):
    return [(p["kind"], p["name"], p["suggestion"]) for p in problems(code, lang)]


GOOD_LUAU = """
local Players = game:GetService("Players")
local TweenService = game:GetService("TweenService")
local prompt = Instance.new("ProximityPrompt")
prompt.KeyboardKeyCode = Enum.KeyCode.E
prompt.Triggered:Connect(function(player)
    print(player.Name, player.UserId)
    local char = player.Character or player.CharacterAdded:Wait()
    local hum = char:FindFirstChildOfClass("Humanoid")
    hum:TakeDamage(10)
    hum.Health = 0
    char.Head.Anchored = true
end)
Players.PlayerAdded:Connect(function(player)
    local stats = Instance.new("Folder")
    stats.Name = "leaderstats"
    stats.Parent = player
end)
for _, p in ipairs(Players:GetPlayers()) do p:Kick("bye") end
local part = workspace:WaitForChild("Door")
part.Touched:Connect(function(hit) hit.Parent:FindFirstChild("Humanoid") end)
TweenService:Create(part, TweenInfo.new(1), {CFrame = part.CFrame}):Play()
game:BindToClose(function() task.wait(1) end)
"""


def test_index_meta_and_closest():
    assert API.meta["version"] == "0.1.0.1" and API.meta["classes"] == len(FAKE_DUMP["Classes"])
    assert API.member("Part", "Touched")[0] == "BasePart"          # found through the superclass chain
    assert closest("Helth", API.members("Humanoid")) == ["Health"]
    assert closest("players", API.services)[0] == "Players"
    assert all(c in API.classes for c in closest("Prat", API.classes))


def test_correct_code_has_no_problems():
    assert problems(GOOD_LUAU) == []


def test_unknown_and_deprecated_roblox_apis():
    code = """
local Players = game:GetService("Players")
Players.PlayerAdded:connect(function(player)
    print(player.userId)
    player:Teleport()
    player:SetSuperSecret()
end)
Players.PlayerJoined:Connect(print)
local p = Instance.new("Prat")
local bv = Instance.new("BodyVelocity")
local svc = Instance.new("Players")
local x = game:GetService("TweenServce")
print(Enum.KeyCod.E, Enum.Material.Plastik, Enum.Material.OldStone, Enum.EasingStyle.Quadratic)
workspace:FindPartOnRay()
wait(1)
"""
    got = kinds(code)
    assert ("deprecated", "PlayerAdded:connect", "Connect") in got
    assert ("deprecated", "Player.userId", "Player.UserId") in got
    assert ("unknown_api", "Player:Teleport", None) in got
    assert any(k == "not_accessible" and n == "Player:SetSuperSecret" for k, n, _ in got)
    assert ("unknown_api", "Players.PlayerJoined", "PlayerAdded or PlayerRemoving") in got
    assert ("unknown_class", "Prat", "Part") in got
    assert ("deprecated", "BodyVelocity", "LinearVelocity") in got
    assert any(k == "not_creatable" and n == "Players" for k, n, _ in got)
    assert ("unknown_service", "TweenServce", "TweenService") in got
    assert ("unknown_enum", "Enum.KeyCod", "KeyCode") in got
    assert ("unknown_enum", "Enum.Material.Plastik", "Enum.Material.Plastic") in got
    assert ("deprecated", "Enum.Material.OldStone", None) in got
    assert ("deprecated", "Enum.EasingStyle.Quadratic", "Enum.EasingStyle.Quad") in got
    assert ("deprecated", "Workspace:FindPartOnRay", "Workspace:Raycast") in got
    assert ("deprecated", "wait", "task.wait") in got
    # every suggestion that names an API comes from the dump (or the fixed deprecated-globals table)
    for _, _, s in got:
        for name in (s or "").replace(" or ", ",").split(","):
            leaf = name.strip().split(".")[-1].split(":")[-1]
            assert not leaf or leaf in API.all_member_names() | set(API.classes) | {"task", "wait", "Connect"} \
                or any(leaf in e["items"] or leaf == en for en, e in API.enums.items()), name


def test_case_slips_dot_calls_and_moved_methods():
    code = """
local Players = game:GetService("Players")
local TweenService = game:GetService("TweenService")
Players.PlayerAdded:Connect(function(player)
    player.CharacterAdded:Connect(function(char)
        local hum = char:FindFirstChildOfClass("Humanoid")
        hum.health = 0
        hum:LoadAnimation(nil)
    end)
end)
local t = TweenService.Create(nil)
local hit = Instance.new("Part")
hit.Touched:Connect(function(other) other:Explode() end)
"""
    got = kinds(code)
    assert ("unknown_api", "Humanoid.health", "Health") in got
    assert ("deprecated", "Humanoid:LoadAnimation", "Animator:LoadAnimation") in got
    assert ("wrong_call", "TweenService.Create", "TweenService:Create") in got
    assert ("unknown_api", "BasePart:Explode", None) in got
    assert kinds('local f = Instance.new("Folder")\nf.Name = "Leaderstats"\n') == \
        [("roblox_rule", "Leaderstats", '"leaderstats"')]


def test_children_are_not_flagged():
    code = """
local Players = game:GetService("Players")
Players.PlayerAdded:Connect(function(player)
    local coins = player.leaderstats.Coins
    coins.Value = coins.Value + 1
    player.Character.Humanoid.Health = 50
end)
script.Parent.Touched:Connect(function() end)
workspace.Map.Door.Transparency = 0.5
"""
    assert problems(code) == []


def test_minecraft_commands():
    good = ("give @s minecraft:diamond 1\nexecute as @a at @s if block ~ ~-1 ~ gold_block run tp @s 0 64 0\n"
            "effect give @p speed 30 1 true\nscoreboard objectives add kills playerKillCount\n"
            "scoreboard players set #temp kills 5\nsummon zombie ~ ~ ~\nfill ~ ~ ~ ~5 ~5 ~5 air hollow\n"
            "tellraw @a {\"text\":\"Hi\",\"color\":\"gold\"}\nfunction mypack:start\n# comment\n")
    assert minecraft.check_commands(good, in_function=True) == []
    bad = ("/give @s diamond\ngive @p diamond_sword{display:{}} 1\ngive @a wool 1 14\ntp @a[r=5] ~ ~10 ~\n"
           "tp @p ^ ~1 ^\nexecute @a ~ ~ ~ say hi\neffect @p speed 10 1\nsummon Zombie\ntellraw @a Hello\n"
           "gamemod creative\nexecute as @a fly run say x\n")
    got = {(p["line"], p["kind"]) for p in minecraft.check_commands(bad, in_function=True)}
    assert got >= {(1, "mc_function"), (2, "mc_syntax"), (3, "mc_syntax"), (4, "mc_selector"), (5, "mc_syntax"),
                   (6, "mc_syntax"), (7, "mc_syntax"), (8, "mc_syntax"), (9, "mc_syntax"),
                   (10, "mc_unknown_command"), (11, "mc_syntax")}
    sugg = {p["line"]: p["suggestion"] for p in minecraft.check_commands(bad, in_function=True)}
    assert sugg[10] == "/gamemode" and sugg[8] == "zombie"
    # chat / command block: a leading slash is fine
    assert minecraft.check_commands("/tp @p 0 64 0") == []
    # <placeholders> the reader fills in are not errors (a fix must not replace them with made-up values)
    assert minecraft.check_commands("tp <player> <spawn_x> <spawn_y> <spawn_z>\ngive @s <item> 1") == []


def test_datapack_rules_in_answer():
    answer = ("Put it in `data/mypack/functions/hello.mcfunction`:\n\n```mcfunction\nsay hi\n```\n\n"
              "pack.mcmeta:\n```json\n{\"pack\": {\"description\": \"x\"}}\n```\n")
    r = V.verify(answer)
    assert not r["ok"]
    assert r["problems"][0]["suggestion"] == "data/mypack/function/"
    assert r["blocks"][0]["ok"] and not r["blocks"][1]["ok"]


def test_csharp_light_checks():
    good = ("using UnityEngine;\npublic class M : MonoBehaviour {\n  void Update() { string s = \"{\"; }\n"
            "  void OnTriggerEnter(Collider other) { }\n}\n")
    assert csharp.check_csharp(good) == []
    bad = "public class M : MonoBehaviour {\n  void update() { }\n  void OnTriggerEnter(Collision c) { }\n"
    got = {p["kind"] + ":" + str(p["suggestion"]) for p in csharp.check_csharp(bad)}
    assert "unity_message:Update" in got and "syntax:using UnityEngine;" in got
    assert any(g.startswith("unity_message:OnTriggerEnter(Collider") for g in got)
    assert any(p["message"].startswith("'{'") for p in csharp.check_csharp(bad))


def test_blocks_and_language_detection():
    answer = ("Intro\n\n```lua\nlocal x = Instance.new(\"Prat\")\n```\n\nThen:\n\n```csharp\nvoid update() {}\n```\n"
              "\n```\n/gamemode creative\n/tp @p 0 64 0\n```\n\n```java\nclass A {}\n```\n\n```lua\nlocal y = 1\n")
    r = V.verify(answer)
    langs = [(b["language"], b["checked"], b["ok"]) for b in r["blocks"]]
    assert langs == [("luau", True, False), ("csharp", True, False), ("minecraft", True, True),
                     ("java", False, True), ("luau", True, True)]      # last fence never closed: still checked
    assert r["blocks"][0]["problems"][0]["answer_line"] == 4
    assert V.verify("give @p diamond 1 0 0", "minecraft")["blocks"][0]["ok"] is False
    # prose without fences is not code unless the caller says so ("auto" = detect)
    prose = "A variable is a box. local score = 0 means a box named score holds 0, and then it can change."
    assert V.verify(prose)["blocks"] == []
    assert V.verify("/gamemode creative\n/tp @p 0 64 0", "auto")["blocks"][0]["language"] == "minecraft"


class FakeModel:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, messages):
        self.calls.append(messages)
        return self.replies.pop(0)


def test_fix_loop_repairs_and_reverifies():
    answer = ("Here you go:\n\n```lua\nlocal Players = game:GetService(\"Players\")\n"
              "Players.PlayerAdded:connect(function(player)\n    print(player.userId)\nend)\n```\n\nEnjoy!\n")
    model = FakeModel(["```lua\nlocal Players = game:GetService(\"Players\")\n"
                       "Players.PlayerAdded:Connect(function(player)\n    print(player.UserId)\nend)\n```"])
    r = V.fix(answer, model)
    assert r["ok"] and r["rounds"] == 1 and len(model.calls) == 1
    assert "PlayerAdded:Connect" in r["answer"] and r["answer"].startswith("Here you go:") and \
        r["answer"].endswith("Enjoy!\n")
    prompt = model.calls[0][1]["content"]
    assert "use: Connect" in prompt and "use: Player.UserId" in prompt
    assert r["before"]["warnings"] == 2 and r["after"] == {"errors": 0, "warnings": 0, "blocks_failing": 0}


def test_fix_loop_second_round_and_give_up():
    answer = "```lua\nlocal p = Instance.new(\"Prat\")\n```\n"
    model = FakeModel(["```lua\nlocal p = Instance.new(\"Partt\")\n```", "```lua\nlocal p = Instance.new(\"Part\")\n```"])
    r = V.fix(answer, model)
    assert r["ok"] and r["rounds"] == 2 and 'Instance.new("Part")' in r["answer"]
    stubborn = FakeModel(["```lua\nlocal p = Instance.new(\"Prat2\")\n```", "```lua\nlocal p = Instance.new(\"Prat3\")\n```"])
    r = V.fix(answer, stubborn)
    assert not r["ok"] and r["rounds"] == 2 and len(stubborn.calls) == 2     # max 2 rounds, then the last version

    def broken(messages):
        raise OSError("router down")
    r = V.fix(answer, broken)
    assert r["answer"] == answer and "fix call failed" in r["changes"][0]["error"]


def test_fix_loop_good_answer_never_calls_model():
    model = FakeModel([])
    r = V.fix("```lua\n" + GOOD_LUAU + "```\n", model)
    assert r["ok"] and r["rounds"] == 0 and model.calls == []


def test_http_service(tmp_path):
    index = tmp_path / "index.json"
    index.write_text(json.dumps(build_index(FAKE_DUMP, "0.1.0.1")), encoding="utf-8")
    keys = tmp_path / "api_keys"
    keys.write_text(KEY + "\n", encoding="utf-8")
    seen = []

    def factory(cfg, auth):
        seen.append(auth)
        return FakeModel(["```lua\nprint(Enum.KeyCode.E)\n```"])
    cfg = dict(service.DEFAULTS, listen="127.0.0.1", port=0, index=str(index), luau_analyze=None,
               client_keys_file=str(keys))
    srv = service.serve(cfg, factory)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]

    def call(method, path, body=None, key=KEY):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request(method, path, json.dumps(body) if body is not None else None,
                  {"Authorization": f"Bearer {key}", "Content-Type": "application/json"} if key else {})
        r = c.getresponse()
        return r.status, json.loads(r.read())
    try:
        assert call("GET", "/health", key=None)[1]["dump"]["version"] == "0.1.0.1"
        assert call("POST", "/mesh/verify", {"code": "x"}, key="wrong")[0] == 401
        assert call("POST", "/mesh/verify", {})[0] == 400
        st, r = call("POST", "/mesh/verify", {"code": "print(Enum.KeyCode.Q)", "language": "luau"})
        assert st == 200 and not r["ok"] and r["blocks"][0]["problems"][0]["kind"] == "unknown_enum"
        st, r = call("POST", "/mesh/verify?fix=1", {"answer": "```lua\nprint(Enum.KeyCode.Q)\n```\n"})
        assert st == 200 and r["ok"] and "Enum.KeyCode.E" in r["answer"] and seen == [f"Bearer {KEY}"]
    finally:
        srv.shutdown()
        srv.server_close()
