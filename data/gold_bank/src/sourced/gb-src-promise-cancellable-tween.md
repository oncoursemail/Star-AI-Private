---
id: gb-src-promise-cancellable-tween
category: ui-interaction
topics: Promise, onCancel, TweenService, cancellation, animation sequence, andThen
source: adapted
source_id: promise
source_path: docs/Examples.md
source_commit: 031d429c82ee458a849e79fa523523bd349d7695
---
# Request
I use evaera's Promise library. My shop menu opens with a sequence of tweens (fade in background, then slide the panel, then pop the title). If the player closes the menu halfway, the remaining tweens keep running and fight the close animation. How do I make the sequence cancellable?

# Answer
Wrap each tween in a Promise that registers an `onCancel` handler (cancel the tween and snap to the end state), and chain them with `andThen`. Cancelling the last promise in the chain cancels the one currently running and skips the rest.

```lua
--!strict
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")

local Promise = require(ReplicatedStorage:WaitForChild("Packages"):WaitForChild("Promise"))

local function tweenPromise(object: Instance, info: TweenInfo, goals: { [string]: any })
	return Promise.new(function(resolve, _reject, onCancel)
		local tween = TweenService:Create(object, info, goals)
		if onCancel(function()
			tween:Cancel()
			for property, value in goals do
				(object :: any)[property] = value
			end
		end) then
			return
		end
		tween.Completed:Connect(function()
			resolve()
		end)
		tween:Play()
	end)
end

local FAST = TweenInfo.new(0.2, Enum.EasingStyle.Quad, Enum.EasingDirection.Out)

local function openMenu(background: Frame, panel: Frame, title: TextLabel)
	return tweenPromise(background, FAST, { BackgroundTransparency = 0.4 })
		:andThen(function()
			return tweenPromise(panel, FAST, { Position = UDim2.fromScale(0.5, 0.5) })
		end)
		:andThen(function()
			return tweenPromise(title, FAST, { TextTransparency = 0 })
		end)
end

return openMenu
```

Usage in the menu controller:

```lua
--!strict
local function bindMenu(openMenu: (Frame, Frame, TextLabel) -> any, background: Frame, panel: Frame, title: TextLabel, closeButton: TextButton)
	local opening = openMenu(background, panel, title)
	closeButton.Activated:Connect(function()
		opening:cancel()
		background.Visible = false
	end)
end

return bindMenu
```

- `onCancel` returns true if the promise was already cancelled before the executor ran, so the tween is never created in that case.
- Snapping to the goal values on cancel leaves the UI in a known state for the close animation.
- Cancellation travels up the chain: `opening:cancel()` cancels whichever tween is running and the later `andThen` steps never start.
