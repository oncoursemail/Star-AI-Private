The original code, unchanged.

```lua
-- Inventory: paint grenades, health packs and power-ups a player carries between rounds.
local Inventory = {}
Inventory.__index = Inventory

local MAX_STACK = 99

function Inventory.new(owner)
	local self = setmetatable({}, Inventory)
	self.owner = owner
	self.items = {}
	self.changed = {}
	return self
end

function Inventory:OnChanged(fn)
	table.insert(self.changed, fn)
end

function Inventory:_notify(item)
	for _, fn in ipairs(self.changed) do
		fn(item, self:GetCount(item))
	end
end

function Inventory:GetCount(item)
	return self.items[item] or 0
end

function Inventory:HasItem(item, amount)
	return self:GetCount(item) >= (amount or 1)
end

function Inventory:AddItem(item, amount)
	local total = math.min(MAX_STACK, self:GetCount(item) + amount)
	self.items[item] = total
	self:_notify(item)
	return total
end

function Inventory:RemoveItem(item, amount)
	local left = self:GetCount(item) - amount
	if left <= 0 then
		self.items[item] = nil
	else
		self.items[item] = left
	end
	self:_notify(item)
	return true
end

function Inventory:Snapshot()
	local copy = {}
	for item in pairs(self.items) do
		copy[item] = self:GetCount(item)
	end
	return copy
end

function Inventory:Clear()
	for item in pairs(self.items) do
		self.items[item] = nil
		self:_notify(item)
	end
end

return Inventory
```
