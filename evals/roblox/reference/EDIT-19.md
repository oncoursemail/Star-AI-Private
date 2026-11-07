Reference fix.

```lua
-- Backpack: what a player carries into a paintball round. Weight limits how much gear they can take.
local Backpack = {}
Backpack.__index = Backpack

local WEIGHTS = {
	paintball_pod = 0.5,
	grenade = 2,
	medkit = 3,
	shield = 6,
}

function Backpack.new(maxWeight)
	local self = setmetatable({}, Backpack)
	self.maxWeight = maxWeight or 20
	self.items = {}
	return self
end

function Backpack.weightOf(item)
	return WEIGHTS[item] or 1
end

function Backpack:count(item)
	return self.items[item] or 0
end

function Backpack:totalWeight()
	local total = 0
	for item, count in pairs(self.items) do
		total += Backpack.weightOf(item) * count
	end
	return total
end

function Backpack:add(item, count)
	count = count or 1
	if self:totalWeight() + Backpack.weightOf(item) * count > self.maxWeight then
		return false
	end
	self.items[item] = self:count(item) + count
	return true
end

function Backpack:remove(item, count)
	count = count or 1
	if self:count(item) < count then
		return false
	end
	local left = self:count(item) - count
	self.items[item] = if left > 0 then left else nil
	return true
end

function Backpack:freeWeight()
	return self.maxWeight - self:totalWeight()
end

function Backpack:list()
	local out = {}
	for item, count in pairs(self.items) do
		table.insert(out, { item = item, count = count })
	end
	table.sort(out, function(a, b)
		return a.item < b.item
	end)
	return out
end

return Backpack
```
