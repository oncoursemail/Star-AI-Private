---
id: gb-eng-weighted-random-picker
category: engineering-algorithm
topics: weighted random, loot table, cumulative weights, binary search, Random
source: original
---
# Request
My loot code does `math.random(1, 100)` and a chain of `if roll <= 60 ... elseif roll <= 85 ...`, and every time we change a drop rate someone breaks the thresholds. Also some weights are decimals like 0.5. How do I write a weighted picker that is correct for any weights?

# Answer
Precompute cumulative weights once, draw a uniform number in `[0, total)` with a `Random` object, and binary-search the first cumulative value greater than the draw. Weights can be any positive numbers and no thresholds are written by hand.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.WeightedPicker
export type Entry<T> = { value: T, weight: number }
export type Picker<T> = { values: { T }, cumulative: { number }, total: number, rng: Random }

local WeightedPicker = {}

function WeightedPicker.new<T>(entries: { Entry<T> }, rng: Random?): Picker<T>
	local values: { T } = {}
	local cumulative: { number } = {}
	local total = 0
	for _, entry in entries do
		if entry.weight ~= entry.weight or entry.weight < 0 then
			error("weights must be non-negative numbers", 2)
		end
		if entry.weight > 0 then
			total += entry.weight
			table.insert(values, entry.value)
			table.insert(cumulative, total)
		end
	end
	assert(total > 0, "at least one entry needs a positive weight")
	return { values = values, cumulative = cumulative, total = total, rng = rng or Random.new() }
end

function WeightedPicker.pickWith<T>(picker: Picker<T>, roll: number): T
	-- roll is in [0, total); find the first cumulative weight strictly greater than it
	local lo, hi = 1, #picker.cumulative
	while lo < hi do
		local mid = (lo + hi) // 2
		if picker.cumulative[mid] > roll then
			hi = mid
		else
			lo = mid + 1
		end
	end
	return picker.values[lo]
end

function WeightedPicker.pick<T>(picker: Picker<T>): T
	return WeightedPicker.pickWith(picker, picker.rng:NextNumber(0, picker.total))
end

return WeightedPicker
```

- Usage: `local loot = WeightedPicker.new({ { value = "Common", weight = 60 }, { value = "Rare", weight = 25 }, { value = "Epic", weight = 0.5 } })` then `WeightedPicker.pick(loot)`; the weights do not need to add up to 100.
- `Random:NextNumber(0, total)` draws a float, so decimal weights are exact; `math.random(1, 100)` can only express whole percentages.
- Roll on the server for anything with value; pass a seeded `Random.new(seed)` when you need reproducible results (tests, replays).

# Test
```lua
local picker = item.new({
	{ value = "a", weight = 1 },
	{ value = "zero", weight = 0 },
	{ value = "b", weight = 2 },
	{ value = "c", weight = 0.5 },
}, Random.new(7))
check("roll boundaries", item.pickWith(picker, 0) == "a" and item.pickWith(picker, 0.999) == "a" and item.pickWith(picker, 1) == "b")
check("last bucket", item.pickWith(picker, 3.2) == "c" and item.pickWith(picker, 2.999) == "b")
local counts = { a = 0, b = 0, c = 0, zero = 0 }
for _ = 1, 7000 do
	local v = item.pick(picker)
	counts[v] += 1
end
check("zero weight never picked", counts.zero == 0)
check("distribution roughly proportional", math.abs(counts.a / 7000 - 1 / 3.5) < 0.03 and math.abs(counts.b / 7000 - 2 / 3.5) < 0.03)
check("negative weight rejected", not pcall(item.new, { { value = "x", weight = -1 } }))
check("all zero rejected", not pcall(item.new, { { value = "x", weight = 0 } }))
```
