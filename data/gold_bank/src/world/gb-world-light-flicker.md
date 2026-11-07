---
id: gb-world-light-flicker
category: building-lighting
topics: flickering light, PointLight, Random, horror, client effect
source: original
---
# Request
For my horror map I want some ceiling lights to flicker: mostly on, with random quick dropouts, and each light flickering differently. When a light gets destroyed (rooms unload) the flicker should stop on its own. Ideas?

# Answer
Run one lightweight loop per light on the client: each step either holds near full brightness for a while or drops out briefly, chosen with that light's own `Random`. The loop exits when the light leaves the game or when the returned stop function is called, and restores the original brightness when stopped.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.LightFlicker
local LightFlicker = {}

function LightFlicker.start(light: Light, seed: number, dropoutChance: number?): () -> ()
	local base = light.Brightness
	local chance = dropoutChance or 0.15
	local random = Random.new(seed)
	local running = true

	task.spawn(function()
		while running and light.Parent ~= nil do
			if random:NextNumber() < chance then
				light.Brightness = base * random:NextNumber(0, 0.25)
				task.wait(random:NextNumber(0.04, 0.12))
			else
				light.Brightness = base * random:NextNumber(0.85, 1)
				task.wait(random:NextNumber(0.15, 0.6))
			end
		end
		if light.Parent ~= nil then
			light.Brightness = base
		end
	end)

	return function()
		running = false
	end
end

return LightFlicker
```

Starting every tagged light with its own seed, in a LocalScript:

```lua
--!strict
local CollectionService = game:GetService("CollectionService")
local LightFlicker = require(game:GetService("ReplicatedStorage"):WaitForChild("LightFlicker"))

local stops: { [Instance]: () -> () } = {}

local function onAdded(light: Instance)
	if light:IsA("Light") then
		stops[light] = LightFlicker.start(light, math.random(1, 1e6))
	end
end

CollectionService:GetInstanceAddedSignal("FlickerLight"):Connect(onAdded)
CollectionService:GetInstanceRemovedSignal("FlickerLight"):Connect(function(light: Instance)
	local stop = stops[light]
	if stop then
		stop()
		stops[light] = nil
	end
end)
for _, light in CollectionService:GetTagged("FlickerLight") do
	onAdded(light)
end
```

- Per-light seeds keep neighbouring lights out of sync, which reads far more natural than one shared pattern.
- The loop yields every step, so dozens of flickering lights cost a handful of property writes per second each.
- Doing it on the client keeps the server from replicating brightness changes; every player sees a different flicker, which is fine for ambience.

# Test
```lua
local part = Instance.new("Part")
part.Parent = workspace
local light = Instance.new("PointLight")
light.Brightness = 2
light.Parent = part
local samples = {}
light:GetPropertyChangedSignal("Brightness"):Connect(function()
	table.insert(samples, light.Brightness)
end)
local stop = item.start(light, 7, 0.3)
__advance(10)
local inRange, dropped = true, false
for _, b in samples do
	if b < 0 or b > 2 then inRange = false end
	if b <= 0.5 then dropped = true end
end
check("brightness keeps changing", #samples > 15)
check("values stay between off and base", inRange)
check("dropouts happen", dropped)
stop()
__advance(1)
check("stop restores the base brightness", light.Brightness == 2)

local other = Instance.new("PointLight")
other.Parent = part
item.start(other, 3)
other:Destroy()
__advance(2)
check("destroyed light ends its loop quietly", other.Parent == nil)
```
