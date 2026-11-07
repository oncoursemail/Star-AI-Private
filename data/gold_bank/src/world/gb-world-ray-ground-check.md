---
id: gb-world-ray-ground-check
category: world-raycast
topics: ground check, raycast, surface normal, slope angle, RaycastParams
source: original
---
# Request
For a custom movement system I need to know if the character is on the ground, what it's standing on, and how steep the slope is (so I can block sliding abilities on steep slopes). `Humanoid.FloorMaterial` doesn't give me the slope. How do I do a proper ground check?

# Answer
Cast a short ray straight down from the root, just past where the feet are, excluding the character. The result gives the part, material and surface normal; the slope angle is the angle between that normal and world up. Reuse one RaycastParams per character instead of building it every frame.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.GroundCheck
export type Ground = { part: BasePart, material: Enum.Material, normal: Vector3, slope: number, distance: number }

local GroundCheck = {}

function GroundCheck.slopeAngle(normal: Vector3): number
	return math.deg(math.acos(math.clamp(normal.Unit:Dot(Vector3.yAxis), -1, 1)))
end

function GroundCheck.newProbe(character: Model, hipToFeet: number, tolerance: number): () -> Ground?
	local root = character:FindFirstChild("HumanoidRootPart")
	assert(root and root:IsA("BasePart"), "character needs a HumanoidRootPart")
	local params = RaycastParams.new()
	params.FilterType = Enum.RaycastFilterType.Exclude
	params.FilterDescendantsInstances = { character }
	params.RespectCanCollide = true

	return function(): Ground?
		local result = workspace:Raycast(root.Position, Vector3.new(0, -(hipToFeet + tolerance), 0), params)
		if result == nil then
			return nil
		end
		return {
			part = result.Instance,
			material = result.Material,
			normal = result.Normal,
			slope = GroundCheck.slopeAngle(result.Normal),
			distance = result.Distance,
		}
	end
end

return GroundCheck
```

Using it to gate a slide ability on the client:

```lua
--!strict
local Players = game:GetService("Players")
local GroundCheck = require(game:GetService("ReplicatedStorage"):WaitForChild("GroundCheck"))

local character = Players.LocalPlayer.Character or Players.LocalPlayer.CharacterAdded:Wait()
local probe = GroundCheck.newProbe(character, 3, 0.6)

local function canSlide(): boolean
	local ground = probe()
	return ground ~= nil and ground.slope <= 40
end

return canSlide
```

- `hipToFeet` is the distance from the root's centre to the bottom of the feet (3 studs for a default R15 character); the tolerance lets small steps and bumps still count as grounded.
- `RespectCanCollide` stops the probe from "standing" on non-collidable decorations such as grass meshes or trigger zones.
- A single ray can miss when the character stands on an edge with the centre over a gap; use `workspace:Spherecast` with a radius of about the root's half width if that matters for your game.

# Test
```lua
check("flat ground is 0 degrees", math.abs(item.slopeAngle(Vector3.new(0, 1, 0))) < 1e-9)
check("45 degree normal", math.abs(item.slopeAngle(Vector3.new(1, 1, 0)) - 45) < 1e-9)
check("wall is 90 degrees", math.abs(item.slopeAngle(Vector3.new(0, 0, 1)) - 90) < 1e-9)

local floor = Instance.new("Part")
floor.Anchored = true
floor.Size = Vector3.new(50, 1, 50)
floor.Position = Vector3.new(0, 0, 0)
floor.Material = Enum.Material.Sand
floor.Parent = workspace
local player = __makePlayer(101, "Runner")
local character = __makeCharacter(player, Vector3.new(0, 3.5, 0))
local probe = item.newProbe(character, 3, 0.6)
local ground = probe()
check("grounded on the floor", ground ~= nil and ground.part == floor and ground.material == Enum.Material.Sand)
check("distance and slope reported", math.abs(ground.distance - 3) < 1e-9 and ground.slope == 0)
character.HumanoidRootPart.Position = Vector3.new(0, 10, 0)
check("airborne returns nil", probe() == nil)
character.HumanoidRootPart.Position = Vector3.new(0, 3.5, 0)
check("own body never counts as ground", probe().part == floor)
```
