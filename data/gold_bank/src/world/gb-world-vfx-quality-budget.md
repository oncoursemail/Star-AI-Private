---
id: gb-world-vfx-quality-budget
category: vfx-particles
topics: ParticleEmitter Rate, graphics quality, distance culling, performance, mobile
source: original
---
# Request
My map has around 60 torches and campfires with ParticleEmitters and phones drop to 30 FPS. I'd like particle rates to go down with the player's graphics setting and with distance from the camera, and turn off completely far away. How would you do it?

# Answer
Compute one scale factor per effect from distance and quality, and apply it to each emitter's rate relative to the rate you authored (stored once in an attribute so repeated updates never compound). A LocalScript refreshes the scales twice a second, which is plenty for ambient effects.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.EffectBudget
local EffectBudget = {}

-- qualityLevel is the graphics slider (1-10); 0 means the player left it on Automatic.
function EffectBudget.scale(distance: number, qualityLevel: number, fullRange: number, cullRange: number): number
	if distance >= cullRange then
		return 0
	end
	local level = if qualityLevel <= 0 then 6 else math.clamp(qualityLevel, 1, 10)
	local falloff = 1
	if distance > fullRange then
		falloff = 1 - (distance - fullRange) / (cullRange - fullRange)
	end
	return (level / 10) * falloff
end

function EffectBudget.apply(effect: Instance, scale: number)
	for _, emitter in effect:GetDescendants() do
		if emitter:IsA("ParticleEmitter") then
			if emitter:GetAttribute("BaseRate") == nil then
				emitter:SetAttribute("BaseRate", emitter.Rate)
			end
			local base = emitter:GetAttribute("BaseRate")
			if type(base) == "number" then
				emitter.Rate = base * scale
				emitter.Enabled = scale > 0
			end
		end
	end
end

return EffectBudget
```

The LocalScript, using a CollectionService tag on each torch's effect container:

```lua
--!strict
local CollectionService = game:GetService("CollectionService")
local EffectBudget = require(game:GetService("ReplicatedStorage"):WaitForChild("EffectBudget"))

local camera = workspace.CurrentCamera
local gameSettings = UserSettings():GetService("UserGameSettings")

while true do
	local quality = gameSettings.SavedQualityLevel.Value
	local cameraPosition = camera.CFrame.Position
	for _, effect in CollectionService:GetTagged("AmbientEffect") do
		if effect:IsA("BasePart") then
			local distance = (effect.Position - cameraPosition).Magnitude
			EffectBudget.apply(effect, EffectBudget.scale(distance, quality, 40, 160))
		end
	end
	task.wait(0.5)
end
```

- At scale 0 the emitter is disabled, and particles already in the air finish their lifetime instead of vanishing when a player walks away.
- Reading the authored rate from an attribute means designers keep tuning `Rate` in Studio as usual, and the script never drifts it.
- With StreamingEnabled, far torches may not exist on the client at all; the loop only touches what is currently tagged and streamed in.

# Test
```lua
check("full detail near, max quality", item.scale(10, 10, 40, 160) == 1)
check("culled past the cull range", item.scale(200, 10, 40, 160) == 0)
check("linear falloff between ranges", math.abs(item.scale(100, 10, 40, 160) - 0.5) < 1e-9)
check("automatic quality uses a middle level", math.abs(item.scale(0, 0, 40, 160) - 0.6) < 1e-9)

local torch = Instance.new("Part")
local fire = Instance.new("ParticleEmitter")
fire.Rate = 40
fire.Parent = torch
item.apply(torch, 0.5)
check("rate scaled from the authored value", fire.Rate == 20 and fire:GetAttribute("BaseRate") == 40)
item.apply(torch, 0.5)
check("repeated updates do not compound", fire.Rate == 20)
item.apply(torch, 0)
check("zero scale disables the emitter", fire.Enabled == false)
item.apply(torch, 1)
check("scale back up restores it", fire.Enabled == true and fire.Rate == 40)
```
