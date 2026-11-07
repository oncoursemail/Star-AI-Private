---
id: gb-world-build-room-builder
category: building-layout
topics: procedural room, walls, door opening, parts, CFrame offsets
source: original
---
# Request
For a dungeon generator I need a function that builds a box room (floor, four walls, optional ceiling) from width, depth and height, with a door opening in the front wall. Walls overlapping at the corners or leaving gaps has been my main problem.

# Answer
Size the side walls to the inner depth and the front/back walls to the full width so corners meet without overlap, and build the front wall as three pieces around the door: left, right and a lintel above it. Every part is positioned with an offset from the room's origin CFrame, so rooms can be rotated freely.

```lua
--!strict
-- ModuleScript: ServerScriptService.RoomBuilder
export type RoomSpec = {
	width: number,
	depth: number,
	height: number,
	thickness: number,
	doorWidth: number,
	doorHeight: number,
	ceiling: boolean,
}

local RoomBuilder = {}

function RoomBuilder.build(origin: CFrame, spec: RoomSpec, parent: Instance): Model
	local w, d, h, t = spec.width, spec.depth, spec.height, spec.thickness
	local side = (w - spec.doorWidth) / 2
	assert(side >= t and spec.doorHeight < h, "door must fit inside the front wall")

	local room = Instance.new("Model")
	room.Name = "Room"

	local function addPart(name: string, size: Vector3, offset: CFrame): Part
		local part = Instance.new("Part")
		part.Name = name
		part.Anchored = true
		part.Size = size
		part.CFrame = origin:ToWorldSpace(offset)
		part.Parent = room
		return part
	end

	local floor = addPart("Floor", Vector3.new(w, t, d), CFrame.new(0, -t / 2, 0))
	local innerDepth = d - 2 * t
	addPart("BackWall", Vector3.new(w, h, t), CFrame.new(0, h / 2, -d / 2 + t / 2))
	addPart("LeftWall", Vector3.new(t, h, innerDepth), CFrame.new(-w / 2 + t / 2, h / 2, 0))
	addPart("RightWall", Vector3.new(t, h, innerDepth), CFrame.new(w / 2 - t / 2, h / 2, 0))

	local frontZ = d / 2 - t / 2
	addPart("FrontLeft", Vector3.new(side, h, t), CFrame.new(-w / 2 + side / 2, h / 2, frontZ))
	addPart("FrontRight", Vector3.new(side, h, t), CFrame.new(w / 2 - side / 2, h / 2, frontZ))
	local lintelHeight = h - spec.doorHeight
	addPart("Lintel", Vector3.new(spec.doorWidth, lintelHeight, t), CFrame.new(0, spec.doorHeight + lintelHeight / 2, frontZ))

	if spec.ceiling then
		addPart("Ceiling", Vector3.new(w, t, d), CFrame.new(0, h + t / 2, 0))
	end

	room.PrimaryPart = floor
	room.Parent = parent
	return room
end

return RoomBuilder
```

- The origin is the centre of the floor's top surface, which makes snapping rooms to each other a matter of adding depth along the room's LookVector.
- Front and back walls span the full width; side walls span only the inner depth, so the corners are filled exactly once.
- Generate all rooms into one Model per level and parent it at the end to avoid replicating parts one by one.

# Test
```lua
local spec = { width = 20, depth = 16, height = 10, thickness = 1, doorWidth = 4, doorHeight = 7, ceiling = true }
local room = item.build(CFrame.new(0, 0, 0), spec, workspace)
check("all pieces built", #room:GetChildren() == 8 and room.PrimaryPart == room.Floor)
check("side walls fit between front and back", room.LeftWall.Size.Z == 14)
local inDoor = workspace:GetPartBoundsInBox(CFrame.new(0, 3, 7.5), Vector3.new(0.5, 0.5, 0.5))
check("door opening is empty", #inDoor == 0)
local atBack = workspace:GetPartBoundsInBox(CFrame.new(0, 3, -7.5), Vector3.new(0.5, 0.5, 0.5))
check("back wall is solid", #atBack == 1 and atBack[1] == room.BackWall)
check("lintel sits above the door", math.abs(room.Lintel.Position.Y - 8.5) < 1e-9)
room:Destroy()
local turned = item.build(CFrame.new(50, 0, 0) * CFrame.Angles(0, math.rad(90), 0), spec, workspace)
check("room follows the origin rotation", (turned.BackWall.Position - Vector3.new(42.5, 5, 0)).Magnitude < 1e-9)
local bad = table.clone(spec)
bad.doorWidth = 19
check("door wider than the wall is rejected", not pcall(item.build, CFrame.new(), bad, workspace))
```
