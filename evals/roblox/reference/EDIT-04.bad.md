The original code, unchanged.

```lua
-- SplatPool: reuses paint splat decals instead of creating a new one for every hit.
local SplatPool = {}
SplatPool.__index = SplatPool

function SplatPool.new(create, maxSize)
	local self = setmetatable({}, SplatPool)
	self.create = create
	self.maxSize = maxSize or 50
	self.free = {}
	self.active = {}
	self.created = 0
	return self
end

function SplatPool:acquire()
	local splat = table.remove(self.free)
	if splat == nil then
		splat = self.create()
		self.created += 1
	end
	self.active[splat] = true
	return splat
end

function SplatPool:release(splat)
	self.active[splat] = nil
	table.insert(self.free, splat)
end

function SplatPool:activeCount()
	local n = 0
	for _ in pairs(self.active) do
		n += 1
	end
	return n
end

function SplatPool:freeCount()
	return #self.free
end

function SplatPool:releaseAll()
	local list = {}
	for splat in pairs(self.active) do
		table.insert(list, splat)
	end
	for _, splat in ipairs(list) do
		self:release(splat)
	end
end

function SplatPool:prewarm(count)
	for _ = 1, count do
		local splat = self.create()
		self.created += 1
		table.insert(self.free, splat)
	end
end

return SplatPool
```
