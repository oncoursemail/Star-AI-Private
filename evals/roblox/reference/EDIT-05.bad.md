The original code, unchanged.

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
	local last = lastUsed[ability]
	if last == nil then
		return true
	end
	return Cooldowns.clock() - last >= DURATIONS[ability]
end

function Cooldowns.use(player, ability)
	if not Cooldowns.ready(player, ability) then
		return false
	end
	lastUsed[ability] = Cooldowns.clock()
	return true
end

function Cooldowns.remaining(player, ability)
	local last = lastUsed[ability]
	if last == nil then
		return 0
	end
	return math.max(0, DURATIONS[ability] - (Cooldowns.clock() - last))
end

function Cooldowns.clear(player)
	lastUsed = {}
end

return Cooldowns
```
