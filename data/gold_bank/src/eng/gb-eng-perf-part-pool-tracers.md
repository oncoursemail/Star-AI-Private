---
id: gb-eng-perf-part-pool-tracers
category: performance
topics: part pooling, Instance.new cost, tracers, CFrame parking, client effects
source: original
---
# Request
My client-side bullet tracers create a new Part for every shot and Destroy it 0.1 s later. With miniguns that's hundreds of parts per second and the frame rate dips. Is pooling parts worth it, and how do I do it without parenting/unparenting every time?

# Answer
Yes: creating and parenting a part is far more expensive than moving one. Pre-create parts once, keep them parented, and "hide" free ones by moving them far away instead of changing `Parent` (which triggers replication/hierarchy work). A tracer then only sets `CFrame`, `Size` and `Transparency`.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.TracerPool (client)
local PARK = CFrame.new(0, 10e6, 0)

export type TracerPool = {
	free: { BasePart },
	inUse: { [BasePart]: boolean },
	folder: Instance,
	template: BasePart,
}

local TracerPool = {}

local function makePart(pool: TracerPool): BasePart
	local part = pool.template:Clone()
	part.Anchored = true
	part.CanCollide = false
	part.CanQuery = false
	part.CanTouch = false
	part.CFrame = PARK
	part.Parent = pool.folder
	return part
end

function TracerPool.new(template: BasePart, folder: Instance, prewarm: number): TracerPool
	local pool: TracerPool = { free = {}, inUse = {}, folder = folder, template = template }
	for _ = 1, prewarm do
		table.insert(pool.free, makePart(pool))
	end
	return pool
end

function TracerPool.show(pool: TracerPool, from: Vector3, to: Vector3, lifetime: number): BasePart
	local part = table.remove(pool.free) or makePart(pool)
	pool.inUse[part] = true
	local length = (to - from).Magnitude
	part.Size = Vector3.new(0.1, 0.1, length)
	part.CFrame = CFrame.lookAt((from + to) / 2, to)
	part.Transparency = 0.2
	task.delay(lifetime, function()
		if pool.inUse[part] then
			pool.inUse[part] = nil
			part.CFrame = PARK
			table.insert(pool.free, part)
		end
	end)
	return part
end

return TracerPool
```

- Prewarm to your typical peak (for example 60) during loading so the first burst does not create parts mid-fight; the pool still grows if a burst exceeds it.
- Parking far away keeps the parts parented, so reuse is a property change instead of a hierarchy change; `CanQuery`/`CanTouch` off keeps parked parts out of raycasts and touch checks.
- Tracers are cosmetic: run this on each client from a replicated "shot fired" event, while hit detection stays on the server.

# Test
```lua
local folder = Instance.new("Folder")
folder.Parent = workspace
local template = Instance.new("Part")
local pool = item.new(template, folder, 3)
check("prewarmed parts parked", #pool.free == 3 and #folder:GetChildren() == 3 and pool.free[1].Position.Y > 1e6)
local a = item.show(pool, Vector3.new(0, 0, 0), Vector3.new(0, 0, 20), 0.1)
check("tracer placed between points", a.Size.Z == 20 and math.abs(a.Position.Z - 10) < 1e-6 and #pool.free == 2)
for _ = 1, 4 do
	item.show(pool, Vector3.zero, Vector3.new(5, 0, 0), 0.1)
end
check("pool grows under burst", #folder:GetChildren() == 5 and #pool.free == 0)
__advance(0.2)
check("parts returned and parked after lifetime", #pool.free == 5 and a.Position.Y > 1e6 and a.Parent == folder)
local b = item.show(pool, Vector3.zero, Vector3.new(1, 0, 0), 0.1)
check("reuse creates no new parts", #folder:GetChildren() == 5 and b.CanQuery == false)
```
