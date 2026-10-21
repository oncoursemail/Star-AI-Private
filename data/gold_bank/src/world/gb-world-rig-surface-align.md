---
id: gb-world-rig-surface-align
category: rig-prop-alignment
topics: surface normal, CFrame.fromMatrix, Cross, raycast placement, decal sign
source: original
---
# Request
Players can stick posters on walls where they click. I use `CFrame.new(hit.Position, hit.Position + hit.Normal)` and it mostly works, but on floors and ceilings the poster spins randomly or disappears. How do I build a stable CFrame from the surface normal?

# Answer
`CFrame.new(pos, lookAt)` has no idea which way is "up" when the normal points straight up or down, so the result is degenerate. Build the axes yourself with cross products and switch to a fallback up direction (the player's facing) when the normal is nearly vertical. The poster's front then faces out of the surface and it is pushed out by half its thickness so it never z-fights.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.SurfaceAlign
local SurfaceAlign = {}

-- CFrame at `position` whose LookVector is `normal`; `upHint` decides the roll.
function SurfaceAlign.fromNormal(position: Vector3, normal: Vector3, upHint: Vector3): CFrame
	local unitNormal = normal.Unit
	local right = unitNormal:Cross(upHint)
	if right.Magnitude < 1e-3 then
		-- upHint is parallel to the normal; any perpendicular axis gives a valid frame.
		right = unitNormal:Cross(Vector3.xAxis)
		if right.Magnitude < 1e-3 then
			right = unitNormal:Cross(Vector3.zAxis)
		end
	end
	local up = right.Unit:Cross(unitNormal)
	return CFrame.fromMatrix(position, right.Unit, up.Unit)
end

function SurfaceAlign.place(result: RaycastResult, thickness: number, facing: Vector3): CFrame
	-- Walls keep world up; floors and ceilings use the player's facing so the poster reads upright for them.
	local upHint = if math.abs(result.Normal.Y) > 0.98 then facing else Vector3.yAxis
	return SurfaceAlign.fromNormal(result.Position, result.Normal, upHint):ToWorldSpace(CFrame.new(0, 0, -thickness / 2))
end

return SurfaceAlign
```

- `CFrame.fromMatrix(pos, right, up)` derives the back vector as `right:Cross(up)`, so building right from `normal x upHint` makes the LookVector equal the normal.
- Moving along local -Z (forward) by half the thickness keeps the poster on the surface instead of half inside it.
- Do the placement on the server with the server's own raycast; trust only the client's click direction, not its hit position.

# Test
```lua
local wall = item.fromNormal(Vector3.new(0, 5, 0), Vector3.new(0, 0, 1), Vector3.yAxis)
check("wall poster faces out of the wall", (wall.LookVector - Vector3.new(0, 0, 1)).Magnitude < 1e-6)
check("wall poster stays upright", (wall.UpVector - Vector3.yAxis).Magnitude < 1e-6)

local floor = item.fromNormal(Vector3.zero, Vector3.new(0, 1, 0), Vector3.yAxis)
local lv = floor.LookVector
check("floor normal still gives a valid frame", lv.X == lv.X and (lv - Vector3.yAxis).Magnitude < 1e-6)

local block = Instance.new("Part")
block.Anchored = true
block.Size = Vector3.new(10, 10, 2)
block.Position = Vector3.new(0, 5, 0)
block.Parent = workspace
local hit = workspace:Raycast(Vector3.new(0, 5, 10), Vector3.new(0, 0, -20))
local placed = item.place(hit, 0.2, Vector3.new(0, 0, -1))
check("placed on the wall face, pushed out by half thickness", math.abs(placed.Position.Z - 1.1) < 1e-6)

local ceiling = item.fromNormal(Vector3.zero, Vector3.new(0, -1, 0), Vector3.new(1, 0, 0))
check("ceiling uses the facing hint for roll", (ceiling.UpVector - Vector3.new(1, 0, 0)).Magnitude < 1e-6)
```
