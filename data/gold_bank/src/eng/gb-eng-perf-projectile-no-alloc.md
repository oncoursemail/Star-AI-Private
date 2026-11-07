---
id: gb-eng-perf-projectile-no-alloc
category: performance
topics: per-frame allocation, garbage collection, RaycastParams reuse, projectiles, Heartbeat
source: original
---
# Request
I simulate ~300 bullets on the server in Heartbeat. The MicroProfiler shows lots of GC time. Per frame I create a new RaycastParams for every bullet, build a `{pos, vel}` table for each step and use `table.insert` into a fresh "alive" list. How should a hot loop like this be written?

# Answer
Allocate once, mutate in place: one shared RaycastParams, bullet state stored in parallel arrays (no per-bullet table per frame), and swap-remove for dead bullets so no new list is built. The loop then creates nothing except the Vector3 values the math needs.

```lua
--!strict
-- ModuleScript: ServerScriptService.BulletSim
export type Sim = {
	count: number,
	positions: { Vector3 },
	velocities: { Vector3 },
	ages: { number },
	owners: { Player | false },
	params: RaycastParams,
}

local GRAVITY = Vector3.new(0, -workspace.Gravity * 0.25, 0)
local MAX_AGE = 3

local BulletSim = {}

function BulletSim.new(ignore: { Instance }): Sim
	local params = RaycastParams.new() -- one params object, reused for every ray
	params.FilterType = Enum.RaycastFilterType.Exclude
	params.FilterDescendantsInstances = ignore
	return { count = 0, positions = {}, velocities = {}, ages = {}, owners = {}, params = params }
end

function BulletSim.spawn(sim: Sim, origin: Vector3, velocity: Vector3, owner: Player?): ()
	local i = sim.count + 1
	sim.count = i
	sim.positions[i] = origin
	sim.velocities[i] = velocity
	sim.ages[i] = 0
	sim.owners[i] = owner or false
end

local function removeAt(sim: Sim, i: number)
	local last = sim.count
	sim.positions[i] = sim.positions[last]
	sim.velocities[i] = sim.velocities[last]
	sim.ages[i] = sim.ages[last]
	sim.owners[i] = sim.owners[last]
	sim.positions[last] = nil
	sim.velocities[last] = nil
	sim.ages[last] = nil
	sim.owners[last] = nil
	sim.count = last - 1
end

function BulletSim.step(sim: Sim, dt: number, onHit: (owner: Player | false, result: RaycastResult) -> ()): ()
	local i = 1
	while i <= sim.count do
		local velocity = sim.velocities[i] + GRAVITY * dt
		local displacement = velocity * dt
		local result = workspace:Raycast(sim.positions[i], displacement, sim.params)
		sim.ages[i] += dt
		if result then
			onHit(sim.owners[i], result)
			removeAt(sim, i) -- the last bullet moved into slot i; do not advance
		elseif sim.ages[i] > MAX_AGE then
			removeAt(sim, i)
		else
			sim.positions[i] += displacement
			sim.velocities[i] = velocity
			i += 1
		end
	end
end

return BulletSim
```

- Swap-remove is O(1) and allocates nothing; bullet order does not matter, so moving the last bullet into the gap is safe as long as the loop re-checks slot `i`.
- Parallel arrays stay the same tables for the whole session; with a table per bullet per frame, 300 bullets at 60 Hz is 18,000 garbage tables a second.
- Measure with the MicroProfiler before and after; if raycasts dominate, the next step is fewer rays (longer steps at lower rates), not more micro-optimisation.

# Test
```lua
local wall = Instance.new("Part")
wall.Anchored = true
wall.Size = Vector3.new(1, 50, 50)
wall.Position = Vector3.new(30, 0, 0)
wall.Parent = workspace
local sim = item.new({})
local shooter = __makePlayer(1, "Shooter")
for i = 1, 5 do
	item.spawn(sim, Vector3.new(0, 0, i), Vector3.new(100, 0, 0), shooter)
end
item.spawn(sim, Vector3.new(0, 0, 0), Vector3.new(-50, 0, 0), nil)
local hits = {}
for _ = 1, 30 do
	item.step(sim, 1 / 60, function(owner, result)
		table.insert(hits, { owner = owner, inst = result.Instance })
	end)
end
check("all bullets toward the wall hit it", #hits == 5 and hits[1].inst == wall and hits[1].owner == shooter)
check("missed bullet still flying", sim.count == 1)
check("arrays compacted", sim.positions[2] == nil and #sim.ages == 1)
for _ = 1, 200 do
	item.step(sim, 1 / 60, function() end)
end
check("expired bullet removed", sim.count == 0 and sim.positions[1] == nil)
local before = sim.params
item.spawn(sim, Vector3.zero, Vector3.new(0, 0, 10), nil)
item.step(sim, 1 / 60, function() end)
check("params object reused", sim.params == before)
```
