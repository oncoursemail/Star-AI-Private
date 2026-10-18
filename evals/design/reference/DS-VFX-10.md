```luau
local Debris = game:GetService("Debris")

local HOT = Color3.fromRGB(255, 236, 200)
local BODY = Color3.fromRGB(31, 120, 160)
local DARK = Color3.fromRGB(70, 66, 60)

local function emitter(parent: Attachment, color: Color3, light: number): ParticleEmitter
	local e = Instance.new("ParticleEmitter")
	e.Rate = 0
	e.Enabled = false
	e.LightEmission = light
	e.Color = ColorSequence.new(color)
	e.Parent = parent
	return e
end

-- campfire: plays when a campfire burning
local function play(at: Attachment)
	local flash = emitter(at, HOT, 1)
	flash.Lifetime = NumberRange.new(0.06, 0.1)
	flash.Size = NumberSequence.new({NumberSequenceKeypoint.new(0, 1), NumberSequenceKeypoint.new(1, 5)})
	flash.Transparency = NumberSequence.new({NumberSequenceKeypoint.new(0, 0.2), NumberSequenceKeypoint.new(1, 1)})

	local splash = emitter(at, BODY, 0.3)
	splash.Lifetime = NumberRange.new(0.4, 0.8)
	splash.Speed = NumberRange.new(10, 18)
	splash.SpreadAngle = Vector2.new(40, 40)
	splash.Acceleration = Vector3.new(0, -35, 0)
	splash.Size = NumberSequence.new({NumberSequenceKeypoint.new(0, 0.6), NumberSequenceKeypoint.new(1, 0.1)})
	splash.Transparency = NumberSequence.new({NumberSequenceKeypoint.new(0, 0), NumberSequenceKeypoint.new(1, 1)})

	local haze = emitter(at, DARK, 0)
	haze.Lifetime = NumberRange.new(1.0, 1.6)
	haze.Speed = NumberRange.new(1, 2)
	haze.Size = NumberSequence.new({NumberSequenceKeypoint.new(0, 2), NumberSequenceKeypoint.new(1, 6)})
	haze.Transparency = NumberSequence.new({NumberSequenceKeypoint.new(0, 0.6), NumberSequenceKeypoint.new(1, 1)})

	flash:Emit(1)          -- anticipation: a small flash
	task.wait(0.04)
	splash:Emit(28)        -- impact: the fire
	haze:Emit(5)           -- aftermath: slow haze that grows and fades
	Debris:AddItem(at, 2.5)
end

return play
```
