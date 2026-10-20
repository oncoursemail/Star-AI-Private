---
id: gb-src-raycast-ground-probe
category: world-raycast
topics: workspace:Raycast, RaycastParams, Exclude filter, ground detection, surface normal
source: adapted
source_id: creator-docs
source_path: content/en-us/workspace/raycasting.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I need a helper that tells me what is directly under a character: the ground part, the hit position, how steep it is and the material, ignoring the character's own parts. I keep hitting my own legs with raycasts.

# Answer
Cast straight down with `workspace:Raycast` and a `RaycastParams` set to `Exclude` the character model. The result gives the part, position, normal and material; the slope angle comes from the normal.

```lua
--!strict
export type GroundInfo = {
	part: BasePart,
	position: Vector3,
	slopeDegrees: number,
	material: Enum.Material,
	distance: number,
}

local GroundProbe = {}

function GroundProbe.probe(origin: Vector3, maxDistance: number, ignore: { Instance }): GroundInfo?
	local params = RaycastParams.new()
	params.FilterDescendantsInstances = ignore
	params.FilterType = Enum.RaycastFilterType.Exclude
	params.IgnoreWater = true

	local result = workspace:Raycast(origin, Vector3.new(0, -maxDistance, 0), params)
	if not result then
		return nil
	end
	local cosine = math.clamp(result.Normal:Dot(Vector3.yAxis), -1, 1)
	return {
		part = result.Instance,
		position = result.Position,
		slopeDegrees = math.deg(math.acos(cosine)),
		material = result.Material,
		distance = result.Distance,
	}
end

return GroundProbe
```

Usage: `GroundProbe.probe(root.Position, 10, { character })`.

- `Exclude` with the character model filters every descendant, including accessories and tools.
- The direction vector's length is the ray's range; `nil` means nothing within `maxDistance` (airborne).
- `slopeDegrees` is 0 on flat ground; compare it with a threshold for "too steep to stand" logic.

# Test
```lua
local ground = Instance.new("Part")
ground.Name = "Ground"
ground.Anchored = true
ground.Size = Vector3.new(50, 2, 50)
ground.Position = Vector3.new(0, -1, 0)
ground.Parent = workspace
local p = __makePlayer(1, "Walker")
local character = __makeCharacter(p, Vector3.new(0, 3, 0))
local info = item.probe(character.HumanoidRootPart.Position, 10, { character })
check("hits the ground, not own legs", info ~= nil and info.part == ground)
check("flat ground has zero slope", info ~= nil and math.abs(info.slopeDegrees) < 0.01)
check("hit position on top surface", info ~= nil and math.abs(info.position.Y - 0) < 0.01)
check("out of range returns nil", item.probe(Vector3.new(0, 50, 0), 10, { character }) == nil)
local own = item.probe(character.HumanoidRootPart.Position + Vector3.new(0, 5, 0), 20, {})
check("without the filter the character is hit first", own ~= nil and own.part ~= ground)
```
