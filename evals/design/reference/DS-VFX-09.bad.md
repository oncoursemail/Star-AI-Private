```luau
local Debris = game:GetService("Debris")
local function play(part)
	for i = 1, 8 do
		local e = Instance.new("ParticleEmitter")
		e.Rate = 600
		e.Lifetime = NumberRange.new(2, 25)
		e.Size = NumberSequence.new(30)
		e.LightEmission = 1
		e.Color = ColorSequence.new(Color3.fromRGB(255, 0, 0), Color3.fromRGB(0, 255, 0))
		e.Enabled = true
		e.Parent = part
		e:Emit(500)
	end
	local bloom = Instance.new("BloomEffect")
	bloom.Intensity = 3
	bloom.Threshold = 0.5
	bloom.Parent = game:GetService("Lighting")
	Debris:AddItem(part, 60)
end
return play
```
