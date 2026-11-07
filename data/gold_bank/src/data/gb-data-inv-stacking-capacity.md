---
id: gb-data-inv-stacking-capacity
category: server-authoritative-inventory
topics: inventory, stacking, slots, capacity, leftover
source: original
---
# Request
I need a server-side inventory with 20 slots where items stack up to a per-item limit (wood stacks to 99, swords don't stack). Adding should fill existing stacks first and tell me how many didn't fit. Can you write that module?

# Answer
Keep slots as an array of `{ id, count }` or `nil`, and read stack limits from a server item table. `add` tops up existing stacks of the same item, then opens empty slots, and returns the leftover instead of failing silently; `remove` refuses to take more than the player has.

```lua
--!strict
-- ModuleScript: ServerScriptService.Inventory
export type Slot = { id: string, count: number }
export type Inventory = { slots: { [number]: Slot? }, size: number }

local MAX_STACK: { [string]: number } = { Wood = 99, Stone = 99, Apple = 20, Sword = 1, Bow = 1 }

local Inventory = {}

function Inventory.new(size: number): Inventory
	return { slots = {}, size = size }
end

function Inventory.count(inv: Inventory, id: string): number
	local total = 0
	for i = 1, inv.size do
		local slot = inv.slots[i]
		if slot and slot.id == id then
			total += slot.count
		end
	end
	return total
end

-- Returns how many could NOT be added (0 when everything fit). Unknown ids add nothing.
function Inventory.add(inv: Inventory, id: string, amount: number): number
	local maxStack = MAX_STACK[id]
	if maxStack == nil or amount < 1 or amount % 1 ~= 0 then
		return amount
	end
	local left = amount
	for i = 1, inv.size do
		local slot = inv.slots[i]
		if left > 0 and slot and slot.id == id and slot.count < maxStack then
			local moved = math.min(left, maxStack - slot.count)
			slot.count += moved
			left -= moved
		end
	end
	for i = 1, inv.size do
		if left > 0 and inv.slots[i] == nil then
			local moved = math.min(left, maxStack)
			inv.slots[i] = { id = id, count = moved }
			left -= moved
		end
	end
	return left
end

-- Removes exactly `amount` or nothing at all. Takes from the last stacks first.
function Inventory.remove(inv: Inventory, id: string, amount: number): boolean
	if amount < 1 or amount % 1 ~= 0 or Inventory.count(inv, id) < amount then
		return false
	end
	local left = amount
	for i = inv.size, 1, -1 do
		local slot = inv.slots[i]
		if left > 0 and slot and slot.id == id then
			local taken = math.min(left, slot.count)
			slot.count -= taken
			left -= taken
			if slot.count == 0 then
				inv.slots[i] = nil
			end
		end
	end
	return true
end

return Inventory
```

- Returning the leftover lets the caller decide: drop it on the ground, mail it, or refuse a purchase before charging.
- `remove` checks the total first, so a partial removal can never happen.
- The inventory lives only on the server; send the client a copy of `slots` after each change for the UI.

# Test
```lua
local inv = item.new(3)
check("wood fills one stack", item.add(inv, "Wood", 50) == 0 and inv.slots[1].count == 50)
check("more wood tops up the stack then opens a new slot", item.add(inv, "Wood", 60) == 0
	and inv.slots[1].count == 99 and inv.slots[2].count == 11)
check("non-stacking items take one slot each and report leftovers", item.add(inv, "Sword", 2) == 1 and inv.slots[3].id == "Sword")
check("full inventory returns everything as leftover", item.add(inv, "Stone", 5) == 5)
check("unknown items and bad amounts add nothing", item.add(inv, "Nuke", 1) == 1 and item.add(inv, "Wood", 0.5) == 0.5)
check("count sums all stacks", item.count(inv, "Wood") == 110)

check("removing more than owned fails and changes nothing", not item.remove(inv, "Wood", 200) and item.count(inv, "Wood") == 110)
check("removing empties slots from the back", item.remove(inv, "Wood", 11) and inv.slots[2] == nil and inv.slots[1].count == 99)
check("negative and NaN removals are refused", not item.remove(inv, "Wood", -5) and not item.remove(inv, "Wood", 0 / 0))
```
