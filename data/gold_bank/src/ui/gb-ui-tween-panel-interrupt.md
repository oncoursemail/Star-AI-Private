---
id: gb-ui-tween-panel-interrupt
category: ui-style
topics: TweenService, interruption, Cancel, open close animation, Completed
source: original
---
# Request
My inventory slides in and out with TweenService. If you press the key twice quickly, the panel ends up invisible while open, or stuck halfway. Here is what I do:

```lua
local function close()
	TweenService:Create(panel, info, { Position = hidden }):Play()
	task.wait(0.3)
	panel.Visible = false
end
```

# Answer
The `task.wait` runs even if the player reopened the panel meanwhile, so it hides an open panel. Keep a handle to the running tween, cancel it before starting the next one, and only run the "hide after closing" step from that tween's own `Completed` when it finished normally and is still the current one.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.SlidePanel
local TweenService = game:GetService("TweenService")

local SlidePanel = {}

export type Panel = {
	open: () -> (),
	close: () -> (),
	toggle: () -> (),
	isOpen: () -> boolean,
}

function SlidePanel.new(frame: GuiObject, shown: UDim2, hidden: UDim2, duration: number?): Panel
	local info = TweenInfo.new(duration or 0.25, Enum.EasingStyle.Quad, Enum.EasingDirection.Out)
	local current: Tween? = nil
	local opened = false

	frame.Position = hidden
	frame.Visible = false

	local function animate(goal: UDim2, after: (() -> ())?)
		if current then
			current:Cancel()
		end
		local tween = TweenService:Create(frame, info, { Position = goal })
		current = tween
		tween.Completed:Connect(function(state: Enum.PlaybackState)
			if state ~= Enum.PlaybackState.Completed or current ~= tween then
				return
			end
			current = nil
			if after then
				after()
			end
		end)
		tween:Play()
	end

	local function open()
		opened = true
		frame.Visible = true
		animate(shown)
	end

	local function close()
		opened = false
		animate(hidden, function()
			frame.Visible = false
		end)
	end

	return {
		open = open,
		close = close,
		toggle = function()
			if opened then
				close()
			else
				open()
			end
		end,
		isOpen = function()
			return opened
		end,
	}
end

return SlidePanel
```

- A new tween starts from the frame's current position, so reversing mid-slide continues smoothly from where it is.
- `Cancel` fires `Completed` with `Cancelled`; the state check is what stops a cancelled close from hiding the panel.
- `opened` changes immediately on input, so game logic (blocking movement, pausing) does not wait for the animation.

# Test
```lua
local frame = Instance.new("Frame")
local shown, hidden = UDim2.fromScale(0.5, 0.5), UDim2.fromScale(0.5, 1.5)
local panel = item.new(frame, shown, hidden, 0.3)
check("starts hidden", frame.Visible == false and frame.Position == hidden)
panel.open()
__advance(0.1)
panel.close()
__advance(0.1)
panel.open()
__advance(1)
check("reopen during close stays visible", frame.Visible == true and frame.Position == shown and panel.isOpen())
panel.close()
__advance(1)
check("close completes and hides", frame.Visible == false and frame.Position == hidden)
panel.toggle()
panel.toggle()
panel.toggle()
__advance(1)
check("odd number of toggles ends open", panel.isOpen() and frame.Visible and frame.Position == shown)
```
