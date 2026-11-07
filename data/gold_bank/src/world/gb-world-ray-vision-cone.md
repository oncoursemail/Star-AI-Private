---
id: gb-world-ray-vision-cone
category: world-raycast
topics: line of sight, field of view, NPC vision, raycast, stealth
source: original
---
# Request
For a stealth game, guards should only notice players who are within 60 studs, inside a 90-degree view cone in front of them, and not hidden behind walls. Glass windows shouldn't block vision. How do I write the "can the guard see this player" check?

# Answer
Do the cheap tests first: distance, then the angle between the guard's look direction and the direction to the target (a dot product against the cosine of half the cone). Only if both pass, cast a ray from the guard's eyes to the target's head; anything hit other than the target means it is hidden. Glass is excluded by putting see-through parts in a tagged list that the ray ignores.

```lua
--!strict
-- ModuleScript: ServerScriptService.Vision
local CollectionService = game:GetService("CollectionService")

export type Eye = { range: number, fovDegrees: number }

local Vision = {}

function Vision.inCone(eyeCFrame: CFrame, point: Vector3, eye: Eye): boolean
	local offset = point - eyeCFrame.Position
	local distance = offset.Magnitude
	if distance > eye.range then
		return false
	end
	if distance < 1e-3 then
		return true
	end
	return eyeCFrame.LookVector:Dot(offset / distance) >= math.cos(math.rad(eye.fovDegrees / 2))
end

function Vision.canSee(guard: Model, eyeCFrame: CFrame, target: Model, eye: Eye): boolean
	local head = target:FindFirstChild("Head")
	if head == nil or not head:IsA("BasePart") or not Vision.inCone(eyeCFrame, head.Position, eye) then
		return false
	end
	local ignore: { Instance } = { guard }
	for _, glass in CollectionService:GetTagged("SeeThrough") do
		table.insert(ignore, glass)
	end
	local params = RaycastParams.new()
	params.FilterType = Enum.RaycastFilterType.Exclude
	params.FilterDescendantsInstances = ignore
	local result = workspace:Raycast(eyeCFrame.Position, head.Position - eyeCFrame.Position, params)
	return result ~= nil and result.Instance:IsDescendantOf(target)
end

return Vision
```

- Raycasts are the expensive part, so the distance and cone checks run first and reject most players for free.
- Casting to the head means a player crouching behind a low wall is hidden; cast to the torso as well if you want partially visible players to count.
- Requiring the ray to hit the target (rather than "hit nothing") also catches the case where the target is standing inside a wall the cone check cannot know about.
- Guards should use their Head's CFrame (`guard.Head.CFrame`) as the eye, so animations that turn the head also turn the view.

# Test
```lua
local eye = { range = 60, fovDegrees = 90 }
local look = CFrame.new(0, 4.5, 0)
check("straight ahead is in the cone", item.inCone(look, Vector3.new(0, 4.5, -30), eye))
check("44 degrees off-axis is inside", item.inCone(look, Vector3.new(math.tan(math.rad(44)) * 10, 4.5, -10), eye))
check("behind is outside", not item.inCone(look, Vector3.new(0, 4.5, 30), eye))
check("too far is outside", not item.inCone(look, Vector3.new(0, 4.5, -80), eye))

local guard = __buildRig(Vector3.new(0, 3, 0))
guard.Parent = workspace
local player = __makePlayer(102, "Sneaky")
local target = __makeCharacter(player, Vector3.new(0, 3, -30))
check("visible target is seen", item.canSee(guard, look, target, eye))
local wall = Instance.new("Part")
wall.Anchored = true
wall.Size = Vector3.new(20, 20, 1)
wall.Position = Vector3.new(0, 5, -15)
wall.Parent = workspace
check("wall hides the target", not item.canSee(guard, look, target, eye))
game:GetService("CollectionService"):AddTag(wall, "SeeThrough")
check("see-through glass does not block", item.canSee(guard, look, target, eye))
```
