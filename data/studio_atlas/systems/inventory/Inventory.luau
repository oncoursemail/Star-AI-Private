--!strict
-- Server-side inventory: stacking, slot capacity, atomic add/remove. The client never sends counts or ids that
-- are trusted; it asks, the server decides with this object.

export type ItemDef = { maxStack: number }
export type Slot = { id: string, count: number }
export type Config = {
	capacity: number, -- number of slots
	items: { [string]: ItemDef },
	onChanged: (() -> ())?, -- replicate to the owner here
}
export type Inventory = {
	CanAdd: (self: Inventory, id: string, count: number) -> (boolean, string?),
	Add: (self: Inventory, id: string, count: number) -> (boolean, string?), -- all or nothing
	Remove: (self: Inventory, id: string, count: number) -> (boolean, string?), -- all or nothing
	Count: (self: Inventory, id: string) -> number,
	Has: (self: Inventory, id: string, count: number) -> boolean,
	Serialize: (self: Inventory) -> { Slot }, -- a copy, safe to put in a profile
}

local Inventories = {}

local function validCount(count: number): boolean
	return type(count) == "number" and count >= 1 and count % 1 == 0 and count < 2 ^ 31
end

-- saved comes from a profile: drop unknown items, clamp stacks, keep at most `capacity` slots.
function Inventories.new(cfg: Config, saved: { Slot }?): Inventory
	local slots: { Slot } = {}
	for _, s in saved or {} do
		local def = cfg.items[s.id]
		if def and validCount(s.count) and #slots < cfg.capacity then
			table.insert(slots, { id = s.id, count = math.min(s.count, def.maxStack) })
		end
	end
	local inv = {} :: Inventory

	local function changed()
		if cfg.onChanged then
			cfg.onChanged()
		end
	end

	function inv.Count(_self, id)
		local total = 0
		for _, s in slots do
			if s.id == id then
				total += s.count
			end
		end
		return total
	end

	function inv.Has(self, id, count)
		return self:Count(id) >= count
	end

	function inv.CanAdd(_self, id, count)
		local def = cfg.items[id]
		if def == nil then
			return false, "unknown item"
		end
		if not validCount(count) then
			return false, "bad count"
		end
		local room = (cfg.capacity - #slots) * def.maxStack
		for _, s in slots do
			if s.id == id then
				room += def.maxStack - s.count
			end
		end
		if count > room then
			return false, "inventory full"
		end
		return true, nil
	end

	function inv.Add(self, id, count)
		local ok, why = self:CanAdd(id, count)
		if not ok then
			return false, why
		end
		local max = cfg.items[id].maxStack
		local left = count
		for _, s in slots do -- top up partial stacks first
			if s.id == id and s.count < max and left > 0 then
				local put = math.min(max - s.count, left)
				s.count += put
				left -= put
			end
		end
		while left > 0 do
			local put = math.min(max, left)
			table.insert(slots, { id = id, count = put })
			left -= put
		end
		changed()
		return true, nil
	end

	function inv.Remove(self, id, count)
		if not validCount(count) then
			return false, "bad count"
		end
		if self:Count(id) < count then
			return false, "not enough"
		end
		local left = count
		for i = #slots, 1, -1 do -- take from the newest stacks first
			local s = slots[i]
			if s.id == id and left > 0 then
				local take = math.min(s.count, left)
				s.count -= take
				left -= take
				if s.count == 0 then
					table.remove(slots, i)
				end
			end
		end
		changed()
		return true, nil
	end

	function inv.Serialize(_self)
		local out = {}
		for _, s in slots do
			table.insert(out, { id = s.id, count = s.count })
		end
		return out
	end

	return inv
end

return Inventories
