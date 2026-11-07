---
id: gb-ui-count-up-number-label
category: ui-text
topics: NumberValue, TweenService, count up animation, number label, interruption
source: original
---
# Request
At the end of a round I want the reward label to count up from the old coin total to the new one over a second instead of jumping. If another reward arrives mid-count, it should continue from the number currently shown, not restart from zero or jump.

# Answer
Tween a NumberValue (TweenService cannot tween a label's text) and write the rounded value to the label whenever it changes. Keep the tween in a variable: a new target cancels the old tween and starts from the value currently displayed. On completion, set the exact target so rounding never leaves it one short.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.CountUp
local TweenService = game:GetService("TweenService")

local CountUp = {}

export type Counter = { set: (target: number) -> (), shown: () -> number }

function CountUp.new(label: TextLabel, format: ((n: number) -> string)?, seconds: number?): Counter
	local fmt = format or function(n: number): string
		return tostring(n)
	end
	local info = TweenInfo.new(seconds or 1, Enum.EasingStyle.Quad, Enum.EasingDirection.Out)
	local value = Instance.new("NumberValue")
	value.Value = 0
	local current: Tween? = nil
	local target = 0

	local function show()
		local n: number = value.Value
		label.Text = fmt(math.floor(n + 0.5))
	end
	value.Changed:Connect(show)

	local function set(newTarget: number)
		target = newTarget
		if current then
			current:Cancel()
		end
		local tween = TweenService:Create(value, info, { Value = newTarget })
		current = tween
		tween.Completed:Connect(function(state: Enum.PlaybackState)
			if state == Enum.PlaybackState.Completed and current == tween then
				current = nil
				value.Value = target
				show()
			end
		end)
		tween:Play()
	end

	show()
	return {
		set = set,
		shown = function()
			local n: number = value.Value
			return math.floor(n + 0.5)
		end,
	}
end

return CountUp
```

- Tweening from the NumberValue's current value is what makes interruption seamless: TweenService always starts from the live property.
- Pass a formatter (separators or abbreviations) so the animation and the static label use identical text.
- Keep the NumberValue unparented; it only exists to be tweened on this client.

# Test
```lua
local label = Instance.new("TextLabel")
local counter = item.new(label, function(n)
	return n .. " coins"
end, 1)
check("starts at zero", label.Text == "0 coins")
counter.set(250)
__advance(1.1)
check("reaches the target exactly", label.Text == "250 coins" and counter.shown() == 250)
counter.set(400)
__advance(0.5)
counter.set(900)
__advance(1.1)
check("interrupted count ends at the newest target", label.Text == "900 coins")
counter.set(899.6)
__advance(1.1)
check("rounded display", label.Text == "900 coins")
```
