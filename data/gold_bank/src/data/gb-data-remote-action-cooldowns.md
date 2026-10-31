---
id: gb-data-remote-action-cooldowns
category: remote-security
topics: cooldown, abilities, RemoteEvent, server timing, per-action
source: original
---
# Request
My abilities (Dash 2s, Heal 10s, Shout 30s) have cooldowns only in the LocalScript, so an exploiter can dash constantly. How do I enforce the cooldowns on the server for several different actions without a pile of separate tables?

# Answer
One server module owns every cooldown: a config table of action names to seconds, and a per-player table of when each action was last used. The handler asks `try(player, action)` before doing anything; unknown actions are refused, and the remaining time comes back so the client can sync its UI.

```lua
--!strict
-- ModuleScript: ServerScriptService.Cooldowns
local Players = game:GetService("Players")

export type Cooldowns = {
	try: (player: Player, action: string) -> (boolean, number),
	reset: (player: Player, action: string) -> (),
}

local Cooldowns = {}

function Cooldowns.new(durations: { [string]: number }): Cooldowns
	local used: { [Player]: { [string]: number } } = {}

	Players.PlayerRemoving:Connect(function(player: Player)
		used[player] = nil
	end)

	-- Returns true and starts the cooldown, or false and the seconds left (math.huge for unknown actions).
	local function try(player: Player, action: string): (boolean, number)
		local duration = durations[action]
		if duration == nil then
			return false, math.huge
		end
		local mine = used[player]
		if mine == nil then
			mine = {}
			used[player] = mine
		end
		local now = os.clock()
		local last = mine[action]
		if last and now - last < duration then
			return false, duration - (now - last)
		end
		mine[action] = now
		return true, 0
	end

	-- For effects such as a cooldown-reset power-up; still decided by server code only.
	local function reset(player: Player, action: string)
		local mine = used[player]
		if mine then
			mine[action] = nil
		end
	end

	return { try = try, reset = reset }
end

return Cooldowns
```

Usage in the ability remote:

```lua
--!strict
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerScriptService = game:GetService("ServerScriptService")
local Cooldowns = require(ServerScriptService.Cooldowns)

local abilities = Cooldowns.new({ Dash = 2, Heal = 10, Shout = 30 })
local useAbility = ReplicatedStorage:WaitForChild("UseAbility") :: RemoteEvent

local function onUse(player: Player, actionArg: unknown)
	if type(actionArg) ~= "string" then
		return
	end
	local allowed, remaining = abilities.try(player, actionArg)
	if not allowed then
		useAbility:FireClient(player, actionArg, remaining)
		return
	end
	print(player.Name, "used", actionArg)
end

useAbility.OnServerEvent:Connect(onUse)
```

- Start the cooldown only when the action is accepted; if the ability then fails a later check (dead, stunned), call `reset` or let it stand, but decide that on the server.
- `os.clock()` is monotonic and unaffected by changes to the server's wall clock.
- Keep the client's cooldown UI as a prediction; the server's reply with `remaining` corrects it when they drift apart.

# Test
```lua
local cds = item.new({ Dash = 2, Heal = 10 })
local p = __makePlayer(1, "Caster")
check("first dash is allowed", cds.try(p, "Dash"))
local ok, left = cds.try(p, "Dash")
check("second dash is refused with time left", not ok and math.abs(left - 2) < 1e-6)
check("other actions have their own cooldown", cds.try(p, "Heal"))

__advance(2.1)
check("dash is ready after its duration", cds.try(p, "Dash"))
local healOk, healLeft = cds.try(p, "Heal")
check("heal is still cooling down", not healOk and healLeft > 7 and healLeft < 8)

local unknownOk, unknownLeft = cds.try(p, "Fly")
check("unknown actions are refused", not unknownOk and unknownLeft == math.huge)

cds.reset(p, "Heal")
check("reset makes the action available", cds.try(p, "Heal"))

local other = __makePlayer(2, "Other")
check("cooldowns are per player", cds.try(other, "Dash"))
```
