---
id: gb-world-vfx-impact-pool
category: vfx-particles
topics: object pool, ParticleEmitter, minigun, Clone cost, ring buffer
source: original
---
# Request
My minigun fires 20 bullets a second and each impact clones a VFX attachment and destroys it later. The microprofiler shows the clones and destroys adding up. Can I reuse the effects instead?

# Answer
Pre-create a fixed ring of attachments and move the next one to each impact before calling `Emit`. Particles already emitted stay where they were spawned, so reusing a slot does not drag the previous burst along. The ring size bounds the memory no matter how fast the gun fires.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.ImpactPool
export type Pool = {
	emitAt: (position: Vector3, count: number?) -> Attachment,
	capacity: () -> number,
}

local ImpactPool = {}

function ImpactPool.new(template: Attachment, capacity: number, container: Instance): Pool
	assert(capacity >= 1, "capacity must be at least 1")
	local slots: { Attachment } = {}
	local emitters: { { ParticleEmitter } } = {}
	for index = 1, capacity do
		local slot = template:Clone()
		local found: { ParticleEmitter } = {}
		for _, child in slot:GetChildren() do
			if child:IsA("ParticleEmitter") then
				table.insert(found, child)
			end
		end
		slot.Parent = container
		slots[index] = slot
		emitters[index] = found
	end
	local nextIndex = 1

	return {
		emitAt = function(position: Vector3, count: number?): Attachment
			local index = nextIndex
			local slot = slots[index]
			nextIndex = index % capacity + 1
			slot.WorldPosition = position
			for _, emitter in emitters[index] do
				emitter:Emit(count or 8)
			end
			return slot
		end,
		capacity = function(): number
			return #slots
		end,
	}
end

return ImpactPool
```

Usage on the client: `local pool = ImpactPool.new(templates.Spark, 24, workspace.Terrain)` once, then `pool.emitAt(hitPosition)` per impact.

- Leave `LockedToPart` off on the emitters (the default): with it on, moving the slot would teleport the previous burst's live particles.
- Size the ring for "shots per second x longest visible lifetime"; 24 covers a 20 rps gun with sparks lasting about a second.
- No Debris, no task.delay, no Clone and no `GetChildren` per shot: each slot's emitters are collected once when the pool is built, so the only per-impact work is one property write and the `Emit` calls. Emitters added to a slot later are not picked up.

# Test
```lua
local container = Instance.new("Folder")
local template = Instance.new("Attachment")
local spark = Instance.new("ParticleEmitter")
spark.Name = "Spark"
spark.Parent = template
local pool = item.new(template, 3, container)

check("pool pre-creates its slots", pool.capacity() == 3 and #container:GetChildren() == 3)
local first = pool.emitAt(Vector3.new(1, 0, 0))
pool.emitAt(Vector3.new(2, 0, 0), 4)
pool.emitAt(Vector3.new(3, 0, 0))
local fourth = pool.emitAt(Vector3.new(4, 0, 0))
check("ring wraps back to the first slot", fourth == first)
check("reused slot moved to the new impact", first.WorldPosition == Vector3.new(4, 0, 0))
check("emits each time it is used", first.Spark.__emitted == 16)
check("no extra instances created", #container:GetChildren() == 3)
check("zero capacity is rejected", not pcall(item.new, template, 0, container))
```
