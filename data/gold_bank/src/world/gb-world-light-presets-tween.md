---
id: gb-world-light-presets-tween
category: building-lighting
topics: Lighting presets, Atmosphere, BloomEffect, TweenService, weather
source: original
---
# Request
My game has weather (clear, sunset, storm) and I want the lighting, atmosphere and bloom to blend smoothly into each preset over a few seconds. If the weather changes again mid-blend it should not fight the old transition.

# Answer
Describe each preset as property tables per object (Lighting, Atmosphere, BloomEffect), make sure those objects exist, and tween each table with one TweenInfo. Cancel the running tweens before starting new ones so a quick weather change blends from wherever the scene currently is.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.LightingPresets
local Lighting = game:GetService("Lighting")
local TweenService = game:GetService("TweenService")

export type Preset = {
	lighting: { [string]: any },
	atmosphere: { [string]: any },
	bloom: { [string]: any },
}

local LightingPresets = {}

LightingPresets.presets = {
	Clear = {
		lighting = { Brightness = 3, Ambient = Color3.fromRGB(110, 110, 120), ExposureCompensation = 0 },
		atmosphere = { Density = 0.3, Haze = 0.5, Color = Color3.fromRGB(199, 210, 225) },
		bloom = { Intensity = 0.4, Threshold = 1.2 },
	},
	Sunset = {
		lighting = { Brightness = 2, Ambient = Color3.fromRGB(120, 85, 70), ExposureCompensation = 0.2 },
		atmosphere = { Density = 0.38, Haze = 2, Color = Color3.fromRGB(255, 170, 120) },
		bloom = { Intensity = 0.8, Threshold = 0.9 },
	},
	Storm = {
		lighting = { Brightness = 0.8, Ambient = Color3.fromRGB(60, 65, 75), ExposureCompensation = -0.4 },
		atmosphere = { Density = 0.55, Haze = 3, Color = Color3.fromRGB(120, 125, 135) },
		bloom = { Intensity = 0.2, Threshold = 1.5 },
	},
} :: { [string]: Preset }

local active: { Tween } = {}

local function ensure(className: string): Instance
	local existing = Lighting:FindFirstChildOfClass(className)
	if existing then
		return existing
	end
	local created = Instance.new(className)
	created.Parent = Lighting
	return created
end

function LightingPresets.apply(name: string, duration: number): { Tween }
	local preset = LightingPresets.presets[name]
	assert(preset, string.format("unknown lighting preset %s", name))
	for _, tween in active do
		tween:Cancel()
	end
	local info = TweenInfo.new(duration, Enum.EasingStyle.Sine, Enum.EasingDirection.InOut)
	active = {
		TweenService:Create(Lighting, info, preset.lighting),
		TweenService:Create(ensure("Atmosphere"), info, preset.atmosphere),
		TweenService:Create(ensure("BloomEffect"), info, preset.bloom),
	}
	for _, tween in active do
		tween:Play()
	end
	return active
end

return LightingPresets
```

- Tweens start from the current property values, so cancelling and starting a new set mid-blend continues smoothly from the half-blended look.
- Keep `ClockTime` out of presets: tweening it from 23 to 1 goes the long way round through the whole day; drive time separately.
- Run this on the client when the server announces the weather (an attribute on ReplicatedStorage works well), so each player gets smooth frames and the server sends one value.

# Test
```lua
local Lighting = game:GetService("Lighting")
Lighting.Brightness = 3
local tweens = item.apply("Sunset", 2)
check("atmosphere and bloom are created", Lighting:FindFirstChildOfClass("Atmosphere") ~= nil and Lighting:FindFirstChildOfClass("BloomEffect") ~= nil)
check("three tweens play", #tweens == 3 and tweens[1].PlaybackState == Enum.PlaybackState.Playing)
__advance(1)
local storm = item.apply("Storm", 2)
check("changing mid-blend cancels the old tweens", tweens[1].PlaybackState == Enum.PlaybackState.Cancelled)
__advance(2.1)
check("storm values reached", Lighting.Brightness == 0.8 and Lighting.Atmosphere.Haze == 3)
check("cancelled sunset never lands", Lighting.BloomEffect.Intensity == 0.2 and storm[3].PlaybackState == Enum.PlaybackState.Completed)
item.apply("Clear", 1)
local count = 0
for _, child in Lighting:GetChildren() do
	if child:IsA("Atmosphere") then
		count += 1
	end
end
check("existing effects are reused", count == 1)
check("unknown preset errors", not pcall(item.apply, "Blizzard", 1))
```
