---
id: gb-src-streaming-tagged-flicker
category: performance-streaming
topics: StreamingEnabled, CollectionService, GetInstanceAddedSignal, GetInstanceRemovedSignal, client effects
source: adapted
source_id: creator-docs
source_path: content/en-us/workspace/streaming/techniques.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I turned on StreamingEnabled and my client script that flickers all the torch lights broke: it does `for _, light in workspace.Torches:GetDescendants()` once at start and only finds the nearby ones, then errors on lights that streamed out. How should client effects find streamed parts?

# Answer
Tag the lights and track them with CollectionService on the client: `GetTagged` returns the ones streamed in now, and the added/removed signals fire as instances stream in and out. Keep a set and only touch what is in it.

```lua
--!strict
local CollectionService = game:GetService("CollectionService")
local RunService = game:GetService("RunService")

local TAG = "FlickerLight"
local BASE_BRIGHTNESS = 8
local JITTER = 0.4
local INTERVAL = 0.05

local Flicker = {}

function Flicker.start(): () -> ()
	local active: { [Instance]: boolean } = {}
	local random = Random.new()
	local elapsed = 0

	for _, light in CollectionService:GetTagged(TAG) do
		active[light] = true
	end
	local added = CollectionService:GetInstanceAddedSignal(TAG):Connect(function(light: Instance)
		active[light] = true
	end)
	local removed = CollectionService:GetInstanceRemovedSignal(TAG):Connect(function(light: Instance)
		active[light] = nil
	end)

	local heartbeat = RunService.Heartbeat:Connect(function(dt: number)
		elapsed += dt
		if elapsed < INTERVAL then
			return
		end
		elapsed = 0
		for light in active do
			if light:IsA("Light") then
				light.Brightness = BASE_BRIGHTNESS + random:NextNumber(-JITTER, JITTER)
			end
		end
	end)

	return function()
		added:Disconnect()
		removed:Disconnect()
		heartbeat:Disconnect()
		table.clear(active)
	end
end

return Flicker
```

- An instance that streams out fires the removed signal, so the loop never writes to a light that is gone; streaming back in fires added again.
- Never index deep paths like `workspace.Torches.Torch12` on the client with streaming on; use tags, `WaitForChild`, or `FindFirstChild` with nil checks.
- Running this on the client keeps a purely cosmetic effect off the network.

# Test
```lua
local CollectionService = game:GetService("CollectionService")
local near = Instance.new("PointLight")
near.Parent = workspace
CollectionService:AddTag(near, "FlickerLight")
local stop = item.start()
__frames(5, 0.02)
check("existing tagged light flickers", near.Brightness ~= 0 and math.abs(near.Brightness - 8) <= 0.4)
local streamedIn = Instance.new("PointLight")
streamedIn.Parent = workspace
CollectionService:AddTag(streamedIn, "FlickerLight")
__frames(5, 0.02)
check("light that streams in is picked up", math.abs(streamedIn.Brightness - 8) <= 0.4)
CollectionService:RemoveTag(near, "FlickerLight")
near.Brightness = 1
__frames(5, 0.02)
check("removed light no longer touched", near.Brightness == 1)
stop()
streamedIn.Brightness = 1
__frames(5, 0.02)
check("stop disconnects", streamedIn.Brightness == 1)
```
