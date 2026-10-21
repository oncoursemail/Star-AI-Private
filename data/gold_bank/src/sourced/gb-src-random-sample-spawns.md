---
id: gb-src-random-sample-spawns
category: engineering-algorithm
topics: Random, Fisher-Yates, sampling without replacement, spawn points, shuffle, seeds
source: adapted
source_id: rbxutil
source_path: modules/table-util/init.luau
source_commit: 31f9120fca021e3dec275b42bc7047d626962082
---
# Request
At round start I need to pick 4 different spawn points out of ~30 for the 4 teams. I'm doing `spawns[math.random(#spawns)]` in a loop and re-rolling duplicates, which feels hacky. Also I'd like the same seed to give the same picks when I'm debugging.

# Answer
Do a partial Fisher-Yates shuffle on a copy: for each of the first `k` slots, swap in a random element from the remaining range. That gives `k` distinct picks in O(k) swaps with no re-rolls. Pass a `Random` object so a fixed seed reproduces the result.

```lua
--!strict
local Sample = {}

function Sample.pick<T>(items: { T }, count: number, rng: Random?): { T }
	local n = #items
	local k = math.clamp(count, 0, n)
	local random = rng or Random.new()
	local pool = table.clone(items)
	local result = table.create(k)
	for i = 1, k do
		local j = random:NextInteger(i, n)
		pool[i], pool[j] = pool[j], pool[i]
		result[i] = pool[i]
	end
	return result
end

return Sample
```

Usage: `local teamSpawns = Sample.pick(workspace.Spawns:GetChildren(), 4, Random.new(roundSeed))`.

- Each pick comes from the not-yet-picked range `i..n`, so duplicates are impossible and every subset is equally likely.
- The input array is copied, so the original spawn list keeps its order.
- Asking for more than exist returns all of them, shuffled, instead of erroring.

# Test
```lua
local spawns = {}
for i = 1, 30 do
	spawns[i] = "Spawn" .. i
end
local picks = item.pick(spawns, 4, Random.new(42))
local seen = {}
local unique = true
for _, s in picks do
	if seen[s] then
		unique = false
	end
	seen[s] = true
end
check("four distinct picks", #picks == 4 and unique)
local again = item.pick(spawns, 4, Random.new(42))
check("same seed, same picks", again[1] == picks[1] and again[4] == picks[4])
check("input order untouched", spawns[1] == "Spawn1" and spawns[30] == "Spawn30")
check("count clamped to size", #item.pick({ "a", "b" }, 5) == 2 and #item.pick({}, 3) == 0)
```
