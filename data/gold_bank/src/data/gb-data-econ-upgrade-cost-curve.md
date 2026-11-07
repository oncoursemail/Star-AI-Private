---
id: gb-data-econ-upgrade-cost-curve
category: economy-simulation
topics: upgrade cost, exponential curve, bulk buy, geometric series, balancing
source: original
---
# Request
My tycoon upgrades cost `base * 1.15^level`. I want a "Buy Max" button that buys as many levels as the player can afford, but looping one level at a time is slow when people have billions of cash. Is there a formula for this?

# Answer
The cost of buying `n` levels starting at level `L` is a geometric series: `base * g^L * (g^n - 1) / (g - 1)`. Solving that for `n` gives the maximum affordable count directly with a logarithm. Round each level's cost to whole coins consistently, and verify the closed-form result against the exact sum so floating point never lets a player buy one level they cannot afford.

```lua
--!strict
-- ModuleScript: ServerScriptService.UpgradeCost
local UpgradeCost = {}

export type Curve = { base: number, growth: number, maxLevel: number }

function UpgradeCost.levelCost(curve: Curve, level: number): number
	return math.floor(curve.base * curve.growth ^ level)
end

-- Exact cost of n levels from `level`, summing the rounded per-level costs (n is small after maxAffordable).
function UpgradeCost.costOf(curve: Curve, level: number, n: number): number
	local total = 0
	for l = level, level + n - 1 do
		total += UpgradeCost.levelCost(curve, l)
	end
	return total
end

-- Largest n with costOf(level, n) <= cash, capped by maxLevel.
function UpgradeCost.maxAffordable(curve: Curve, level: number, cash: number): number
	local g = curve.growth
	local first = curve.base * g ^ level
	local estimate = math.floor(math.log(cash * (g - 1) / first + 1) / math.log(g))
	local n = math.clamp(estimate, 0, curve.maxLevel - level)
	-- the floors in levelCost make real costs slightly lower than the series; correct by a step or two
	while n > 0 and UpgradeCost.costOf(curve, level, n) > cash do
		n -= 1
	end
	while level + n < curve.maxLevel and UpgradeCost.costOf(curve, level, n + 1) <= cash do
		n += 1
	end
	return n
end

return UpgradeCost
```

The server's "buy max" handler computes `n = maxAffordable(...)`, then charges `costOf(curve, level, n)` and adds `n` levels, all from the player's server-side cash and level.

- A growth of 1.15 doubles the price about every 5 levels; with income that grows linearly per level, progress slows naturally, which is the curve doing its job as a sink.
- `maxLevel` keeps `costOf` loops short and stops numbers from running into floating point territory where whole coins stop being exact (above about 2^53).
- Running the correction loops after the estimate means the result is always exact, even when the estimate is off by one.

# Test
```lua
local curve = { base = 10, growth = 1.15, maxLevel = 500 }
check("level cost follows the curve", item.levelCost(curve, 0) == 10 and item.levelCost(curve, 10) == math.floor(10 * 1.15 ^ 10))
check("cost of several levels sums each level", item.costOf(curve, 0, 3) == 10 + 11 + 13)

local function bruteForce(level, cash)
	local n, spent = 0, 0
	while level + n < curve.maxLevel do
		local nextCost = item.levelCost(curve, level + n)
		if spent + nextCost > cash then
			break
		end
		spent += nextCost
		n += 1
	end
	return n
end
local allMatch = true
for _, case in { { 0, 0 }, { 0, 9 }, { 0, 10 }, { 0, 1000 }, { 25, 123456 }, { 100, 5e9 }, { 40, 77777 } } do
	if item.maxAffordable(curve, case[1], case[2]) ~= bruteForce(case[1], case[2]) then
		allMatch = false
	end
end
check("closed form matches buying one level at a time", allMatch)
local n = item.maxAffordable(curve, 0, 1e6)
check("the result is affordable and one more is not", item.costOf(curve, 0, n) <= 1e6 and item.costOf(curve, 0, n + 1) > 1e6)
check("max level caps the purchase", item.maxAffordable(curve, 498, 1e300) == 2)
```
