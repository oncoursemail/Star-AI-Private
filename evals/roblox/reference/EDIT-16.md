Reference fix.

```lua
-- SpawnPicker: chooses where a respawning paintball player appears.
-- Positions are {x, y, z} tables; spawns = { { name = "A", position = {...}, blocked = false }, ... }
local SpawnPicker = {}

local function distance(a, b)
	local dx, dy, dz = a.x - b.x, a.y - b.y, a.z - b.z
	return math.sqrt(dx * dx + dy * dy + dz * dz)
end

-- Distance from `position` to the closest enemy (math.huge without enemies).
function SpawnPicker.nearestEnemy(position, enemies)
	local best = math.huge
	for _, enemy in ipairs(enemies) do
		local d = distance(position, enemy)
		if d < best then
			best = d
		end
	end
	return best
end

function SpawnPicker.pick(spawns, enemies)
	local best, bestDistance = nil, -1
	for _, spawn in ipairs(spawns) do
		if not spawn.blocked then
			local d = SpawnPicker.nearestEnemy(spawn.position, enemies)
			if d > bestDistance then
				best, bestDistance = spawn, d
			end
		end
	end
	return best
end

-- Spawns sorted from safest to most dangerous, for the debug overlay.
function SpawnPicker.ranked(spawns, enemies)
	local list = table.clone(spawns)
	table.sort(list, function(a, b)
		return SpawnPicker.nearestEnemy(a.position, enemies) > SpawnPicker.nearestEnemy(b.position, enemies)
	end)
	return list
end

function SpawnPicker.distance(a, b)
	return distance(a, b)
end

return SpawnPicker
```
