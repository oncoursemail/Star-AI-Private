---
id: gb-eng-stream-tagged-lights-client
category: performance-streaming
topics: StreamingEnabled, CollectionService, stream in, stream out, client effects
source: original
---
# Request
With StreamingEnabled on, my client script that makes all street lamps flicker only affects the lamps near spawn, and errors later when some of those lamps stream out. It does `for _, lamp in workspace.Lamps:GetChildren()` once at startup. How should client code handle parts that come and go?

# Answer
Assume any workspace instance can appear later and disappear at any time. Tag the lamps, handle both `GetTagged` (already streamed in) and `GetInstanceAddedSignal` (streams in later), and clean up per lamp on `GetInstanceRemovedSignal`, which also fires when a lamp streams out.

```lua
--!strict
-- ModuleScript: StarterPlayer.StarterPlayerScripts.LampFlicker
local CollectionService = game:GetService("CollectionService")

local TAG = "StreetLamp"

local LampFlicker = {}

local active: { [Instance]: thread } = {}

local function startLamp(lamp: Instance, rng: Random)
	if active[lamp] then
		return
	end
	local light = lamp:FindFirstChildWhichIsA("Light", true)
	if light == nil then
		return
	end
	local base = light.Brightness
	active[lamp] = task.spawn(function()
		while true do
			task.wait(rng:NextNumber(0.05, 0.4))
			light.Brightness = base * rng:NextNumber(0.4, 1)
		end
	end)
end

local function stopLamp(lamp: Instance)
	local thread = active[lamp]
	if thread then
		task.cancel(thread)
		active[lamp] = nil
	end
end

function LampFlicker.start(rng: Random?): () -> ()
	local random = rng or Random.new()
	local added = CollectionService:GetInstanceAddedSignal(TAG):Connect(function(lamp: Instance)
		startLamp(lamp, random)
	end)
	local removed = CollectionService:GetInstanceRemovedSignal(TAG):Connect(stopLamp)
	for _, lamp in CollectionService:GetTagged(TAG) do
		startLamp(lamp, random)
	end
	return function()
		added:Disconnect()
		removed:Disconnect()
		for lamp in active do
			stopLamp(lamp)
		end
	end
end

function LampFlicker.activeCount(): number
	local n = 0
	for _ in active do
		n += 1
	end
	return n
end

return LampFlicker
```

- Streamed-out instances are removed from the client's DataModel, so references to them go stale; the removed signal is the cue to drop threads and connections for that lamp.
- When a lamp streams back in, the client gets a new copy, which triggers the added signal again and starts fresh.
- Tags replicate with the instance, so the same code works with streaming on or off; with it off, the added signal simply never fires after startup.
- Set the lamp models' `ModelStreamingMode` to `Atomic` (or tag the bulb part instead of the model): a non-atomic Model can be on the client while its parts are streamed out, so a tagged model could arrive without its light and never flicker.

# Test
```lua
__setClient(true)
local function lamp(name)
	local model = Instance.new("Model")
	model.Name = name
	local bulb = Instance.new("Part")
	bulb.Parent = model
	local light = Instance.new("PointLight")
	light.Brightness = 2
	light.Parent = bulb
	model.Parent = workspace
	model:AddTag("StreetLamp")
	return model, light
end
local near, nearLight = lamp("Near")
local stop = item.start(Random.new(5))
check("already streamed-in lamp started", item.activeCount() == 1)
__advance(1)
check("flicker changes brightness", nearLight.Brightness < 2 and nearLight.Brightness >= 0.8)
local far = lamp("Far")
check("lamp streaming in later is picked up", item.activeCount() == 2)
far:RemoveTag("StreetLamp")
far:Destroy()
check("lamp streaming out is cleaned up", item.activeCount() == 1)
stop()
check("stop cleans everything", item.activeCount() == 0)
local brightness = nearLight.Brightness
__advance(2)
check("no flicker after stop", nearLight.Brightness == brightness)
```
