---
id: gb-ui-canvasgroup-fade
category: ui-style
topics: CanvasGroup, GroupTransparency, fade in out, TweenService, panel
source: original
---
# Request
To fade my settings panel I loop over every descendant and tween BackgroundTransparency, TextTransparency and ImageTransparency separately. It's a lot of code, items that were already half-transparent end up fully opaque after fading in, and it looks uneven. Is there a better way?

# Answer
Make the panel a CanvasGroup and tween its single `GroupTransparency`: the whole group is rendered together and faded as one image, so children keep their own transparency values untouched. Cancel the previous tween on each new fade and only hide the panel when a fade-out actually completes.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Fader
local TweenService = game:GetService("TweenService")

local Fader = {}

export type Fade = { show: () -> (), hide: () -> (), visible: () -> boolean }

function Fader.new(group: CanvasGroup, seconds: number?): Fade
	local info = TweenInfo.new(seconds or 0.2, Enum.EasingStyle.Quad, Enum.EasingDirection.Out)
	local current: Tween? = nil
	local wanted = group.Visible

	local function fadeTo(target: number, onDone: (() -> ())?)
		if current then
			current:Cancel()
		end
		local tween = TweenService:Create(group, info, { GroupTransparency = target })
		current = tween
		tween.Completed:Connect(function(state: Enum.PlaybackState)
			if state == Enum.PlaybackState.Completed and current == tween then
				current = nil
				if onDone then
					onDone()
				end
			end
		end)
		tween:Play()
	end

	return {
		show = function()
			wanted = true
			if not group.Visible then
				group.GroupTransparency = 1
				group.Visible = true
			end
			fadeTo(0)
		end,
		hide = function()
			wanted = false
			fadeTo(1, function()
				group.Visible = false
			end)
		end,
		visible = function()
			return wanted
		end,
	}
end

return Fader
```

- CanvasGroup renders its children into a texture; keep it for panels and dialogs, not for huge scrolling lists, which cost more memory as a group.
- Starting a show from fully transparent only when the panel was hidden means reversing a half-finished hide continues from the current value.
- Short fades (0.15 to 0.25 s) feel responsive; long ones make menus feel slow.

# Test
```lua
local group = Instance.new("CanvasGroup")
group.Visible = false
local child = Instance.new("TextLabel")
child.TextTransparency = 0.5
child.Parent = group
local fade = item.new(group, 0.2)
fade.show()
check("shown starts from transparent", group.Visible and group.GroupTransparency == 1)
__advance(0.3)
check("fades in fully", group.GroupTransparency == 0)
fade.hide()
__advance(0.1)
fade.show()
__advance(0.3)
check("show during hide keeps it visible", group.Visible and group.GroupTransparency == 0)
fade.hide()
__advance(0.3)
check("hide completes and hides", group.Visible == false and not fade.visible())
check("children keep their own transparency", child.TextTransparency == 0.5)
```
