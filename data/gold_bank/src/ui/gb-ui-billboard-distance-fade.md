---
id: gb-ui-billboard-distance-fade
category: ui-layout
topics: BillboardGui, distance fade, camera distance, throttled update, world labels
source: original
---
# Request
My shop stall labels are BillboardGuis with MaxDistance = 60, and they pop out of existence when you walk away. I'd like them to fade out smoothly between 40 and 60 studs instead. What's an efficient way with lots of labels?

# Answer
Compute an alpha from the camera distance (0 inside the fade start, 1 at the fade end) and drive the labels' transparency with it. Update all labels from one loop a few times per second rather than one connection per label per frame, and keep MaxDistance as the hard cut-off for rendering.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.DistanceFade
local RunService = game:GetService("RunService")

local DistanceFade = {}

function DistanceFade.alpha(distance: number, fadeStart: number, fadeEnd: number): number
	if distance <= fadeStart then
		return 0
	elseif distance >= fadeEnd then
		return 1
	end
	return (distance - fadeStart) / (fadeEnd - fadeStart)
end

export type Fader = { add: (gui: BillboardGui, label: TextLabel) -> (), stop: () -> () }

function DistanceFade.start(fadeStart: number, fadeEnd: number, interval: number?): Fader
	local entries: { [BillboardGui]: TextLabel } = {}
	local every = interval or 0.1
	local elapsed = every

	local connection = RunService.Heartbeat:Connect(function(dt: number)
		elapsed += dt
		if elapsed < every then
			return
		end
		elapsed = 0
		local camera = workspace.CurrentCamera
		if camera == nil then
			return
		end
		local eye: Vector3 = camera.CFrame.Position
		for gui, label in entries do
			local adornee = gui.Adornee
			if gui.Parent == nil or adornee == nil then
				entries[gui] = nil
				continue
			end
			local where: Vector3 = adornee.Position
			local a = DistanceFade.alpha((where - eye).Magnitude, fadeStart, fadeEnd)
			label.TextTransparency = a
			label.TextStrokeTransparency = 0.5 + a * 0.5
		end
	end)

	return {
		add = function(gui: BillboardGui, label: TextLabel)
			gui.MaxDistance = fadeEnd
			entries[gui] = label
		end,
		stop = function()
			connection:Disconnect()
		end,
	}
end

return DistanceFade
```

- Ten updates per second is smooth enough for a fade and costs a tenth of a per-frame loop.
- Entries whose gui was destroyed or lost its adornee are dropped during the loop, so the table does not grow forever.
- Setting MaxDistance to the fade end means the engine stops drawing exactly where the label becomes invisible.

# Test
```lua
check("opaque when close", item.alpha(10, 40, 60) == 0)
check("half way through the fade", item.alpha(50, 40, 60) == 0.5)
check("gone past the end", item.alpha(80, 40, 60) == 1)
local camera = workspace.CurrentCamera
camera.CFrame = CFrame.new(0, 0, 0)
local stall = Instance.new("Part")
stall.Position = Vector3.new(50, 0, 0)
stall.Parent = workspace
local gui = Instance.new("BillboardGui")
gui.Adornee = stall
gui.Parent = stall
local label = Instance.new("TextLabel")
label.Parent = gui
local fader = item.start(40, 60)
fader.add(gui, label)
__frames(10, 1 / 60)
check("label faded by distance", math.abs(label.TextTransparency - 0.5) < 1e-6)
check("hard cut-off matches the fade end", gui.MaxDistance == 60)
stall.Position = Vector3.new(20, 0, 0)
__frames(10, 1 / 60)
check("walking closer makes it opaque", label.TextTransparency == 0)
fader.stop()
```
