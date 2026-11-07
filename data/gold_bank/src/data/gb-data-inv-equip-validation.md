---
id: gb-data-inv-equip-validation
category: server-authoritative-inventory
topics: equip, inventory slots, level requirement, RemoteEvent, validation
source: original
---
# Request
My equip button sends `Equip:FireServer(slotIndex)`. How should the server check that request so players can't equip items they don't have, put a helmet in the weapon slot, or wear gear above their level?

# Answer
The server resolves everything from the slot index: it must be an integer in range, the slot must hold an item, the item's definition says which equipment slot it goes in and what level it needs. Equipping swaps with whatever was in that equipment slot, so items are never created or lost.

```lua
--!strict
-- ModuleScript: ServerScriptService.Equipment
export type ItemDef = { equipSlot: "Weapon" | "Head" | "Body"?, level: number }
export type PlayerState = {
	level: number,
	bag: { [number]: string? },          -- bag slot -> item id
	equipped: { [string]: string? },     -- equipment slot -> item id
	bagSize: number,
}
export type Result = "ok" | "bad slot" | "empty" | "not equippable" | "level"

local DEFS: { [string]: ItemDef } = {
	WoodSword = { equipSlot = "Weapon", level = 1 },
	DragonBlade = { equipSlot = "Weapon", level = 30 },
	IronHelm = { equipSlot = "Head", level = 5 },
	Apple = { equipSlot = nil, level = 1 },
}

local Equipment = {}

function Equipment.equip(state: PlayerState, slotArg: unknown): Result
	if type(slotArg) ~= "number" or slotArg % 1 ~= 0 or slotArg < 1 or slotArg > state.bagSize then
		return "bad slot"
	end
	local itemId = state.bag[slotArg]
	if itemId == nil then
		return "empty"
	end
	local def = DEFS[itemId]
	if def == nil or def.equipSlot == nil then
		return "not equippable"
	end
	if state.level < def.level then
		return "level"
	end
	local target = def.equipSlot
	-- swap: the previously equipped item (or nothing) goes back into the same bag slot
	state.bag[slotArg] = state.equipped[target]
	state.equipped[target] = itemId
	return "ok"
end

return Equipment
```

Hook it to the remote with the state your server already owns: `local result = Equipment.equip(states[player], slotArg)`, then update the character's visuals and send the new state (and the result for UI feedback) back to that client.

- The client never names an item id, only a bag slot, so it cannot equip something that is not in its bag.
- Swapping into the same bag slot keeps the item count constant, which is easy to reason about when auditing dupes.
- Unequip is the reverse: the equipment slot must be filled and the bag needs a free slot, or the request is refused.

# Test
```lua
local state = { level = 10, bagSize = 4, bag = { "WoodSword", "IronHelm", "DragonBlade", "Apple" }, equipped = {} }
check("equipping a weapon works", item.equip(state, 1) == "ok" and state.equipped.Weapon == "WoodSword" and state.bag[1] == nil)
check("head items go to the head slot", item.equip(state, 2) == "ok" and state.equipped.Head == "IronHelm")
check("level requirement is enforced", item.equip(state, 3) == "level" and state.bag[3] == "DragonBlade")
state.level = 30
check("equipping swaps with the current item", item.equip(state, 3) == "ok" and state.equipped.Weapon == "DragonBlade"
	and state.bag[3] == "WoodSword")
check("consumables cannot be equipped", item.equip(state, 4) == "not equippable")
check("empty slots are reported", item.equip(state, 1) == "empty")
check("out-of-range, fractional and NaN slots are refused", item.equip(state, 5) == "bad slot"
	and item.equip(state, 1.5) == "bad slot" and item.equip(state, 0 / 0) == "bad slot" and item.equip(state, "1") == "bad slot")
```
