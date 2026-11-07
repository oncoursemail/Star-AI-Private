---
id: gb-eng-debug-script-timeout-spawn-search
category: engineering-debugging
topics: script timeout, runaway loop, repeat until, bounded attempts, spawn points
source: original
---
# Request
Sometimes the whole server freezes for a few seconds and then I get "Script timeout: exhausted allowed execution time" from this function that picks a random free spawn spot for a pickup. It's fine most of the time.

```lua
local function findSpot()
	local pos
	repeat
		pos = Vector3.new(math.random(-100, 100), 5, math.random(-100, 100))
	until not isOccupied(pos)
	return pos
end
```

# Answer
The `repeat` loop has no upper bound and never yields. When the area is nearly full (late in a round, or when every candidate is blocked) no free spot exists, so the loop spins until the engine kills the script, freezing the server meanwhile. Bound the attempts, return nil when none is found, and let the caller decide (skip this spawn, retry later).

```lua
--!strict
-- ModuleScript: ServerScriptService.SpotFinder
local SpotFinder = {}

export type Options = {
	halfSize: number,
	height: number,
	minSpacing: number,
	maxAttempts: number?,
	rng: Random?,
}

function SpotFinder.find(occupied: { Vector3 }, options: Options): Vector3?
	local rng = options.rng or Random.new()
	local attempts = options.maxAttempts or 30
	local spacingSq = options.minSpacing * options.minSpacing
	for _ = 1, attempts do
		local candidate = Vector3.new(
			rng:NextNumber(-options.halfSize, options.halfSize),
			options.height,
			rng:NextNumber(-options.halfSize, options.halfSize)
		)
		local free = true
		for _, other in occupied do
			local d = candidate - other
			if d.X * d.X + d.Z * d.Z < spacingSq then
				free = false
				break
			end
		end
		if free then
			return candidate
		end
	end
	return nil
end

return SpotFinder
```

- 30 attempts costs at most 30 x (number of pickups) distance checks, a fraction of a millisecond, and the chance of missing a free spot when the map is half full is about 1 in a billion.
- A loop that waits for a condition must either be bounded or yield (`task.wait`) each iteration; a loop that computes something must be bounded. A `repeat ... until` over random draws is neither.
- Caller: `local spot = SpotFinder.find(positions, { halfSize = 100, height = 5, minSpacing = 8 }); if spot then spawnPickup(spot) end`.

# Test
```lua
local spot = item.find({}, { halfSize = 50, height = 5, minSpacing = 4, rng = Random.new(2) })
check("empty map finds a spot", spot ~= nil and spot.Y == 5 and math.abs(spot.X) <= 50 and math.abs(spot.Z) <= 50)
local crowded = {}
for x = -10, 10, 2 do
	for z = -10, 10, 2 do
		table.insert(crowded, Vector3.new(x, 5, z))
	end
end
local start = os.clock()
local none = item.find(crowded, { halfSize = 10, height = 5, minSpacing = 5, maxAttempts = 50, rng = Random.new(3) })
check("full map returns nil instead of hanging", none == nil)
local some = item.find({ Vector3.new(0, 5, 0) }, { halfSize = 20, height = 5, minSpacing = 6, rng = Random.new(4) })
check("result respects spacing", some ~= nil and Vector3.new(some.X, 0, some.Z).Magnitude >= 6)
check("virtual clock untouched (no yields)", os.clock() == start)
```
