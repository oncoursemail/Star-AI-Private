---
id: gb-world-combat-penetrating-hitscan
category: combat-hitbox
topics: hitscan, wall penetration, raycast, damage falloff, RaycastParams
source: original
---
# Request
My sniper should shoot through thin walls (up to 2 studs of material in total) and through multiple players, losing damage with each wall. A single raycast stops at the first thing it hits. How do I continue the ray?

# Answer
Loop: cast, handle what was hit, then continue from the hit point. A character hit is recorded and added to the exclude list. A wall's thickness is measured by casting back from beyond the entry point against only that wall; if the remaining penetration budget covers it, the ray continues from the exit point with reduced damage, otherwise the shot stops.

```lua
--!strict
-- ModuleScript: ServerScriptService.PenetratingShot
export type Hit = { humanoid: Humanoid, position: Vector3, damageScale: number }

local WALL_FALLOFF = 0.6

local PenetratingShot = {}

local function wallThickness(entry: Vector3, direction: Vector3, wall: BasePart, maxDepth: number): number?
	local params = RaycastParams.new()
	params.FilterType = Enum.RaycastFilterType.Include
	params.FilterDescendantsInstances = { wall }
	local beyond = entry + direction * maxDepth
	local back = workspace:Raycast(beyond, entry - beyond, params)
	if back == nil then
		return nil
	end
	return (back.Position - entry).Magnitude
end

function PenetratingShot.fire(origin: Vector3, direction: Vector3, range: number, penetration: number, shooter: Instance): { Hit }
	local unit = direction.Unit
	local exclude: { Instance } = { shooter }
	local hits: { Hit } = {}
	local position = origin
	local travelled = 0
	local budget = penetration
	local scale = 1

	while travelled < range do
		local params = RaycastParams.new()
		params.FilterType = Enum.RaycastFilterType.Exclude
		params.FilterDescendantsInstances = exclude
		local result = workspace:Raycast(position, unit * (range - travelled), params)
		if result == nil then
			break
		end
		travelled += (result.Position - position).Magnitude
		local model = result.Instance:FindFirstAncestorOfClass("Model")
		local humanoid = if model then model:FindFirstChildOfClass("Humanoid") else nil
		if model and humanoid then
			table.insert(hits, { humanoid = humanoid, position = result.Position, damageScale = scale })
			table.insert(exclude, model)
			position = result.Position
		else
			local thickness = wallThickness(result.Position, unit, result.Instance, budget + 0.01)
			if thickness == nil or thickness > budget then
				break
			end
			budget -= thickness
			scale *= WALL_FALLOFF
			travelled += thickness
			position = result.Position + unit * (thickness + 0.01)
		end
	end
	return hits
end

return PenetratingShot
```

- Characters go into the exclude list instead of being stepped through, so a ray that hits an arm does not hit the same player's torso again.
- The back-cast only includes the wall that was hit, so its result is the wall's exit face even with other geometry right behind it.
- Thickness is limited to the remaining budget plus a hair, so a 50-stud-thick terrain cliff never costs a long cast.
- Apply `damageScale` with your damage service; the server should also run this, not trust a client list of hits.

# Test
```lua
local function wall(z, thickness)
	local p = Instance.new("Part")
	p.Anchored = true
	p.Size = Vector3.new(20, 20, thickness)
	p.Position = Vector3.new(0, 5, z)
	p.Parent = workspace
	return p
end
local shooter = __buildRig(Vector3.new(0, 3, 0))
shooter.Parent = workspace
wall(-10, 1)
local first = __buildRig(Vector3.new(0, 4, -20))
first.Parent = workspace
local second = __buildRig(Vector3.new(0, 4, -30))
second.Parent = workspace
local thick = wall(-40, 3)
local hidden = __buildRig(Vector3.new(0, 4, -50))
hidden.Parent = workspace

local hits = item.fire(Vector3.new(0, 4, 0), Vector3.new(0, 0, -1), 200, 2, shooter)
check("passes a thin wall and two players", #hits == 2 and hits[1].humanoid == first.Humanoid and hits[2].humanoid == second.Humanoid)
check("damage drops after the wall", math.abs(hits[1].damageScale - 0.6) < 1e-9 and math.abs(hits[2].damageScale - 0.6) < 1e-9)
check("thick wall stops the shot", hits[3] == nil)
thick.Size = Vector3.new(20, 20, 0.5)
local through = item.fire(Vector3.new(0, 4, 0), Vector3.new(0, 0, -1), 200, 2, shooter)
check("total budget allows two thin walls", #through == 3 and through[3].humanoid == hidden.Humanoid and math.abs(through[3].damageScale - 0.36) < 1e-9)
check("range limits the shot", #item.fire(Vector3.new(0, 4, 0), Vector3.new(0, 0, -1), 15, 2, shooter) == 0)
```
