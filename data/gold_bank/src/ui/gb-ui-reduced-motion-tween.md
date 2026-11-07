---
id: gb-ui-reduced-motion-tween
category: ui-style
topics: reduced motion, GuiService.ReducedMotionEnabled, accessibility, TweenService, settings
source: original
---
# Request
Some players have asked for less movement in menus (sliding panels and bouncing buttons make them feel sick). Roblox has a reduced motion setting now. How do I respect it across all my UI tweens without adding checks everywhere?

# Answer
Route UI tweens through one helper. It reads `GuiService.ReducedMotionEnabled` (plus an optional in-game override) and, when motion is reduced, applies the goal immediately instead of tweening; callers still get a "completed" callback either way, so their logic does not branch.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Motion
local GuiService = game:GetService("GuiService")
local TweenService = game:GetService("TweenService")

local Motion = {}

local override: boolean? = nil

function Motion.setOverride(reduced: boolean?)
	override = reduced
end

function Motion.reduced(): boolean
	if override ~= nil then
		return override
	end
	return GuiService.ReducedMotionEnabled == true
end

function Motion.tween(instance: Instance, info: TweenInfo, goals: { [string]: any }, onDone: (() -> ())?): Tween?
	if Motion.reduced() then
		local target: any = instance
		for property, value in goals do
			target[property] = value
		end
		if onDone then
			task.defer(onDone)
		end
		return nil
	end
	local tween = TweenService:Create(instance, info, goals)
	if onDone then
		tween.Completed:Connect(function(state: Enum.PlaybackState)
			if state == Enum.PlaybackState.Completed then
				onDone()
			end
		end)
	end
	tween:Play()
	return tween
end

return Motion
```

- Reduced motion removes movement, not feedback: a colour change on hover is fine to keep, a slide-in becomes an instant appear.
- `onDone` is deferred in the instant path so callers see the same ordering as with a real tween.
- An in-game toggle (`setOverride`) lets a player reduce motion in your game without changing their Roblox-wide setting; pass `nil` to follow the setting again.

# Test
```lua
local GuiService = game:GetService("GuiService")
local frame = Instance.new("Frame")
local info = TweenInfo.new(0.5)
GuiService.ReducedMotionEnabled = true
local done = 0
local t = item.tween(frame, info, { Position = UDim2.fromScale(0.5, 0.5) }, function()
	done += 1
end)
check("reduced motion applies instantly", t == nil and frame.Position == UDim2.fromScale(0.5, 0.5))
__advance(0)
check("callback still runs", done == 1)
GuiService.ReducedMotionEnabled = false
item.tween(frame, info, { Position = UDim2.fromScale(0, 0) }, function()
	done += 1
end)
check("normal motion tweens over time", frame.Position == UDim2.fromScale(0.5, 0.5) and done == 1)
__advance(0.6)
check("tween completes", frame.Position == UDim2.fromScale(0, 0) and done == 2)
item.setOverride(true)
item.tween(frame, info, { Position = UDim2.fromScale(1, 1) })
check("player override wins", frame.Position == UDim2.fromScale(1, 1))
```
