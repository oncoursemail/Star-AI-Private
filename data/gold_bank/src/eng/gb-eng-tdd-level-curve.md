---
id: gb-eng-tdd-level-curve
category: engineering-test-first
topics: test-first, level curve, xp, progression, pure module
source: original
test_block: 2
---
# Request
I want to do this test-first. I need a level curve module: level 1 starts at 0 XP, reaching level `n+1` from `n` costs `100 * n^1.5` XP rounded down, max level 50. Functions: total XP needed for a level, the level for a total XP amount, and progress (0 to 1) through the current level. Write the tests first, then the implementation.

# Answer
Tests first, as a plain spec script with a tiny runner (no framework needed); they pin down the edge cases before any code exists: level 1 at 0 XP, exact thresholds, one XP short, negative XP, and the cap. Then a module that precomputes the cumulative table once.

```lua
--!strict
-- Script: ServerScriptService.Tests.LevelCurveSpec (run in Studio; prints failures)
local LevelCurve = require(game:GetService("ReplicatedStorage").LevelCurve)

local failures = 0
local function test(name: string, fn: () -> ())
	local ok, err = pcall(fn)
	if not ok then
		failures += 1
		warn(`FAIL {name}: {err}`)
	end
end

test("level 1 needs no xp", function()
	assert(LevelCurve.totalXpFor(1) == 0)
end)
test("cost of each step follows the formula", function()
	assert(LevelCurve.totalXpFor(2) == 100)
	assert(LevelCurve.totalXpFor(3) == 100 + math.floor(100 * 2 ^ 1.5))
end)
test("exact threshold reaches the level, one short does not", function()
	local t = LevelCurve.totalXpFor(10)
	assert(LevelCurve.levelFor(t) == 10)
	assert(LevelCurve.levelFor(t - 1) == 9)
end)
test("negative and zero xp are level 1", function()
	assert(LevelCurve.levelFor(-50) == 1 and LevelCurve.levelFor(0) == 1)
end)
test("capped at max level", function()
	assert(LevelCurve.levelFor(10 ^ 12) == LevelCurve.MAX_LEVEL)
	assert(LevelCurve.progress(10 ^ 12) == 1)
end)
test("progress is the fraction through the current level", function()
	assert(LevelCurve.progress(50) == 0.5)
	assert(LevelCurve.progress(100) == 0)
end)

print(`LevelCurve spec: {failures} failure(s)`)
```

```lua
--!strict
-- ModuleScript: ReplicatedStorage.LevelCurve
local MAX_LEVEL = 50

local cumulative: { number } = { 0 } -- cumulative[n] = total xp needed to reach level n
for n = 1, MAX_LEVEL - 1 do
	cumulative[n + 1] = cumulative[n] + math.floor(100 * n ^ 1.5)
end

local LevelCurve = {}
LevelCurve.MAX_LEVEL = MAX_LEVEL

function LevelCurve.totalXpFor(level: number): number
	return cumulative[math.clamp(math.floor(level), 1, MAX_LEVEL)]
end

function LevelCurve.levelFor(xp: number): number
	-- binary search for the highest level whose threshold is <= xp
	local lo, hi = 1, MAX_LEVEL
	while lo < hi do
		local mid = (lo + hi + 1) // 2
		if cumulative[mid] <= xp then
			lo = mid
		else
			hi = mid - 1
		end
	end
	return lo
end

function LevelCurve.progress(xp: number): number
	local level = LevelCurve.levelFor(xp)
	if level >= MAX_LEVEL then
		return 1
	end
	local start, finish = cumulative[level], cumulative[level + 1]
	return math.clamp((xp - start) / (finish - start), 0, 1)
end

return LevelCurve
```

- Writing the "one XP short" and "negative XP" tests first is what forced the binary search to use `<=` and to start at level 1; those are the cases that usually break.
- The table is built once at require time, so `levelFor` is a handful of comparisons and safe to call every time XP changes.
- Changing the curve later is a one-line edit, and the spec immediately shows which expectations moved.

# Test
```lua
check("level 1 needs no xp", item.totalXpFor(1) == 0)
check("step costs", item.totalXpFor(2) == 100 and item.totalXpFor(3) == 100 + math.floor(100 * 2 ^ 1.5))
local t = item.totalXpFor(10)
check("exact threshold and one short", item.levelFor(t) == 10 and item.levelFor(t - 1) == 9)
check("negative and zero xp", item.levelFor(-50) == 1 and item.levelFor(0) == 1)
check("cap", item.levelFor(10 ^ 12) == 50 and item.progress(10 ^ 12) == 1)
check("progress fraction", item.progress(50) == 0.5 and item.progress(100) == 0)
check("level clamps out of range", item.totalXpFor(0) == 0 and item.totalXpFor(99) == item.totalXpFor(50))
```
