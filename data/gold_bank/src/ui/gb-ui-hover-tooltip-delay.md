---
id: gb-ui-hover-tooltip-delay
category: ui-interaction
topics: hover delay, tooltip, MouseEnter, MouseLeave, task.delay cancel
source: original
---
# Request
My toolbar shows a tooltip the instant the mouse touches a button, so sweeping the mouse across the toolbar flashes five tooltips. I'd like a short hover delay, and moving off the button before the delay should cancel it. My attempt with `task.wait(0.4)` still shows tooltips for buttons I already left.

# Answer
The `task.wait` version cannot tell that the mouse left. Bump a per-button counter on every enter and leave, and when the delay ends, show the tooltip only if the counter still matches the value from that enter. Once one tooltip is showing, moving to a neighbour can show the next one immediately, which is how desktop toolbars feel.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.HoverTips
local HoverTips = {}

export type Tips = { attach: (button: GuiButton, text: string) -> () }

function HoverTips.new(tooltip: TextLabel, delaySeconds: number?): Tips
	local hoverDelay = delaySeconds or 0.4
	local generation = 0
	local warm = false
	local hovered: GuiButton? = nil

	local function hide()
		generation += 1
		tooltip.Visible = false
		local mine = generation
		task.delay(0.15, function()
			if mine == generation then
				warm = false
			end
		end)
	end

	local function attach(button: GuiButton, text: string)
		button.MouseEnter:Connect(function()
			hovered = button
			generation += 1
			local mine = generation
			local function show()
				if mine == generation then
					tooltip.Text = text
					tooltip.Visible = true
					warm = true
				end
			end
			if warm then
				show()
			else
				task.delay(hoverDelay, show)
			end
		end)
		button.MouseLeave:Connect(function()
			-- MouseLeave of the old button can arrive after MouseEnter of the next one; ignore it then.
			if hovered == button then
				hovered = nil
				hide()
			end
		end)
	end

	return { attach = attach }
end

return HoverTips
```

- The shared generation counter means any newer enter or leave invalidates older pending shows, across all buttons.
- Tracking which button is hovered makes a late MouseLeave from the previous button harmless.
- "Warm" mode lasts 0.15 s after leaving, enough to cross the gap between buttons without restarting the delay.
- Touch has no hover; show the same text on long-press (`TouchLongPress`) for mobile players.

# Test
```lua
local tip = Instance.new("TextLabel")
tip.Visible = false
local tips = item.new(tip, 0.4)
local a, b = Instance.new("TextButton"), Instance.new("TextButton")
tips.attach(a, "Build")
tips.attach(b, "Paint")
a.MouseEnter:Fire()
__advance(0.2)
a.MouseLeave:Fire()
__advance(0.5)
check("leaving early cancels", tip.Visible == false)
a.MouseEnter:Fire()
__advance(0.45)
check("shows after the delay", tip.Visible and tip.Text == "Build")
a.MouseLeave:Fire()
b.MouseEnter:Fire()
check("neighbour shows instantly while warm", tip.Visible and tip.Text == "Paint")
b.MouseLeave:Fire()
__advance(1)
b.MouseEnter:Fire()
check("after cooling down the delay applies again", tip.Visible == false)
__advance(0.45)
check("and then shows", tip.Visible and tip.Text == "Paint")
a.MouseEnter:Fire()
b.MouseLeave:Fire()
__advance(0.45)
check("late leave from the old button does not hide the new tooltip", tip.Visible and tip.Text == "Build")
```
