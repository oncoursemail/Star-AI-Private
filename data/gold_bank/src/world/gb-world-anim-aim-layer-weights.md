---
id: gb-world-anim-aim-layer-weights
category: animation
topics: AnimationPriority, AdjustWeight, blending, aim pose, layers
source: original
---
# Request
I made three upper-body poses for my bow: aiming up, level and down. How do I blend between them based on where the camera is looking, while the legs keep using the normal walk animation?

# Answer
Play all three as looping Action-priority tracks and drive their weights from the camera pitch, so exactly two neighbouring poses share the blend at any time. Because the poses only key upper-body joints, the walk animation (Movement priority) still owns the legs.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.AimLayer
export type AimAnimations = { up: Animation, level: Animation, down: Animation }
export type AimLayer = {
	setPitch: (pitchDegrees: number) -> (),
	stopLayer: () -> (),
}

local AimLayer = {}

-- Returns the weights for (up, level, down); they always sum to 1.
function AimLayer.weights(pitchDegrees: number, maxPitch: number): (number, number, number)
	local t = math.clamp(pitchDegrees / maxPitch, -1, 1)
	if t >= 0 then
		return t, 1 - t, 0
	end
	return 0, 1 + t, -t
end

function AimLayer.new(animator: Animator, animations: AimAnimations, maxPitch: number?): AimLayer
	local limit = maxPitch or 70
	local up = animator:LoadAnimation(animations.up)
	local level = animator:LoadAnimation(animations.level)
	local down = animator:LoadAnimation(animations.down)
	for _, track in { up, level, down } do
		track.Priority = Enum.AnimationPriority.Action
		track.Looped = true
	end
	up:Play(0.2, 0.001)
	level:Play(0.2, 1)
	down:Play(0.2, 0.001)

	return {
		setPitch = function(pitchDegrees: number)
			local wUp, wLevel, wDown = AimLayer.weights(pitchDegrees, limit)
			-- A tiny floor keeps every track alive in the blend instead of dropping out at 0.
			up:AdjustWeight(math.max(wUp, 0.001), 0.1)
			level:AdjustWeight(math.max(wLevel, 0.001), 0.1)
			down:AdjustWeight(math.max(wDown, 0.001), 0.1)
		end,
		stopLayer = function()
			up:Stop(0.2)
			level:Stop(0.2)
			down:Stop(0.2)
		end,
	}
end

return AimLayer
```

Feeding it from the camera in a LocalScript while the bow is drawn:

```lua
--!strict
local RunService = game:GetService("RunService")
local AimLayer = require(game:GetService("ReplicatedStorage"):WaitForChild("AimLayer"))

local camera = workspace.CurrentCamera
local animator = script.Parent:WaitForChild("Humanoid"):WaitForChild("Animator")
local layer = AimLayer.new(animator, {
	up = script:WaitForChild("AimUp"),
	level = script:WaitForChild("AimLevel"),
	down = script:WaitForChild("AimDown"),
})

RunService.RenderStepped:Connect(function()
	layer.setPitch(math.deg(math.asin(camera.CFrame.LookVector.Y)))
end)
```

- Weights of tracks at the same priority blend proportionally, so keeping the sum at 1 avoids the pose looking weaker at the extremes.
- Only key the spine, arms and head in the aim poses; any key on a leg joint would override the walk because Action beats Movement.
- The fade argument of `AdjustWeight` smooths sudden camera flicks without extra code.

# Test
```lua
local u, l, d = item.weights(0, 70)
check("level pitch is all level", u == 0 and l == 1 and d == 0)
u, l, d = item.weights(35, 70)
check("half up splits up and level", math.abs(u - 0.5) < 1e-9 and math.abs(l - 0.5) < 1e-9 and d == 0)
u, l, d = item.weights(-500, 70)
check("pitch is clamped", u == 0 and l == 0 and d == 1)

local rig = __buildRig()
local animator = rig.Humanoid.Animator
local layer = item.new(animator, { up = Instance.new("Animation"), level = Instance.new("Animation"), down = Instance.new("Animation") }, 60)
local tracks = animator.__tracks
layer.setPitch(60)
check("full up weight on the up track", tracks[1].WeightCurrent == 1 and tracks[2].WeightCurrent == 0.001)
check("tracks use Action priority", tracks[1].Priority == Enum.AnimationPriority.Action and tracks[3].Looped)
layer.stopLayer()
check("stop ends all three", #animator:GetPlayingAnimationTracks() == 0)
```
