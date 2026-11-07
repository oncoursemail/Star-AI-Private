Reference fix.

```lua
-- Cooldowns: ability cooldowns for the paintball abilities (dash, shield, grenade). Server only.
local Cooldowns = {}

local DURATIONS = {
	dash = 3,
	shield = 12,
	grenade = 8,
}

local lastUsed = {}

-- Replaced in tests; os.clock on the server.
Cooldowns.clock = os.clock

function Cooldowns.duration(ability)
	return DURATIONS[ability]
end

function Cooldowns.ready(player, ability)
	if DURATIONS[ability] == nil then
		return false
	end
	local last = lastUsed[player] and lastUsed[player][ability]
	if last == nil then
		return true
	end
	return Cooldowns.clock() - last >= DURATIONS[ability]
end

function Cooldowns.use(player, ability)
	if not Cooldowns.ready(player, ability) then
		return false
	end
	lastUsed[player] = lastUsed[player] or {}
	lastUsed[player][ability] = Cooldowns.clock()
	return true
end

function Cooldowns.remaining(player, ability)
	local last = lastUsed[player] and lastUsed[player][ability]
	if last == nil or DURATIONS[ability] == nil then
		return 0
	end
	return math.max(0, DURATIONS[ability] - (Cooldowns.clock() - last))
end

function Cooldowns.clear(player)
	lastUsed[player] = nil
end

return Cooldowns
```
