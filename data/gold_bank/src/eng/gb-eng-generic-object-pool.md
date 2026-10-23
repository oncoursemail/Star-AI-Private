---
id: gb-eng-generic-object-pool
category: engineering-algorithm
topics: object pool, reuse, garbage collection, generics, reset callback
source: original
---
# Request
My particle-like effect system creates thousands of small state tables per second (position, velocity, life) and the GC spikes are visible. Can you write a generic object pool where I pass in how to create and how to reset an object?

# Answer
A pool that keeps a stack of released objects, hands them out before creating new ones, and runs a reset callback on release so stale state never leaks into the next user. A cap on the free list stops a burst from pinning memory forever.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Pool
export type Pool<T> = {
	acquire: (self: Pool<T>) -> T,
	release: (self: Pool<T>, object: T) -> (),
	stats: (self: Pool<T>) -> (number, number),
}

local Pool = {}

function Pool.new<T>(create: () -> T, reset: (T) -> (), maxFree: number?): Pool<T>
	local free: { T } = {}
	local inUse: { [T]: boolean } = {}
	local cap = maxFree or 256
	local pool = {} :: Pool<T>

	function pool.acquire(_self: Pool<T>): T
		local object = free[#free]
		if object ~= nil then
			free[#free] = nil
		else
			object = create()
		end
		inUse[object] = true
		return object
	end

	function pool.release(_self: Pool<T>, object: T): ()
		if not inUse[object] then
			error("released an object this pool did not hand out (or released it twice)", 2)
		end
		inUse[object] = nil
		reset(object)
		if #free < cap then
			table.insert(free, object)
		end
	end

	function pool.stats(_self: Pool<T>): (number, number)
		local active = 0
		for _ in inUse do
			active += 1
		end
		return active, #free
	end

	return pool
end

return Pool
```

- Usage: `local sparks = Pool.new(function() return { pos = Vector3.zero, vel = Vector3.zero, life = 0 } end, function(s) s.life = 0 end)`.
- Double release is the classic pool bug (two systems end up sharing one object); the `inUse` set turns it into an immediate error at the faulty call.
- Pools pay off for objects created at high rates; for a few allocations per second the GC handles it fine and the extra bookkeeping is not worth it.

# Test
```lua
local created = 0
local pool = item.new(function()
	created += 1
	return { life = 0, tag = created }
end, function(o)
	o.life = 0
end, 2)
local a = pool:acquire()
local b = pool:acquire()
a.life = 5
pool:release(a)
local c = pool:acquire()
check("reuses released object", c == a and created == 2)
check("reset ran on release", c.life == 0)
check("double release errors", not pcall(function()
	pool:release(b)
	pool:release(b)
end))
check("foreign object rejected", not pcall(function()
	pool:release({ life = 1 })
end))
local extra = {}
for i = 1, 5 do
	extra[i] = pool:acquire()
end
for i = 1, 5 do
	pool:release(extra[i])
end
local active, free = pool:stats()
check("free list capped", free == 2 and active == 1)
```
