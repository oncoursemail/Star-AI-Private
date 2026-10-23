---
id: gb-world-vfx-server-to-clients
category: vfx-particles
topics: UnreliableRemoteEvent, client VFX, FireClient, range culling, explosions
source: original
---
# Request
My server creates explosion effects (parts with particle emitters) directly in workspace, and with 30 players the server's network usage spikes every time a grenade goes off. What's the better pattern?

# Answer
The server decides that an explosion happened and where; each client builds the visuals itself from its own copy of the effect templates. Send the event only to players close enough to see it, over an `UnreliableRemoteEvent` since a dropped cosmetic is harmless. Gameplay (damage) stays on the server.

```lua
--!strict
-- ModuleScript: ServerScriptService.EffectBroadcast
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local playEffect = ReplicatedStorage:WaitForChild("PlayEffect")

local EffectBroadcast = {}

function EffectBroadcast.send(effectName: string, position: Vector3, visibleRange: number): number
	local recipients = 0
	for _, player in Players:GetPlayers() do
		if player.Character and player:DistanceFromCharacter(position) <= visibleRange then
			playEffect:FireClient(player, effectName, position)
			recipients += 1
		end
	end
	return recipients
end

return EffectBroadcast
```

The client side, in StarterPlayerScripts:

```lua
--!strict
local Debris = game:GetService("Debris")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local playEffect = ReplicatedStorage:WaitForChild("PlayEffect")
local templates = ReplicatedStorage:WaitForChild("EffectTemplates")

playEffect.OnClientEvent:Connect(function(effectName: string, position: Vector3)
	local template = templates:FindFirstChild(effectName)
	if template == nil or not template:IsA("Attachment") then
		return
	end
	local effect = template:Clone()
	effect.Parent = workspace.Terrain
	effect.WorldPosition = position
	for _, emitter in effect:GetChildren() do
		if emitter:IsA("ParticleEmitter") then
			local count = emitter:GetAttribute("EmitCount")
			emitter:Emit(if type(count) == "number" then count else 20)
		end
	end
	Debris:AddItem(effect, 3)
end)
```

- Replicating effect parts sends every part, emitter and property to every client; the remote sends a name and a Vector3.
- Players without a character (menus, respawning) are skipped because `DistanceFromCharacter` returns 0 for them, which would otherwise count as "in range".
- UnreliableRemoteEvent messages can arrive out of order or not at all, which is acceptable for visuals and never for game state.
- Create the remote in Studio as an UnreliableRemoteEvent named PlayEffect under ReplicatedStorage.

# Test
```lua
local remote = Instance.new("UnreliableRemoteEvent")
remote.Name = "PlayEffect"
remote.Parent = game:GetService("ReplicatedStorage")
```
```lua
local near = __makePlayer(11, "Near")
__makeCharacter(near, Vector3.new(10, 3, 0))
local far = __makePlayer(12, "Far")
__makeCharacter(far, Vector3.new(900, 3, 0))
local menu = __makePlayer(13, "InMenu")
local remote = game:GetService("ReplicatedStorage").PlayEffect

local count = item.send("Grenade", Vector3.new(0, 3, 0), 200)
check("only one player in range", count == 1 and #remote.__sent == 1)
check("sent to the near player with name and position", remote.__sent[1][1] == near and remote.__sent[1][2] == "Grenade")
check("far and characterless players skipped", remote.__sent[1][1] ~= far and remote.__sent[1][1] ~= menu)
__makeCharacter(menu, Vector3.new(0, 3, 50))
check("respawned player now receives", item.send("Grenade", Vector3.new(0, 3, 0), 200) == 2)
```
