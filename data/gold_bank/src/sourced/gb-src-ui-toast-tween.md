---
id: gb-src-ui-toast-tween
category: ui-interaction
topics: TweenService, CanvasGroup, GroupTransparency, UDim2, AnchorPoint, notification
source: adapted
source_id: creator-docs
source_path: content/en-us/ui/animation.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I want a "Quest complete!" banner that slides down from the top of the screen and fades in, stays for 3 seconds, then fades out. The banner has a frame, an icon and a label. Tweening each element's transparency separately is getting messy.

# Answer
Put the banner content in a `CanvasGroup` and tween its `GroupTransparency`, which fades all children together, while also tweening `Position` in the same tween. Center it with `AnchorPoint` so the slide is resolution independent.

```lua
--!strict
local TweenService = game:GetService("TweenService")

local SHOW_INFO = TweenInfo.new(0.35, Enum.EasingStyle.Quint, Enum.EasingDirection.Out)
local HIDE_INFO = TweenInfo.new(0.25, Enum.EasingStyle.Quad, Enum.EasingDirection.In)
local SHOWN = UDim2.fromScale(0.5, 0.08)
local HIDDEN = UDim2.fromScale(0.5, -0.1)

local Banner = {}

local showCount: { [CanvasGroup]: number } = {}

function Banner.show(group: CanvasGroup, label: TextLabel, text: string, holdSeconds: number): Tween
	local token = (showCount[group] or 0) + 1
	showCount[group] = token
	label.Text = text
	group.AnchorPoint = Vector2.new(0.5, 0)
	group.Position = HIDDEN
	group.GroupTransparency = 1
	group.Visible = true

	local showTween = TweenService:Create(group, SHOW_INFO, { Position = SHOWN, GroupTransparency = 0 })
	local hideTween = TweenService:Create(group, HIDE_INFO, { Position = HIDDEN, GroupTransparency = 1 })

	showTween.Completed:Connect(function(state: Enum.PlaybackState)
		if state == Enum.PlaybackState.Completed then
			task.delay(holdSeconds, function()
				if showCount[group] == token then
					hideTween:Play()
				end
			end)
		end
	end)
	hideTween.Completed:Connect(function(state: Enum.PlaybackState)
		if state == Enum.PlaybackState.Completed then
			group.Visible = false
		end
	end)

	showTween:Play()
	return showTween
end

return Banner
```

- One `GroupTransparency` value fades the frame, icon and text together, and the group renders as one image, so overlapping children do not show through each other mid-fade.
- Position and transparency share one tween, so they always finish together.
- The token makes a newer `show` call win: the older banner's pending hide is skipped instead of cutting the new message short.
- `Visible = false` after hiding stops the hidden banner from blocking input or costing rendering.

# Test
```lua
local group = Instance.new("CanvasGroup")
local label = Instance.new("TextLabel")
label.Parent = group
item.show(group, label, "Quest complete!", 3)
check("text set and starts hidden", label.Text == "Quest complete!" and group.Visible == true)
__advance(0.4)
check("slid in and opaque", group.Position == UDim2.fromScale(0.5, 0.08) and group.GroupTransparency == 0)
__advance(2)
check("still shown during hold", group.Visible == true)
__advance(1.5)
check("hidden after hold and fade", group.Visible == false and group.GroupTransparency == 1)
item.show(group, label, "First", 3)
__advance(2)
item.show(group, label, "Second", 3)
__advance(2)
check("older hide skipped when shown again", group.Visible == true and label.Text == "Second")
__advance(2)
check("newer banner hides on its own schedule", group.Visible == false)
```
