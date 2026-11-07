---
id: gb-ui-ability-cooldown-overlay
category: ui-interaction
topics: cooldown overlay, Heartbeat, ability button, countdown text, progress
source: original
---
# Request
I want my ability buttons to show a dark overlay that shrinks from top to bottom while the ability recharges, with the seconds left in the middle. Right now I use a while loop with `task.wait(0.1)` per button and it stutters and sometimes keeps running after the cooldown ends.

# Answer
Compute everything from the start time: remaining fraction = 1 - elapsed / duration. One Heartbeat connection per active cooldown sets the overlay height and text each frame and disconnects itself at zero, so nothing keeps running. Restarting mid-cooldown replaces the old connection.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.CooldownOverlay
local RunService = game:GetService("RunService")

local CooldownOverlay = {}

export type Overlay = {
	start: (duration: number) -> (),
	isActive: () -> boolean,
}

function CooldownOverlay.remaining(now: number, startedAt: number, duration: number): number
	if duration <= 0 then
		return 0
	end
	return math.clamp(1 - (now - startedAt) / duration, 0, 1)
end

function CooldownOverlay.attach(button: GuiButton): Overlay
	local baseZ: number = button.ZIndex
	local shade = Instance.new("Frame")
	shade.Name = "CooldownShade"
	shade.AnchorPoint = Vector2.new(0, 1)
	shade.Position = UDim2.fromScale(0, 1)
	shade.Size = UDim2.fromScale(1, 0)
	shade.BackgroundColor3 = Color3.new(0, 0, 0)
	shade.BackgroundTransparency = 0.4
	shade.ZIndex = baseZ + 1
	shade.Parent = button

	local label = Instance.new("TextLabel")
	label.Name = "Seconds"
	label.BackgroundTransparency = 1
	label.Size = UDim2.fromScale(1, 1)
	label.TextScaled = true
	label.TextColor3 = Color3.new(1, 1, 1)
	label.ZIndex = baseZ + 2
	label.Text = ""
	label.Parent = button

	local connection: RBXScriptConnection? = nil

	local function finish()
		if connection then
			connection:Disconnect()
			connection = nil
		end
		shade.Size = UDim2.fromScale(1, 0)
		label.Text = ""
	end

	local function start(duration: number)
		finish()
		local startedAt = os.clock()
		local function step()
			local left = CooldownOverlay.remaining(os.clock(), startedAt, duration)
			if left <= 0 then
				finish()
				return
			end
			shade.Size = UDim2.fromScale(1, left)
			label.Text = tostring(math.ceil(left * duration))
		end
		connection = RunService.Heartbeat:Connect(step)
		step()
	end

	return {
		start = start,
		isActive = function()
			return connection ~= nil
		end,
	}
end

return CooldownOverlay
```

- The shade is anchored at the bottom, so shrinking its height makes it recede downward as the ability fills back up.
- `math.ceil` shows "1" during the last second instead of "0" while it is still unusable.
- The overlay is display only; the server keeps its own cooldown per player and rejects early activations.

# Test
```lua
check("full at start", item.remaining(10, 10, 4) == 1)
check("half way", item.remaining(12, 10, 4) == 0.5)
check("never below zero", item.remaining(20, 10, 4) == 0)
local button = Instance.new("TextButton")
local overlay = item.attach(button)
overlay.start(2)
check("shade covers the button at start", button.CooldownShade.Size.Y.Scale == 1 and button.Seconds.Text == "2")
__frames(66, 1 / 60)
check("partly recharged after 1.1 seconds", math.abs(button.CooldownShade.Size.Y.Scale - 0.45) < 0.02 and button.Seconds.Text == "1")
__frames(70, 1 / 60)
check("finished and stopped", not overlay.isActive() and button.CooldownShade.Size.Y.Scale == 0 and button.Seconds.Text == "")
overlay.start(3)
overlay.start(1)
__frames(70, 1 / 60)
check("restart replaces the old cooldown", not overlay.isActive() and button.CooldownShade.Size.Y.Scale == 0)
```
