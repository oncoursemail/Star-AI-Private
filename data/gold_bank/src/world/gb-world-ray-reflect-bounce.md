---
id: gb-world-ray-reflect-bounce
category: world-raycast
topics: reflection, ricochet, laser mirrors, raycast normal, bounce limit
source: original
---
# Request
I'm making a laser puzzle where the beam bounces off mirror parts (tagged "Mirror") and has to reach a receiver. Non-mirror surfaces stop it. How do I trace the bounces?

# Answer
Cast, and if the hit part is a mirror, reflect the direction about the surface normal with `d - 2(d·n)n` and cast again from the hit point (nudged off the surface so it does not re-hit the same face). Stop at a non-mirror, when the remaining length runs out, or at a bounce limit. The result is the list of points, ready for drawing beams between them.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.LaserTrace
local CollectionService = game:GetService("CollectionService")

export type Trace = { points: { Vector3 }, finalHit: BasePart? }

local LaserTrace = {}

function LaserTrace.reflect(direction: Vector3, normal: Vector3): Vector3
	return direction - 2 * direction:Dot(normal) * normal
end

function LaserTrace.trace(origin: Vector3, direction: Vector3, maxLength: number, maxBounces: number, params: RaycastParams): Trace
	local points = { origin }
	local position = origin
	local heading = direction.Unit
	local remaining = maxLength
	local finalHit: BasePart? = nil

	for bounce = 0, maxBounces do
		local result = workspace:Raycast(position, heading * remaining, params)
		if result == nil then
			table.insert(points, position + heading * remaining)
			break
		end
		table.insert(points, result.Position)
		remaining -= result.Distance
		finalHit = result.Instance
		if not CollectionService:HasTag(result.Instance, "Mirror") or bounce == maxBounces or remaining <= 0 then
			break
		end
		heading = LaserTrace.reflect(heading, result.Normal)
		position = result.Position + result.Normal * 0.01
	end
	return { points = points, finalHit = finalHit }
end

return LaserTrace
```

Checking the puzzle on the server: `local trace = LaserTrace.trace(emitter.Position, emitter.CFrame.LookVector, 500, 8, params)` and the puzzle is solved when `trace.finalHit == receiver`.

- The reflection formula needs a unit normal; raycast normals already are.
- Nudging the new origin along the normal avoids the next ray starting exactly on the mirror's surface and hitting it again at distance 0.
- The bounce limit protects against two parallel mirrors trapping the beam forever.
- Run the trace on the server to decide whether the puzzle is solved, and draw the beams on clients from the same point list.

# Test
```lua
check("reflect off a floor flips Y", item.reflect(Vector3.new(1, -1, 0), Vector3.new(0, 1, 0)) == Vector3.new(1, 1, 0))
local cs = game:GetService("CollectionService")
local mirror = Instance.new("Part")
mirror.Anchored = true
mirror.Size = Vector3.new(1, 10, 10)
mirror.Position = Vector3.new(20, 5, 0)
mirror.Parent = workspace
cs:AddTag(mirror, "Mirror")
local receiver = Instance.new("Part")
receiver.Anchored = true
receiver.Size = Vector3.new(1, 10, 10)
receiver.Position = Vector3.new(-20, 5, 0)
receiver.Parent = workspace
local params = RaycastParams.new()

local trace = item.trace(Vector3.new(0, 5, 0), Vector3.new(1, 0, 0), 200, 4, params)
check("beam bounces off the mirror into the receiver", trace.finalHit == receiver and #trace.points == 3)
check("bounce point on the mirror face", (trace.points[2] - Vector3.new(19.5, 5, 0)).Magnitude < 1e-9)
cs:RemoveTag(mirror, "Mirror")
local stopped = item.trace(Vector3.new(0, 5, 0), Vector3.new(1, 0, 0), 200, 4, params)
check("non-mirror stops the beam", stopped.finalHit == mirror and #stopped.points == 2)
cs:AddTag(receiver, "Mirror")
cs:AddTag(mirror, "Mirror")
local trapped = item.trace(Vector3.new(0, 5, 0), Vector3.new(1, 0, 0), 10000, 6, params)
check("bounce limit ends a trapped beam", #trapped.points == 8)
local short = item.trace(Vector3.new(0, 5, 0), Vector3.new(0, 0, 1), 50, 4, params)
check("open air ends at max length", short.finalHit == nil and (short.points[2] - Vector3.new(0, 5, 50)).Magnitude < 1e-9)
```
