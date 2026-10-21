---
id: gb-ui-hold-to-confirm-delete
category: ui-interaction
topics: hold to confirm, destructive action, progress fill, Heartbeat, MouseButton1Down
source: original
---
# Request
Deleting a pet is permanent, and a confirm popup still gets clicked through by accident. I'd like a "hold to delete" button: you hold for 1.5 seconds while a bar fills, letting go early cancels. How do I build that?

# Answer
Track the press start time; while held, a Heartbeat connection fills the bar from elapsed / hold time and fires the action once it reaches 1. Releasing or sliding off the button cancels and empties the bar. The action fires exactly once per hold.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.HoldButton
local RunService = game:GetService("RunService")

local HoldButton = {}

export type Hold = { progress: () -> number, destroy: () -> () }

function HoldButton.attach(button: GuiButton, holdSeconds: number, onConfirm: () -> ()): Hold
	assert(holdSeconds > 0, "holdSeconds must be positive")
	local baseZ: number = button.ZIndex
	local fill = Instance.new("Frame")
	fill.Name = "HoldFill"
	fill.Size = UDim2.fromScale(0, 1)
	fill.BackgroundColor3 = Color3.fromRGB(205, 64, 64)
	fill.BackgroundTransparency = 0.25
	fill.ZIndex = baseZ + 1
	fill.Parent = button

	local progress = 0
	local heartbeat: RBXScriptConnection? = nil

	local function reset()
		if heartbeat then
			heartbeat:Disconnect()
			heartbeat = nil
		end
		progress = 0
		fill.Size = UDim2.fromScale(0, 1)
	end

	local function begin()
		reset()
		local startedAt = os.clock()
		heartbeat = RunService.Heartbeat:Connect(function()
			progress = math.min((os.clock() - startedAt) / holdSeconds, 1)
			fill.Size = UDim2.fromScale(progress, 1)
			if progress >= 1 then
				reset()
				onConfirm()
			end
		end)
	end

	local connections = {
		button.MouseButton1Down:Connect(begin),
		button.MouseButton1Up:Connect(reset),
		button.MouseLeave:Connect(reset),
	}

	return {
		progress = function()
			return progress
		end,
		destroy = function()
			reset()
			for _, connection in connections do
				connection:Disconnect()
			end
			fill:Destroy()
		end,
	}
end

return HoldButton
```

- `MouseButton1Down` and `MouseButton1Up` also fire for touch, so the same code works on phones.
- Resetting before calling `onConfirm` means a slow handler cannot be triggered twice by the same hold.
- Show the hold time on the label ("Hold to delete") so players know a tap will not work.
- The server still checks that the player owns the pet before deleting it.

# Test
```lua
local button = Instance.new("TextButton")
local confirmed = 0
local hold = item.attach(button, 1.5, function()
	confirmed += 1
end)
button.MouseButton1Down:Fire()
__frames(45, 1 / 60)
check("bar fills while held", hold.progress() > 0.45 and hold.progress() < 0.55 and confirmed == 0)
button.MouseButton1Up:Fire()
check("early release cancels", hold.progress() == 0 and button.HoldFill.Size.X.Scale == 0)
__frames(120, 1 / 60)
check("nothing fires after cancelling", confirmed == 0)
button.MouseButton1Down:Fire()
__frames(100, 1 / 60)
check("full hold confirms once", confirmed == 1)
__frames(100, 1 / 60)
check("does not repeat while still held", confirmed == 1)
button.MouseButton1Down:Fire()
__frames(30, 1 / 60)
button.MouseLeave:Fire()
check("sliding off cancels", hold.progress() == 0)
```
