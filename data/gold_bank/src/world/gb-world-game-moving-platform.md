---
id: gb-world-game-moving-platform
category: gameplay-systems
topics: moving platform, AlignPosition, ping-pong, players carried, constraints
source: original
---
# Request
I move my platforms with TweenService on an anchored part. They move fine, but players standing on them slide off or get left behind. How do I make a moving platform that carries players?

# Answer
Characters are only carried by parts the physics engine moves. Make the platform unanchored, hold it with AlignPosition and AlignOrientation to a target that you move between two points on the server, and let friction carry everyone on top. The ping-pong position is a pure function of elapsed time, so it never drifts and is easy to test.

```lua
--!strict
-- ModuleScript: ServerScriptService.MovingPlatform
local RunService = game:GetService("RunService")

local MovingPlatform = {}

-- Smooth back-and-forth between a and b; `period` is one full round trip in seconds.
function MovingPlatform.positionAt(a: Vector3, b: Vector3, period: number, t: number): Vector3
	local phase = (t % period) / period
	local alpha = (1 - math.cos(phase * 2 * math.pi)) / 2
	return a:Lerp(b, alpha)
end

function MovingPlatform.start(platform: BasePart, a: Vector3, b: Vector3, period: number): () -> ()
	local attachment = Instance.new("Attachment")
	attachment.Parent = platform

	local align = Instance.new("AlignPosition")
	align.Mode = Enum.PositionAlignmentMode.OneAttachment
	align.Attachment0 = attachment
	align.RigidityEnabled = true
	align.Position = a
	align.Parent = platform

	local keepUpright = Instance.new("AlignOrientation")
	keepUpright.Mode = Enum.OrientationAlignmentMode.OneAttachment
	keepUpright.Attachment0 = attachment
	keepUpright.RigidityEnabled = true
	keepUpright.CFrame = platform.CFrame.Rotation
	keepUpright.Parent = platform

	platform.Anchored = false
	platform:SetNetworkOwner(nil)

	local elapsed = 0
	local connection = RunService.Heartbeat:Connect(function(dt: number)
		elapsed += dt
		align.Position = MovingPlatform.positionAt(a, b, period, elapsed)
	end)

	return function()
		connection:Disconnect()
		align:Destroy()
		keepUpright:Destroy()
		attachment:Destroy()
		platform.Anchored = true
	end
end

return MovingPlatform
```

Usage: `MovingPlatform.start(workspace.Lift, workspace.Lift.Position, workspace.Lift.Position + Vector3.new(0, 0, 40), 8)`.

- An anchored part moved by tweens teleports a little every frame; physics sees no velocity, so nothing on top is carried.
- `RigidityEnabled` makes the constraints follow the target as hard as possible, so heavy groups of players do not drag the platform down.
- The server owns the platform (`SetNetworkOwner(nil)`); otherwise ownership can jump to a player standing on it and the motion stutters for everyone else.
- The cosine easing slows the platform at each end, which keeps players from being thrown off when it reverses.

# Test
```lua
local a, b = Vector3.new(0, 10, 0), Vector3.new(0, 10, 40)
check("starts at a", (item.positionAt(a, b, 8, 0) - a).Magnitude < 1e-9)
check("reaches b at half period", (item.positionAt(a, b, 8, 4) - b).Magnitude < 1e-9)
check("back at a after a full period", (item.positionAt(a, b, 8, 8) - a).Magnitude < 1e-9)
check("eases: a quarter of the time covers half the distance", math.abs(item.positionAt(a, b, 8, 2).Z - 20) < 1e-9)

local platform = Instance.new("Part")
platform.Anchored = true
platform.Position = a
platform.Parent = workspace
local stop = item.start(platform, a, b, 8)
local align = platform:FindFirstChildOfClass("AlignPosition")
check("platform becomes physical and server owned", not platform.Anchored and platform:GetNetworkOwner() == nil)
__frames(120, 1 / 60)
check("target follows the schedule", align ~= nil and math.abs(align.Position.Z - 20) < 0.5)
stop()
check("stop removes the constraints and re-anchors", platform:FindFirstChildOfClass("AlignPosition") == nil and platform.Anchored)
```
