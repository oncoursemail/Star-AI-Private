---
id: gb-eng-debug-respawn-connection-leak
category: engineering-debugging
topics: memory leak, connections, CharacterAdded, Heartbeat, disconnect
source: original
---
# Request
My stamina regen gets faster every time a player respawns, and server memory climbs over a long session. What's wrong with this?

```lua
game.Players.PlayerAdded:Connect(function(plr)
	plr.CharacterAdded:Connect(function(char)
		local hum = char:WaitForChild("Humanoid")
		plr:SetAttribute("Stamina", 100)
		game:GetService("RunService").Heartbeat:Connect(function(dt)
			local stamina = plr:GetAttribute("Stamina")
			plr:SetAttribute("Stamina", math.min(100, stamina + 10 * dt))
		end)
	end)
end)
```

# Answer
Each respawn connects a new Heartbeat handler and none are ever disconnected: `RunService.Heartbeat` lives forever, so after five respawns five handlers regen stamina (5x speed), and each one keeps its `plr`, `char` and `hum` alive after they are gone. Keep the connection and disconnect it when that character goes away; one per-player handler is the cleaner fix.

```lua
--!strict
-- Script: ServerScriptService.Stamina
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")

local MAX_STAMINA = 100
local REGEN_PER_SECOND = 10

local regenConnections: { [Player]: RBXScriptConnection } = {}

local function stopRegen(player: Player)
	local connection = regenConnections[player]
	if connection then
		connection:Disconnect()
		regenConnections[player] = nil
	end
end

local function onCharacterAdded(player: Player, _character: Model)
	stopRegen(player) -- never more than one handler per player
	player:SetAttribute("Stamina", MAX_STAMINA)
	regenConnections[player] = RunService.Heartbeat:Connect(function(dt: number)
		local stamina = player:GetAttribute("Stamina")
		if type(stamina) == "number" and stamina < MAX_STAMINA then
			player:SetAttribute("Stamina", math.min(MAX_STAMINA, stamina + REGEN_PER_SECOND * dt))
		end
	end)
end

local function onPlayerAdded(player: Player)
	player.CharacterAdded:Connect(function(character: Model)
		onCharacterAdded(player, character)
	end)
	player.CharacterRemoving:Connect(function()
		stopRegen(player)
	end)
	if player.Character then
		onCharacterAdded(player, player.Character)
	end
end

Players.PlayerAdded:Connect(onPlayerAdded)
for _, player in Players:GetPlayers() do
	onPlayerAdded(player)
end
Players.PlayerRemoving:Connect(stopRegen)
```

- Connections to objects that get destroyed (the character, the humanoid) are cleaned up by `Destroy`; connections to services (`RunService`, `Players`, `ReplicatedStorage` remotes) are not, so they need an explicit owner and `Disconnect`.
- Calling `stopRegen` at the start of `onCharacterAdded` makes the handler safe even if `CharacterRemoving` is missed or a character is loaded twice.
- The original also yielded on `WaitForChild("Humanoid")` without using it; drop waits you do not need, since each one is a chance to stall forever.

# Test
```lua
local p = __makePlayer(1, "Runner")
__makeCharacter(p)
__makeCharacter(p)
__makeCharacter(p)
p:SetAttribute("Stamina", 50)
__frames(60, 1 / 60)
local stamina = p:GetAttribute("Stamina")
check("regen at single speed after respawns", math.abs(stamina - 60) < 0.01)
check("respawn refills", (function()
	__makeCharacter(p)
	return p:GetAttribute("Stamina") == 100
end)())
p:SetAttribute("Stamina", 10)
__removePlayer(p)
__frames(30, 1 / 60)
check("no regen after player leaves", p:GetAttribute("Stamina") == 10)
local q = __makePlayer(2, "Other")
__makeCharacter(q)
q:SetAttribute("Stamina", 0)
__frames(30, 1 / 60)
check("other players unaffected", math.abs(q:GetAttribute("Stamina") - 5) < 0.01)
```
