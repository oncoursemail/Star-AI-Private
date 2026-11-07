---
id: gb-eng-tdd-inventory-stacking
category: engineering-test-first
topics: test-first, inventory, stacking, slots, leftover
source: original
test_block: 2
---
# Request
I'd like to write tests before the code for my inventory math. Inventory has a fixed number of slots; each slot holds one item id with a count up to that item's max stack. Adding items should top up existing stacks of the same id first, then fill empty slots, and return how many did not fit. Removing should take from the last stacks first and fail without changing anything if there aren't enough.

# Answer
The spec fixes the rules as examples: top-up before new slots, partial fit returns the leftover, removal is all-or-nothing and drains later stacks first. The implementation is pure data in, data out, so the same module serves the server and a client-side preview.

```lua
--!strict
-- Script: ServerScriptService.Tests.StackingSpec
local Stacking = require(game:GetService("ReplicatedStorage").Stacking)

local failures = 0
local function test(name: string, fn: () -> ())
	local ok, err = pcall(fn)
	if not ok then
		failures += 1
		warn(`FAIL {name}: {err}`)
	end
end

local MAX = { Wood = 50, Sword = 1 }

test("tops up existing stacks before using empty slots", function()
	local inv = Stacking.new(3)
	inv.slots[2] = { id = "Wood", count = 45 }
	assert(Stacking.add(inv, "Wood", 10, MAX) == 0)
	assert(inv.slots[2].count == 50 and inv.slots[1] ~= nil and inv.slots[1].count == 5)
end)
test("returns what did not fit", function()
	local inv = Stacking.new(2)
	assert(Stacking.add(inv, "Sword", 3, MAX) == 1)
end)
test("remove is all or nothing", function()
	local inv = Stacking.new(2)
	Stacking.add(inv, "Wood", 30, MAX)
	assert(not Stacking.take(inv, "Wood", 31))
	assert(Stacking.count(inv, "Wood") == 30)
end)
test("remove drains later stacks first and frees empty slots", function()
	local inv = Stacking.new(3)
	Stacking.add(inv, "Wood", 70, MAX)
	assert(Stacking.take(inv, "Wood", 25))
	assert(inv.slots[1].count == 45 and inv.slots[2] == nil)
end)

print(`Stacking spec: {failures} failure(s)`)
```

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Stacking
export type Stack = { id: string, count: number }
export type Inventory = { size: number, slots: { [number]: Stack? } }

local Stacking = {}

function Stacking.new(size: number): Inventory
	return { size = size, slots = {} }
end

function Stacking.count(inv: Inventory, id: string): number
	local total = 0
	for i = 1, inv.size do
		local stack = inv.slots[i]
		if stack and stack.id == id then
			total += stack.count
		end
	end
	return total
end

function Stacking.add(inv: Inventory, id: string, amount: number, maxStacks: { [string]: number }): number
	local maxStack = maxStacks[id] or 1
	local left = math.max(0, math.floor(amount))
	for i = 1, inv.size do -- pass 1: top up existing stacks
		local stack = inv.slots[i]
		if left > 0 and stack and stack.id == id and stack.count < maxStack then
			local moved = math.min(left, maxStack - stack.count)
			stack.count += moved
			left -= moved
		end
	end
	for i = 1, inv.size do -- pass 2: empty slots
		if left > 0 and inv.slots[i] == nil then
			local moved = math.min(left, maxStack)
			inv.slots[i] = { id = id, count = moved }
			left -= moved
		end
	end
	return left
end

function Stacking.take(inv: Inventory, id: string, amount: number): boolean
	if amount % 1 ~= 0 or amount <= 0 or Stacking.count(inv, id) < amount then -- % 1 also rejects NaN and inf
		return false
	end
	local left = amount
	for i = inv.size, 1, -1 do
		local stack = inv.slots[i]
		if left > 0 and stack and stack.id == id then
			local taken = math.min(left, stack.count)
			stack.count -= taken
			left -= taken
			if stack.count == 0 then
				inv.slots[i] = nil
			end
		end
	end
	return true
end

return Stacking
```

- Counting first in `take` is what makes it all-or-nothing; without that check a failed craft could still eat half the materials.
- `add` floors and clamps its amount, and `take` refuses fractions, NaN and non-positive amounts, so no call can create fractional or negative stacks or "take" NaN items for free.
- On the server, call these only with server-side item ids and amounts; a client request names a recipe or a slot, never "add 999 Wood".

# Test
```lua
local MAX = { Wood = 50, Sword = 1 }
local inv = item.new(3)
inv.slots[2] = { id = "Wood", count = 45 }
check("top up first", item.add(inv, "Wood", 10, MAX) == 0 and inv.slots[2].count == 50 and inv.slots[1].count == 5)
local small = item.new(2)
check("leftover returned", item.add(small, "Sword", 3, MAX) == 1 and small.slots[1].count == 1 and small.slots[2].count == 1)
local inv2 = item.new(2)
item.add(inv2, "Wood", 30, MAX)
check("remove all or nothing", not item.take(inv2, "Wood", 31) and item.count(inv2, "Wood") == 30)
local inv3 = item.new(3)
item.add(inv3, "Wood", 70, MAX)
check("drains later stacks first", item.take(inv3, "Wood", 25) and inv3.slots[1].count == 45 and inv3.slots[2] == nil)
check("bad amounts", item.add(inv3, "Wood", -5, MAX) == 0 and not item.take(inv3, "Wood", 0) and item.count(inv3, "Wood") == 45)
check("fractional floored", item.add(inv3, "Wood", 2.7, MAX) == 0 and item.count(inv3, "Wood") == 47)
check("take refuses fractions and NaN", not item.take(inv3, "Wood", 0.5) and not item.take(inv3, "Wood", 0 / 0) and item.count(inv3, "Wood") == 47)
```
