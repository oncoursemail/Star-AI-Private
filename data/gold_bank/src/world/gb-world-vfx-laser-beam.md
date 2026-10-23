---
id: gb-world-vfx-laser-beam
category: vfx-beam-trail
topics: Beam, laser sight, raycast, Attachment.WorldPosition, RenderStepped
source: original
---
# Request
I want a laser sight on my rifle: a thin red beam from the muzzle that stops at whatever it hits, or goes out to 300 studs if it hits nothing. How do I make the beam end at the hit point every frame?

# Answer
A Beam needs two attachments, so keep the start attachment on the muzzle and a second "end" attachment parented to `workspace.Terrain` that you move to the ray hit each frame. The ray direction comes from the muzzle attachment's own orientation, so the laser always matches the gun model.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.LaserSight
export type Laser = {
	update: () -> RaycastResult?,
	cleanup: () -> (),
}

local LaserSight = {}

function LaserSight.new(muzzle: Attachment, maxRange: number, ignore: { Instance }): Laser
	local endPoint = Instance.new("Attachment")
	endPoint.Name = "LaserEnd"
	endPoint.Parent = workspace.Terrain

	local beam = Instance.new("Beam")
	beam.Attachment0 = muzzle
	beam.Attachment1 = endPoint
	beam.Color = ColorSequence.new(Color3.fromRGB(255, 40, 40))
	beam.Width0 = 0.05
	beam.Width1 = 0.05
	beam.LightEmission = 1
	beam.FaceCamera = true
	beam.Parent = endPoint

	local params = RaycastParams.new()
	params.FilterType = Enum.RaycastFilterType.Exclude
	params.FilterDescendantsInstances = ignore

	local function update(): RaycastResult?
		local frame = muzzle.WorldCFrame
		local direction = frame:VectorToWorldSpace(Vector3.new(0, 0, -maxRange))
		local result = workspace:Raycast(frame.Position, direction, params)
		endPoint.WorldPosition = if result then result.Position else frame:PointToWorldSpace(Vector3.new(0, 0, -maxRange))
		return result
	end

	return {
		update = update,
		cleanup = function()
			endPoint:Destroy()
		end,
	}
end

return LaserSight
```

Driving it while the rifle is equipped (LocalScript in the tool):

```lua
--!strict
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local LaserSight = require(game:GetService("ReplicatedStorage"):WaitForChild("LaserSight"))

local tool = script.Parent
local muzzle = tool:WaitForChild("Handle"):WaitForChild("Muzzle")
local stopLaser: (() -> ())? = nil

tool.Equipped:Connect(function()
	local laser = LaserSight.new(muzzle, 300, { Players.LocalPlayer.Character })
	RunService:BindToRenderStep("LaserSight", Enum.RenderPriority.Camera.Value + 1, function()
		laser.update()
	end)
	stopLaser = function()
		RunService:UnbindFromRenderStep("LaserSight")
		laser.cleanup()
	end
end)

tool.Unequipped:Connect(function()
	if stopLaser then
		stopLaser()
		stopLaser = nil
	end
end)
```

- The muzzle attachment's -Z axis is "forward"; rotate the attachment in Studio so its front points down the barrel.
- Binding after the camera update keeps the beam glued to the gun even while the camera moves in first person.
- Excluding the shooter's character stops the ray from hitting the gun or arms at point-blank range.
- Everything here runs in the holder's LocalScript, so only they see the laser. To show other players' lasers, run the same module on each client for every equipped rifle.

# Test
```lua
local terrain = Instance.new("Terrain")
terrain.Name = "Terrain"
terrain.CanQuery = false
terrain.Parent = workspace
```
```lua
local wall = Instance.new("Part")
wall.Anchored = true
wall.Size = Vector3.new(20, 20, 1)
wall.Position = Vector3.new(0, 5, -50)
wall.Parent = workspace
local gun = Instance.new("Part")
gun.Parent = workspace
local muzzle = Instance.new("Attachment")
muzzle.Parent = gun
muzzle.WorldCFrame = CFrame.new(0, 5, 0)

local laser = item.new(muzzle, 300, { gun })
local endPoint = workspace.Terrain.LaserEnd
local hit = laser.update()
check("laser stops at the wall", hit ~= nil and hit.Instance == wall and math.abs(endPoint.WorldPosition.Z + 49.5) < 1e-6)
muzzle.WorldCFrame = CFrame.new(0, 5, 0) * CFrame.Angles(0, math.rad(180), 0)
check("no hit returns nil", laser.update() == nil)
check("open air extends to max range", (endPoint.WorldPosition - Vector3.new(0, 5, 300)).Magnitude < 1e-6)
check("beam connects muzzle and end", endPoint:FindFirstChildOfClass("Beam").Attachment0 == muzzle)
laser.cleanup()
check("cleanup removes the end attachment", workspace.Terrain:FindFirstChild("LaserEnd") == nil)
```
