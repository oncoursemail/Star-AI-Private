---
id: gb-data-inv-slot-move-merge
category: server-authoritative-inventory
topics: inventory, drag and drop, move slot, merge stacks, validation
source: original
---
# Request
My inventory UI supports drag and drop between slots. The client fires `MoveSlot:FireServer(from, to)`. What should the server do so moving, swapping and merging stacks can't be abused?

# Answer
Both indices must be integers inside the inventory and different from each other. If the target holds the same item, merge up to the stack limit and leave the rest in the source; otherwise swap the two slots. Nothing else changes, so the total count of every item is preserved by construction.

```lua
--!strict
-- ModuleScript: ServerScriptService.SlotMove
export type Slot = { id: string, count: number }
export type Inventory = { slots: { [number]: Slot? }, size: number }

local MAX_STACK: { [string]: number } = { Wood = 99, Arrow = 50, Sword = 1 }

local SlotMove = {}

local function validIndex(inv: Inventory, value: unknown): number?
	if type(value) == "number" and value % 1 == 0 and value >= 1 and value <= inv.size then
		return value
	end
	return nil
end

function SlotMove.move(inv: Inventory, fromArg: unknown, toArg: unknown): boolean
	local from, to = validIndex(inv, fromArg), validIndex(inv, toArg)
	if from == nil or to == nil or from == to then
		return false
	end
	local source = inv.slots[from]
	if source == nil then
		return false
	end
	local target = inv.slots[to]
	if target and target.id == source.id then
		local limit = MAX_STACK[source.id] or 1
		local moved = math.min(source.count, limit - target.count)
		if moved <= 0 then
			return false -- target stack already full
		end
		target.count += moved
		source.count -= moved
		if source.count == 0 then
			inv.slots[from] = nil
		end
		return true
	end
	inv.slots[from], inv.slots[to] = target, source
	return true
end

return SlotMove
```

Wire it to the remote with a short per-player rate limit (drag and drop is a few requests per second at most), then send the updated slots back to the client to replace its predicted state.

- The client's drag preview is only a prediction; if the server refuses, the UI snaps back when the authoritative slots arrive.
- A full target stack returns `false` rather than swapping, matching what players expect when dropping wood onto a full wood stack.
- Splitting a stack is a separate request with its own count validation (integer, 1 to count - 1, empty target).

# Test
```lua
local inv = { size = 4, slots = { { id = "Wood", count = 60 }, { id = "Wood", count = 70 }, { id = "Sword", count = 1 } } }
check("merging fills the target up to the stack limit", item.move(inv, 1, 2) and inv.slots[2].count == 99 and inv.slots[1].count == 31)
check("merging into a full stack is refused", not item.move(inv, 1, 2) and inv.slots[1].count == 31)
check("different items swap", item.move(inv, 1, 3) and inv.slots[1].id == "Sword" and inv.slots[3].id == "Wood")
check("moving into an empty slot works", item.move(inv, 3, 4) and inv.slots[3] == nil and inv.slots[4].count == 31)
check("moving from an empty slot fails", not item.move(inv, 3, 1))
check("out-of-range, same-slot, fractional and NaN indices are refused", not item.move(inv, 1, 5) and not item.move(inv, 1, 1)
	and not item.move(inv, 1.5, 2) and not item.move(inv, 0 / 0, 2) and not item.move(inv, "1", 2))
local total = 0
for i = 1, inv.size do
	local slot = inv.slots[i]
	if slot and slot.id == "Wood" then
		total += slot.count
	end
end
check("wood total is unchanged by all the moves", total == 130)
```
