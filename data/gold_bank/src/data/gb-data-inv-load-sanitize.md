---
id: gb-data-inv-load-sanitize
category: server-authoritative-inventory
topics: inventory, save format, load validation, removed items, DataStore
source: original
---
# Request
I removed some items from my game and changed stack sizes, and now old saves have items that don't exist and stacks of 500 arrows when the max is 99. What should I do when loading an inventory from the DataStore?

# Answer
Never trust saved data more than client data: it was written by an older version of your code and may have been corrupted by a bug. Save a compact list of `{ id, count }` pairs and rebuild the inventory on load against the current item table: drop unknown ids (or convert them), merge duplicates, split oversized stacks and stop at the slot limit, reporting what changed.

```lua
--!strict
-- ModuleScript: ServerScriptService.InventoryCodec
export type Slot = { id: string, count: number }

local MAX_STACK: { [string]: number } = { Arrow = 99, Wood = 99, Sword = 1, Shield = 1, Bow = 1 }
local RENAMED: { [string]: string } = { OldBow = "Bow" } -- ids that became other items

local InventoryCodec = {}

function InventoryCodec.encode(slots: { [number]: Slot? }, size: number): { { any } }
	local out: { { any } } = {}
	for i = 1, size do
		local slot = slots[i]
		if slot then
			table.insert(out, { slot.id, slot.count })
		end
	end
	return out
end

-- Returns clean slots and a list of notes about anything that was dropped or changed.
function InventoryCodec.decode(saved: unknown, size: number): ({ Slot }, { string })
	local notes: { string } = {}
	local totals: { [string]: number } = {}
	local order: { string } = {}
	if type(saved) == "table" then
		for _, pair in saved :: { any } do
			local id, count = if type(pair) == "table" then pair[1] else nil, if type(pair) == "table" then pair[2] else nil
			if type(id) == "string" and RENAMED[id] then
				id = RENAMED[id]
			end
			if type(id) ~= "string" or MAX_STACK[id] == nil then
				table.insert(notes, "dropped unknown item " .. tostring(id))
			elseif type(count) ~= "number" or count ~= count or count < 1 then
				table.insert(notes, "dropped bad count for " .. id)
			else
				if totals[id] == nil then
					table.insert(order, id)
				end
				totals[id] = (totals[id] or 0) + math.floor(count)
			end
		end
	end
	local slots: { Slot } = {}
	for _, id in order do
		local left = totals[id]
		while left > 0 do
			if #slots >= size then
				table.insert(notes, "no room for " .. left .. " " .. id)
				break
			end
			local take = math.min(left, MAX_STACK[id])
			table.insert(slots, { id = id, count = take })
			left -= take
		end
	end
	return slots, notes
end

return InventoryCodec
```

- Log the notes with the UserId once per load; a sudden burst of "dropped unknown item" lines is how you catch a bad deploy before players notice.
- `RENAMED` lets you retire an item id without deleting players' copies.
- When something will not fit, you can mail the overflow to the player instead of dropping it; the notes tell you exactly what was cut.

# Test
```lua
local saved = { { "Arrow", 500 }, { "Wood", 10 }, { "Arrow", 20 }, { "LaserGun", 1 }, { "OldBow", 1 }, { "Wood", 0 / 0 }, "junk" }
local slots, notes = item.decode(saved, 10)
check("duplicate arrows merge and split into legal stacks", slots[1].id == "Arrow" and slots[1].count == 99
	and slots[6].id == "Arrow" and slots[6].count == 25)
check("renamed items are converted", slots[8].id == "Bow")
check("unknown items, bad counts and junk entries are dropped with notes", #notes == 3)

local tight, tightNotes = item.decode({ { "Sword", 3 } }, 2)
check("slot limit is enforced", #tight == 2 and #tightNotes == 1)

local encoded = item.encode({ { id = "Wood", count = 5 }, nil, { id = "Sword", count = 1 } }, 3)
check("encode writes compact pairs", #encoded == 2 and encoded[2][1] == "Sword")
local store = game:GetService("DataStoreService"):GetDataStore("Inv")
check("encoded inventories are valid DataStore values", pcall(function()
	store:SetAsync("k", encoded)
end))
local back = item.decode(store:GetAsync("k"), 3)
check("round trip keeps the items", #back == 2 and back[1].count == 5)
check("nil saves decode to an empty inventory", #item.decode(nil, 5) == 0)
```
