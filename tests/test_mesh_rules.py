"""Roblox architecture rules (server/mesh/rules): one true-positive and one false-positive case per rule, the answer
parser (labels, script kinds, places), the Luau scan helpers, the targeted fix pass (kept only when better) and the hook
in the loop runner."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from mesh.rules import fix, rules, scan  # noqa: E402
# `server/` holds a `discord` folder: leaving it on sys.path would shadow the discord package for tests collected later
sys.path.remove(str(ROOT / "server"))


def ids(text: str, question: str = "How do I do this in Roblox?") -> set[str]:
    return {h["rule"] for h in rules.check(text, question)}


def lua(label: str, code: str, prose: str = "") -> str:
    return f"{prose}\n\n{label}\n```lua\n{code.strip()}\n```\n"


# ---- parser -----------------------------------------------------------------------------------------------------------
def test_labels_give_kind_and_place():
    a = scan.parse(lua("**LocalScript (inside StarterPlayerScripts):**", "print(1)") +
                   lua("Place this **Script** in `ServerScriptService`:", "print(2)") +
                   lua("Put a Script inside your Door part:", "print(3)") +
                   lua("", "-- ModuleScript in ReplicatedStorage\nreturn {}"))
    got = [(b.kind, b.place) for b in a.blocks]
    assert got == [("local", "client"), ("server", "sss"), ("server", "world"), ("module", "storage")]


def test_comparison_block_with_two_script_types_is_either():
    code = "-- Put this in a Script inside ServerScriptService\nprint(1)\n-- Put this in a LocalScript in " \
           "StarterPlayerScripts\nprint(game.Players.LocalPlayer)"
    assert scan.parse(lua("Example:", code)).blocks[0].kind == "either"


def test_blank_keeps_offsets_and_hides_comments_and_strings():
    code = 'local s = "wait(1) -- not code"\n-- wait(2)\nprint(s)'
    c = scan.blank(code)
    assert len(c) == len(code) and "wait" not in c and c.count("\n") == 2 and "print(s)" in c


def test_body_end_and_handlers():
    code = ("part.Touched:Connect(function(hit)\n if hit then\n  for i = 1, 2 do print(i) end\n end\nend)\n"
            "local function onEvent(player, amount)\n print(amount)\nend\nremote.OnServerEvent:Connect(onEvent)\n")
    c = scan.blank(code)
    (params, body), = scan.handlers(c, "Touched")
    assert params == ["hit"] and "for i" in body and "onEvent" not in body
    (params2, body2), = scan.handlers(c, "OnServerEvent")
    assert params2 == ["player", "amount"] and "print(amount)" in body2


def test_protected_spans_inline_and_named():
    code = ("local ok, v = pcall(function()\n return store:GetAsync(k)\nend)\n"
            "local function save(p)\n store:SetAsync(k, 1)\nend\npcall(save, plr)\nstore:RemoveAsync(k)\n")
    c = scan.blank(code)
    spans = scan.protected_spans(c)
    inside = lambda word: any(s <= c.find(word) < e for s, e in spans)  # noqa: E731
    assert inside("GetAsync") and inside("SetAsync") and not inside("RemoveAsync")


def test_non_roblox_answers_are_skipped():
    unity = "Use this C# script:\n```csharp\nusing UnityEngine;\npublic class A : MonoBehaviour {}\n```"
    assert rules.check(unity, "How do I move in Unity?") == []


# ---- 1. placement -------------------------------------------------------------------------------------------------------
def test_localscript_never_runs():
    bad = lua("**LocalScript (Inside the ProximityPrompt):**", "script.Parent.Triggered:Connect(function() end)")
    assert "localscript-never-runs" in ids(bad)
    either = lua("", "-- LocalScript or Script (Put inside the Part)\nscript.Parent.Color = Color3.new(1, 0, 0)")
    assert "localscript-never-runs" in ids(either)
    assert "localscript-never-runs" in ids("Put a LocalScript inside the door part and paste this.")
    good = lua("**LocalScript (inside StarterPlayerScripts):**", "print('hi')")
    assert "localscript-never-runs" not in ids(good)
    tip = "A LocalScript will not run if you put it in Workspace or ServerScriptService."
    assert "localscript-never-runs" not in ids(tip)
    listing = ("You'll need a RemoteEvent in ReplicatedStorage, a LocalScript for the button, and a Script in "
               "ServerScriptService.")
    assert "localscript-never-runs" not in ids(listing)


def test_script_never_runs():
    assert "script-never-runs" in ids(lua("Put this **Script** in StarterPlayerScripts:", "print(1)"))
    assert "script-never-runs" not in ids(lua("Put this **Script** in ServerScriptService:", "print(1)"))


def test_server_api_in_localscript():
    bad = lua("**LocalScript (StarterPlayerScripts):**", 'local ds = game:GetService("DataStoreService")')
    assert "server-api-in-localscript" in ids(bad)
    good = lua("**Script (ServerScriptService):**", 'local ds = game:GetService("DataStoreService")')
    assert "server-api-in-localscript" not in ids(good)
    commented = lua("**LocalScript (StarterPlayerScripts):**", "-- never use DataStoreService here\nprint(1)")
    assert "server-api-in-localscript" not in ids(commented)


def test_client_api_in_server_script():
    bad = lua("**Script (ServerScriptService):**", "local player = game.Players.LocalPlayer\nprint(player)")
    assert "client-api-in-server-script" in ids(bad)
    chat = lua("Create a **Script** in `ServerScriptService`:",
               'local TCS = game:GetService("TextChatService")\nTCS.MessageReceived:Connect(function(m) end)')
    assert "client-api-in-server-script" in ids(chat)
    good = lua("**LocalScript (StarterPlayerScripts):**", "local player = game.Players.LocalPlayer")
    assert "client-api-in-server-script" not in ids(good)


def test_fireserver_and_onserverevent_in_one_script():
    bad = lua("Put this script in the part:", "remote:FireServer()\nremote.OnServerEvent:Connect(function(p) end)")
    assert "fireserver-and-onserverevent-in-one-script" in ids(bad)
    assert "fireserver-and-onserverevent-in-one-script" not in ids(lua("**LocalScript (StarterGui):**",
                                                                       "remote:FireServer()"))


def test_script_parent_is_a_service():
    bad = lua("Place this **Script** in `ServerScriptService`:", "script.Parent.Touched:Connect(function(h) end)")
    assert "script-parent-is-a-service" in ids(bad)
    good = lua("Place this **Script** inside the part:", "script.Parent.Touched:Connect(function(h) end)")
    assert "script-parent-is-a-service" not in ids(good)


# ---- 2. client-server trust ---------------------------------------------------------------------------------------------
def test_client_changes_currency():
    bad = lua("**LocalScript (inside a TextButton in StarterGui):**",
              "script.Parent.MouseButton1Click:Connect(function()\n"
              " game.Players.LocalPlayer.leaderstats.Coins.Value += 10\nend)")
    assert "client-changes-currency" in ids(bad)
    good = lua("**LocalScript (inside a TextButton in StarterGui):**",
               "script.Parent.MouseButton1Click:Connect(function()\n remote:FireServer('Claim')\nend)")
    assert "client-changes-currency" not in ids(good)


def test_server_trusts_client_value():
    capped = lua("**Script (Server)**", "remote.OnServerEvent:Connect(function(player, amount)\n"
                 " if typeof(amount) == 'number' and amount <= 100 then\n  print(amount)\n end\nend)")
    assert "server-trusts-client-value" in ids(capped)
    target = lua("**Script (ServerScriptService):**", "remote.OnServerEvent:Connect(function(player, targetModel)\n"
                 " local h = targetModel:FindFirstChild('Humanoid')\n if h then h:TakeDamage(20) end\nend)")
    assert "server-trusts-client-value" in ids(target)
    keyed = lua("**Script (ServerScriptService):**", "local prices = {Sword = 100}\n"
                "remote.OnServerEvent:Connect(function(player, itemName)\n local price = prices[itemName]\n"
                " if price and player.leaderstats.Coins.Value >= price then\n"
                "  player.leaderstats.Coins.Value -= price\n end\nend)")
    assert "server-trusts-client-value" not in ids(keyed)
    ranged = lua("**Script (ServerScriptService):**", "remote.OnServerEvent:Connect(function(player, target)\n"
                 " if (target.HumanoidRootPart.Position - player.Character.HumanoidRootPart.Position).Magnitude < 10"
                 " then\n  target.Humanoid:TakeDamage(10)\n end\nend)")
    assert "server-trusts-client-value" not in ids(ranged)


def test_remote_no_rate_limit():
    bad = lua("**Script (ServerScriptService):**",
              "remote.OnServerEvent:Connect(function(player)\n player.leaderstats.Points.Value += 1\nend)")
    assert "remote-no-rate-limit" in ids(bad)
    good = lua("**Script (ServerScriptService):**", "local last = {}\n"
               "remote.OnServerEvent:Connect(function(player)\n"
               " if last[player] and os.clock() - last[player] < 1 then return end\n last[player] = os.clock()\n"
               " player.leaderstats.Points.Value += 1\nend)")
    assert "remote-no-rate-limit" not in ids(good)


# ---- 3. Touched ---------------------------------------------------------------------------------------------------------
def test_touched_no_debounce():
    bad = lua("Place a **Script** inside your Part:", "local part = script.Parent\n"
              "part.Touched:Connect(function(hit)\n local h = hit.Parent:FindFirstChild('Humanoid')\n"
              " if h then\n  h.Health = h.Health - 10\n  task.wait(0.5)\n end\nend)")
    assert "touched-no-debounce" in ids(bad)
    good = lua("Place a **Script** inside your Part:", "local part = script.Parent\nlocal touched = {}\n"
               "part.Touched:Connect(function(hit)\n local plr = game.Players:GetPlayerFromCharacter(hit.Parent)\n"
               " if not plr or touched[plr] then return end\n touched[plr] = true\n"
               " plr.leaderstats.Coins.Value += 1\n task.wait(1)\n touched[plr] = nil\nend)")
    assert "touched-no-debounce" not in ids(good)
    kill = lua("Place a **Script** inside your Part:", "script.Parent.Touched:Connect(function(hit)\n"
               " local h = hit.Parent:FindFirstChild('Humanoid')\n if h then h.Health = 0 end\nend)")
    assert "touched-no-debounce" not in ids(kill)


# ---- 4. DataStores ------------------------------------------------------------------------------------------------------
DS = 'local store = game:GetService("DataStoreService"):GetDataStore("Coins")\n'


def test_datastore_no_pcall():
    bad = lua("**Script (ServerScriptService):**", DS + "game.Players.PlayerAdded:Connect(function(p)\n"
              " local v = store:GetAsync(p.UserId)\nend)")
    assert "datastore-no-pcall" in ids(bad)
    good = lua("**Script (ServerScriptService):**", DS + "game.Players.PlayerAdded:Connect(function(p)\n"
               " local ok, v = pcall(function() return store:GetAsync(p.UserId) end)\nend)")
    assert "datastore-no-pcall" not in ids(good)


def test_datastore_save_on_character_removing():
    bad = lua("**Script (ServerScriptService):**", DS + "p.CharacterRemoving:Connect(function()\n"
              " pcall(function() store:SetAsync(p.UserId, 1) end)\nend)")
    assert "datastore-save-on-character-removing" in ids(bad)
    good = lua("**Script (ServerScriptService):**", DS + "game.Players.PlayerRemoving:Connect(function(p)\n"
               " pcall(function() store:SetAsync(p.UserId, 1) end)\nend)\ngame:BindToClose(function() end)")
    assert "datastore-save-on-character-removing" not in ids(good)


def test_datastore_no_bindtoclose():
    bad = lua("**Script (ServerScriptService):**", DS + "game.Players.PlayerRemoving:Connect(function(p)\n"
              " pcall(function() store:SetAsync(p.UserId, 1) end)\nend)")
    assert "datastore-no-bindtoclose" in ids(bad)
    good = bad.replace("end)\n```", "end)\ngame:BindToClose(function() end)\n```")
    assert "datastore-no-bindtoclose" not in ids(good)


def test_datastore_failed_load_overwrites():
    load = (DS + "game.Players.PlayerAdded:Connect(function(p)\n"
            " local ok, data = pcall(function() return store:GetAsync(p.UserId) end)\n"
            " coins.Value = (ok and data) or 0\nend)\n"
            "game.Players.PlayerRemoving:Connect(function(p)\n"
            " pcall(function() store:SetAsync(p.UserId, coins.Value) end)\nend)\ngame:BindToClose(function() end)")
    assert "datastore-failed-load-overwrites" in ids(lua("**Script (ServerScriptService):**", load))
    guarded = load.replace(" coins.Value = (ok and data) or 0", " loaded[p] = ok\n coins.Value = (ok and data) or 0")
    assert "datastore-failed-load-overwrites" not in ids(lua("**Script (ServerScriptService):**", guarded))


def test_datastore_new_player_never_saved():
    code = (DS + "local ok, data = pcall(function() return store:GetAsync(k) end)\n"
            "sessionData[p.UserId] = ok and data\n")
    assert "datastore-new-player-never-saved" in ids(lua("**Script (ServerScriptService):**", code))
    good = code.replace("sessionData[p.UserId] = ok and data", "sessionData[p.UserId] = ok")
    assert "datastore-new-player-never-saved" not in ids(lua("**Script (ServerScriptService):**", good))


def test_datastore_save_every_change():
    bad = lua("**Script (ServerScriptService):**", DS + "coins.Changed:Connect(function(v)\n"
              " pcall(function() store:SetAsync(key, v) end)\nend)")
    assert "datastore-save-every-change" in ids(bad)
    assert "datastore-save-every-change" not in ids(lua("**Script (ServerScriptService):**",
                                                        DS + "coins.Changed:Connect(function(v) print(v) end)"))


def test_datastore_stores_vector3():
    bad = lua("**Script (ServerScriptService):**", DS + "pcall(function() store:SetAsync(key, root.Position) end)")
    assert "datastore-stores-vector3" in ids(bad)
    good = lua("**Script (ServerScriptService):**", DS + "local p = root.Position\n"
               "pcall(function() store:SetAsync(key, {x = p.X, y = p.Y, z = p.Z}) end)")
    assert "datastore-stores-vector3" not in ids(good)


def test_web_call_no_pcall():
    bad = lua("Place this **Script** inside your NPC:", "path:ComputeAsync(a, b)")
    assert "web-call-no-pcall" in ids(bad)
    good = lua("Place this **Script** inside your NPC:", "local ok = pcall(function() path:ComputeAsync(a, b) end)")
    assert "web-call-no-pcall" not in ids(good)


# ---- 5. loops, deprecated, remotes ----------------------------------------------------------------------------------------
def test_loop_without_yield():
    assert "loop-without-yield" in ids(lua("Put a **Script** in the part:", "while true do\n part.CFrame *= r\nend"))
    assert "loop-without-yield" not in ids(lua("Put a **Script** in the part:",
                                               "while true do\n part.CFrame *= r\n task.wait()\nend"))
    assert "loop-without-yield" not in ids(lua("Put a **Script** in the part:",
                                               "while true do\n if done then break end\nend"))


def test_deprecated_scheduler_and_body_mover():
    assert "deprecated-scheduler" in ids(lua("Script:", "wait(1)"))
    assert "deprecated-scheduler" not in ids(lua("Script:", "task.wait(1)\nanimTrack.Stopped:Wait()"))
    assert "deprecated-body-mover" in ids(lua("Script:", 'local bv = Instance.new("BodyVelocity")'))
    assert "deprecated-body-mover" not in ids(lua("Script:", '-- not Instance.new("BodyVelocity")\nprint(1)'))


def test_invokeclient_from_server():
    bad = lua("**Script (ServerScriptService):**", "local answer = rf:InvokeClient(player)")
    assert "invokeclient-from-server" in ids(bad)
    warned = bad + "\nCareful: InvokeClient can hang forever if the client never returns."
    assert "invokeclient-from-server" not in ids(warned)


def test_remote_created_twice():
    code = 'local r = Instance.new("RemoteEvent")\nr.Name = "Buy"\nr.Parent = game.ReplicatedStorage'
    bad = "1. Insert a RemoteEvent into ReplicatedStorage named Buy.\n" + lua("**Script (ServerScriptService):**", code)
    assert "remote-created-twice" in ids(bad)
    assert "remote-created-twice" not in ids(lua("**Script (ServerScriptService):**", code))


def test_remote_never_created():
    code = 'local ev = game.ReplicatedStorage:WaitForChild("ToggleEffect")\nev:FireServer()'
    assert "remote-never-created" in ids(lua("**LocalScript (StarterPlayerScripts):**", code))
    told = "In ReplicatedStorage add a RemoteEvent named \"ToggleEffect\"." + \
        lua("**LocalScript (StarterPlayerScripts):**", code)
    assert "remote-never-created" not in ids(told)


# ---- 6. physics -----------------------------------------------------------------------------------------------------------
def test_constraint_without_attachment():
    bad = lua("Put this **Script** inside the pad:", 'local lv = Instance.new("LinearVelocity")\nlv.MaxForce = 1e5\n'
              'lv.Parent = root')
    assert "constraint-without-attachment" in ids(bad)
    good = lua("Put this **Script** inside the pad:", 'local att = Instance.new("Attachment", root)\n'
               'local lv = Instance.new("LinearVelocity")\nlv.Attachment0 = att\nlv.Parent = root')
    assert "constraint-without-attachment" not in ids(good)


def test_hinge_servo_not_set():
    bad = lua("**Script (inside the Hinge Part):**", "hinge.TargetAngle = 90") + \
        "\nOne common mistake is forgetting to set ActuatorType to Servo."
    assert "hinge-servo-not-set" in ids(bad)
    good = lua("**Script (inside the Hinge Part):**", "hinge.ActuatorType = Enum.ActuatorType.Servo\n"
               "hinge.TargetAngle = 90")
    assert "hinge-servo-not-set" not in ids(good)


# ---- 7. incomplete ----------------------------------------------------------------------------------------------------------
def test_placeholder_code():
    bad = lua("**Script (ServerScriptService):**", "remote.OnServerEvent:Connect(function(p)\n"
              " -- Add your code here to clone the sword into the player's Backpack\nend)")
    assert "placeholder-code" in ids(bad)
    template = lua("**Script (ServerScriptService):**", "seat.Changed:Connect(function()\n"
                   " -- Add your custom logic here (e.g., changing colors or playing sounds)\nend)")
    assert "placeholder-code" not in ids(template)


# ---- 8. claims ------------------------------------------------------------------------------------------------------------
def test_myths():
    q = "How do I save coins with DataStores in Roblox?"
    assert "myth-allow-http-for-datastores" in ids("Turn on Allow HTTP Requests in Game Settings first.", q)
    assert "myth-allow-http-for-datastores" not in ids("You do not need Allow HTTP Requests for DataStores.", q)
    assert "myth-filteringenabled" in ids("Make sure FilteringEnabled is turned on in Workspace.")
    assert "myth-filteringenabled" not in ids("FilteringEnabled is always on now, so use RemoteEvents.")
    assert "myth-respawntime-default" in ids("Players.RespawnTime has a default of 3 seconds.")
    assert "myth-respawntime-default" not in ids("Players.RespawnTime has a default of 5 seconds.")
    assert "myth-bindtoclose-on-crash" in ids("BindToClose makes sure data saves even if the server crashes.")
    assert "myth-bindtoclose-on-crash" not in ids("BindToClose does not run if the server crashes.")
    assert "myth-third-party-sales" in ids("Enable Allow Third Party Sales so your game pass can be bought.")
    assert "myth-third-party-sales" not in ids("Third Party Sales is only for selling other creators' items.")
    assert "myth-third-party-teleports" in ids("One common mistake is forgetting to enable \"Allow Third Party "
                                               "Teleports\" in Game Settings.", "Teleport to another place in my Roblox game")
    assert "myth-pcall-stops-hang" in ids("Wrap InvokeServer in a pcall, as the script will hang indefinitely "
                                          "if the server fails to return.")
    assert "myth-pcall-stops-hang" not in ids("pcall only catches errors; it does not stop a hang.")
    anim = "Do not just play the animation in a LocalScript; if you do that, only the player will see themselves move!"
    assert "myth-local-animation-not-replicated" in ids(anim.replace("Do not just play", "Play"))
    assert "myth-random-needs-seed" in ids("One common mistake is using math.random(1, 100) without seeding.")
    assert "myth-random-needs-seed" not in ids("math.random is seeded automatically in Luau.")
    assert "myth-module-shares-between-clients" in ids("A ModuleScript shares its data between clients.")
    assert "myth-module-shares-between-clients" not in ids("A ModuleScript does not share data between clients.")


def test_claims_against_code():
    code = lua("**Script (ServerScriptService):**", "local coins = Instance.new('IntValue')")
    assert "claim-saves-without-saving" in ids("Your coins are saved when they leave the game." + code)
    saved = lua("**Script (ServerScriptService):**", DS + "pcall(function() store:SetAsync(k, 1) end)")
    assert "claim-saves-without-saving" not in ids("Your coins are saved when they leave the game." + saved)
    assert "claim-no-script-needed" in ids("No script is needed for this." + code)
    assert "claim-no-script-needed" not in ids("No script is needed for this, just set the property.")


def test_every_rule_has_text_and_a_test():
    src = Path(__file__).read_text(encoding="utf-8")
    for r in rules.RULES:
        assert r.severity in ("error", "warning") and r.message and r.note and r.family
        assert f'"{r.id}"' in src, f"no test for {r.id}"


def test_a_crashing_rule_never_breaks_the_check(monkeypatch):
    boom = rules.Rule("boom", "error", "x", "m", "n", (), lambda a, q: 1 / 0)
    monkeypatch.setattr(rules, "RULES", rules.RULES + [boom])
    hits = rules.check(lua("Script:", "print(1)"))
    assert any(h["rule"] == "boom" and h["severity"] == "info" for h in hits)
    assert not rules.errors([h for h in hits if h["rule"] == "boom"])


# ---- fix pass -------------------------------------------------------------------------------------------------------------
BAD_ANSWER = ("Use a ProximityPrompt.\n\n**LocalScript (Inside the ProximityPrompt):**\n```lua\n"
              "script.Parent.Triggered:Connect(function() print('open') end)\n```\n")
GOOD_ANSWER = ("Use a ProximityPrompt.\n\n**Script (inside the Door part):**\n```lua\n"
               "script.Parent.ProximityPrompt.Triggered:Connect(function(player) print('open') end)\n```\n")


def run(coro):
    return asyncio.run(coro)


def test_fix_keeps_a_better_rewrite_and_returns_notes():
    seen = {}

    async def model(body):
        seen["prompt"] = body["messages"][1]["content"]
        return {"text": "Here is the corrected version:\n\n" + GOOD_ANSWER, "finish": "stop"}

    async def docs(names):
        seen["names"] = names
        return "ProximityPrompt.Triggered(playerWhoTriggered: Player)"

    text, info = run(fix.run("door with E", BAD_ANSWER, model, docs=docs))
    assert text == GOOD_ANSWER.strip() and info["result"] == "fixed"
    assert "LocalScripts only run" in info["notes"][0]
    assert "LocalScript is placed where LocalScripts never run" in seen["prompt"]
    assert "Official Roblox docs" in seen["prompt"] and "ProximityPrompt.Triggered" in seen["names"]


def test_fix_keeps_the_original_when_the_rewrite_is_not_better():
    async def same(body):
        return {"text": BAD_ANSWER, "finish": "stop"}

    async def worse(body):
        return {"text": BAD_ANSWER + "\n```lua\nwhile true do\n x = 1\nend\n```\n", "finish": "stop"}

    async def cut(body):
        return {"text": GOOD_ANSWER[:-6], "finish": "length"}

    async def down(body):
        raise ConnectionError("node down")

    for model, why in ((same, "not reduced"), (worse, "adds rule problems"), (cut, "cut off"), (down, "model error")):
        text, info = run(fix.run("door with E", BAD_ANSWER, model))
        assert text == BAD_ANSWER and why in info["result"], info


def test_fix_rejects_a_rewrite_the_verifier_likes_less():
    async def model(body):
        return {"text": GOOD_ANSWER, "finish": "stop"}

    async def verify(text):
        n = 0 if text == BAD_ANSWER else 1
        return {"blocks": [{"problems": [{"severity": "error"}] * n}], "problems": []}

    text, info = run(fix.run("door with E", BAD_ANSWER, model, verify=verify))
    assert text == BAD_ANSWER and "verifier worse" in info["result"]


def test_fix_times_out_and_skips_clean_answers():
    async def slow(body):
        await asyncio.sleep(2)
        return {"text": GOOD_ANSWER, "finish": "stop"}

    text, info = run(fix.run("door with E", BAD_ANSWER, slow, budget_s=0.6))
    assert text == BAD_ANSWER and "timed out" in info["result"]

    async def never(body):
        raise AssertionError("no model call for a clean answer")

    text, info = run(fix.run("door with E", GOOD_ANSWER, never))
    assert text == GOOD_ANSWER and info["result"] == "no rule errors"


def test_fix_rejects_a_much_longer_rewrite():
    long = GOOD_ANSWER + "\n" + " ".join(["word"] * 400)

    async def model(body):
        return {"text": long, "finish": "stop"}

    text, info = run(fix.run("door with E", BAD_ANSWER, model))
    assert text == BAD_ANSWER and "too long" in info["result"]


# ---- router hook (server/mesh/loop/runner.py) ------------------------------------------------------------------------
def test_router_sends_the_rule_fix_as_mesh_replace(tmp_path):
    import test_mesh_loop as tl                      # the loop tests' fake node, fake verifier and router setup

    async def go():
        node = tl.Node(BAD_ANSWER, GOOD_ANSWER)      # non-stream calls (here: the fix pass) get GOOD_ANSWER
        r, port, ver = await tl.setup(tmp_path, node, loop_best_of_nodes=[], rules_docs_url="http://127.0.0.1:9")
        evs = tl.events(await asyncio.to_thread(tl.call, port, tl.CHAT))
        assert tl.streamed_text(evs) == BAD_ANSWER
        rep = [e for e in evs if e.get("object") == "mesh.replace"]
        assert len(rep) == 1 and rep[0]["mesh_replace"]["source"] == "rules"
        assert rep[0]["mesh_replace"]["content"] == GOOD_ANSWER.strip() and rep[0]["mesh_replace"]["notes"]
        fix_req = [q for q in node.requests if not q.get("stream")][0]
        assert "checker that knows Roblox" in fix_req["messages"][0]["content"]
        assert r.decisions[-1]["loop"]["rules"]["result"] == "fixed" and r.nodes[0].inflight == 0
        r.cfg["rules_enabled"] = False
        evs = tl.events(await asyncio.to_thread(tl.call, port, tl.CHAT))
        assert not [e for e in evs if e.get("object") == "mesh.replace"]
    tl.arun(go())
