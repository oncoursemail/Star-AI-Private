---
id: gb-eng-tdd-damage-resistances
category: engineering-test-first
topics: test-first, damage formula, armor, resistances, balance
source: original
test_block: 2
---
# Request
Our designer gave me the damage rules and I want tests that encode them before I implement anything: final damage = base x (1 + attacker bonus) x (1 - resistance for that element), resistance capped at 75% (negative resistance means extra damage, floored at -100%), then flat armor is subtracted, but a hit always deals at least 1 unless the target is immune (resistance exactly 1 in the data). Result rounded to the nearest integer.

# Answer
The spec turns each sentence of the rules into a case, including the order of operations (percentages before flat armor), both caps, the minimum of 1 and the immunity exception. Then a small pure function.

```lua
--!strict
-- Script: ServerScriptService.Tests.DamageSpec
local Damage = require(game:GetService("ReplicatedStorage").Damage)

local failures = 0
local function test(name: string, fn: () -> ())
	local ok, err = pcall(fn)
	if not ok then
		failures += 1
		warn(`FAIL {name}: {err}`)
	end
end

test("bonus and resistance multiply, then armor subtracts", function()
	-- 40 x 1.5 x (1 - 0.25) = 45, minus 5 armor = 40
	assert(Damage.compute(40, 0.5, "fire", { resist = { fire = 0.25 }, armor = 5 }) == 40)
end)
test("resistance capped at 75 percent", function()
	assert(Damage.compute(100, 0, "ice", { resist = { ice = 0.9 }, armor = 0 }) == 25)
end)
test("negative resistance is a weakness, floored at -100 percent", function()
	assert(Damage.compute(10, 0, "fire", { resist = { fire = -0.5 }, armor = 0 }) == 15)
	assert(Damage.compute(10, 0, "fire", { resist = { fire = -3 }, armor = 0 }) == 20)
end)
test("armor never reduces a hit below 1", function()
	assert(Damage.compute(5, 0, "physical", { resist = {}, armor = 50 }) == 1)
end)
test("immunity deals 0", function()
	assert(Damage.compute(500, 2, "poison", { resist = { poison = 1 }, armor = 0 }) == 0)
end)

print(`Damage spec: {failures} failure(s)`)
```

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Damage
export type Defender = { resist: { [string]: number }, armor: number }

local MAX_RESIST = 0.75
local MIN_RESIST = -1

local Damage = {}

function Damage.compute(base: number, attackerBonus: number, element: string, target: Defender): number
	local resist = target.resist[element] or 0
	if resist == 1 then
		return 0 -- immunity is a data flag, not a big resistance number
	end
	local scaled = base * (1 + math.max(attackerBonus, -1)) * (1 - math.clamp(resist, MIN_RESIST, MAX_RESIST))
	local afterArmor = scaled - math.max(0, target.armor)
	return math.max(1, math.floor(afterArmor + 0.5))
end

return Damage
```

- The worked example in the first test's comment is the designer's own sentence turned into numbers; when the rules change, update the numbers there first.
- Treating `resist == 1` as immunity (before the cap) keeps the 75% cap meaningful for gear while still allowing immune bosses.
- Clamp inputs that come from data or upgrades (bonus not below -100%, armor not negative) so a typo cannot create healing hits.

# Test
```lua
check("order of operations", item.compute(40, 0.5, "fire", { resist = { fire = 0.25 }, armor = 5 }) == 40)
check("resist cap", item.compute(100, 0, "ice", { resist = { ice = 0.9 }, armor = 0 }) == 25)
check("weakness", item.compute(10, 0, "fire", { resist = { fire = -0.5 }, armor = 0 }) == 15)
check("weakness floor", item.compute(10, 0, "fire", { resist = { fire = -3 }, armor = 0 }) == 20)
check("minimum one", item.compute(5, 0, "physical", { resist = {}, armor = 50 }) == 1)
check("immune", item.compute(500, 2, "poison", { resist = { poison = 1 }, armor = 0 }) == 0)
check("negative armor ignored", item.compute(10, 0, "physical", { resist = {}, armor = -20 }) == 10)
check("rounding to nearest", item.compute(10, 0.05, "physical", { resist = {}, armor = 0 }) == 11)
```
