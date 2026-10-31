---
id: gb-world-vfx-hit-burst
category: vfx-particles
topics: ParticleEmitter, Emit, Debris, burst effect, Terrain attachment
source: original
---
# Request
For bullet impacts I clone a part with a ParticleEmitter, enable it, wait 0.2 seconds, disable it and destroy it. The number of sparks changes depending on frame rate and sometimes the sparks vanish mid-air when the part is destroyed. What's the proper way to do one-shot bursts?

# Answer
Keep the emitters disabled and call `Emit(n)` for an exact particle count, independent of frame rate. Clone an Attachment (not a Part) into `workspace.Terrain`, and destroy it only after the longest particle lifetime so nothing disappears early. Each emitter can carry its own `EmitCount` attribute.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.HitBurst
local Debris = game:GetService("Debris")

local DEFAULT_COUNT = 10

local HitBurst = {}

function HitBurst.lifetimeOf(effect: Instance): number
	local longest = 0
	for _, descendant in effect:GetDescendants() do
		if descendant:IsA("ParticleEmitter") then
			longest = math.max(longest, descendant.Lifetime.Max)
		end
	end
	return longest
end

function HitBurst.play(template: Attachment, position: Vector3, scale: number?): Attachment
	local effect = template:Clone()
	effect.Parent = workspace.Terrain
	effect.WorldPosition = position
	local multiplier = scale or 1
	for _, emitter in effect:GetDescendants() do
		if emitter:IsA("ParticleEmitter") then
			local count = emitter:GetAttribute("EmitCount")
			local base: number = if type(count) == "number" then count else DEFAULT_COUNT
			emitter:Emit(math.max(1, math.round(base * multiplier)))
		end
	end
	Debris:AddItem(effect, HitBurst.lifetimeOf(effect) + 0.1)
	return effect
end

return HitBurst
```

- `Emit` spawns exactly that many particles in one call; enable/wait/disable produces `Rate x time` particles, which changes with frame timing.
- An Attachment under Terrain is the cheapest world-space emitter host: no physics, no collision, no part to replicate.
- Emitters in the template should have `Enabled = false` so they emit only through `Emit`.
- Run this on the client from a remote or your own hit prediction; particles are visual and never need to exist on the server.

# Test
```lua
local terrain = Instance.new("Terrain")
terrain.Name = "Terrain"
terrain.CanQuery = false
terrain.Parent = workspace
```
```lua
local template = Instance.new("Attachment")
local sparks = Instance.new("ParticleEmitter")
sparks.Name = "Sparks"
sparks.Enabled = false
sparks.Lifetime = NumberRange.new(0.3, 1.2)
sparks:SetAttribute("EmitCount", 20)
sparks.Parent = template
local smoke = Instance.new("ParticleEmitter")
smoke.Name = "Smoke"
smoke.Lifetime = NumberRange.new(0.5, 0.8)
smoke.Parent = template

local effect = item.play(template, Vector3.new(4, 2, 1), 1.5)
check("emits the attribute count scaled", effect.Sparks.__emitted == 30)
check("falls back to the default count", effect.Smoke.__emitted == 15)
check("placed in Terrain at the hit", effect.Parent == workspace.Terrain and effect.WorldPosition == Vector3.new(4, 2, 1))
check("lifetime is the longest emitter", item.lifetimeOf(template) == 1.2)
__advance(1.0)
check("still alive while particles live", effect.Parent ~= nil)
__advance(0.5)
check("cleaned up after the longest lifetime", effect.Parent == nil)
```
