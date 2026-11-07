---
id: gb-ui-quest-step-pips
category: ui-style
topics: step indicator, progress pips, UIListLayout, accessible label, quest UI
source: original
---
# Request
For my tutorial I want a row of small step indicators under the instructions: completed steps filled, the current one highlighted, upcoming ones dim, plus "Step 2 of 5" text. What's a tidy way to build and update it?

# Answer
Build N pips in a horizontal UIListLayout once and restyle them from a single `setStep` function: done, current and upcoming each get one look. The text label states the step in words, so the pips are a visual summary rather than the only signal.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.StepPips
local StepPips = {}

export type Pips = { frame: Frame, setStep: (step: number) -> (), step: () -> number }

local DONE = Color3.fromRGB(70, 150, 235)
local UPCOMING = Color3.fromRGB(70, 74, 84)

function StepPips.build(total: number): Pips
	assert(total >= 1, "need at least one step")
	local frame = Instance.new("Frame")
	frame.Name = "StepPips"
	frame.BackgroundTransparency = 1
	frame.Size = UDim2.new(1, 0, 0, 28)

	local layout = Instance.new("UIListLayout")
	layout.FillDirection = Enum.FillDirection.Horizontal
	layout.HorizontalAlignment = Enum.HorizontalAlignment.Center
	layout.VerticalAlignment = Enum.VerticalAlignment.Center
	layout.SortOrder = Enum.SortOrder.LayoutOrder
	layout.Padding = UDim.new(0, 6)
	layout.Parent = frame

	local pips: { Frame } = {}
	for i = 1, total do
		local pip = Instance.new("Frame")
		pip.Name = "Pip" .. i
		pip.LayoutOrder = i
		pip.Size = UDim2.fromOffset(10, 10)
		local corner = Instance.new("UICorner")
		corner.CornerRadius = UDim.new(0.5, 0)
		corner.Parent = pip
		local stroke = Instance.new("UIStroke")
		stroke.Color = DONE
		stroke.Parent = pip
		pip.Parent = frame
		pips[i] = pip
	end

	local label = Instance.new("TextLabel")
	label.Name = "StepText"
	label.LayoutOrder = total + 1
	label.BackgroundTransparency = 1
	label.AutomaticSize = Enum.AutomaticSize.X
	label.Size = UDim2.fromOffset(0, 20)
	label.TextSize = 14
	label.TextColor3 = Color3.fromRGB(200, 204, 212)
	label.Parent = frame

	local current = 1
	local function setStep(step: number)
		current = math.clamp(math.floor(step), 1, total)
		for i, pip in pips do
			local stroke = pip:FindFirstChildOfClass("UIStroke")
			pip.BackgroundColor3 = if i <= current then DONE else UPCOMING
			pip.BackgroundTransparency = if i == current then 1 else 0
			pip.Size = if i == current then UDim2.fromOffset(14, 14) else UDim2.fromOffset(10, 10)
			if stroke then
				stroke.Enabled = i == current
				stroke.Thickness = 2
			end
		end
		label.Text = string.format("Step %d of %d", current, total)
	end

	setStep(1)
	return {
		frame = frame,
		setStep = setStep,
		step = function()
			return current
		end,
	}
end

return StepPips
```

- The current pip is a larger ring (stroke only), done pips are filled, upcoming ones dim: three looks distinguishable without relying on hue.
- Clamping the step means a stray `setStep(0)` or an extra "next" never breaks the row.
- With many steps (10+), switch to a single progress bar; pips stop being countable at a glance.

# Test
```lua
local pips = item.build(5)
pips.setStep(3)
local f = pips.frame
check("text states the step", f.StepText.Text == "Step 3 of 5")
check("done pips filled", f.Pip1.BackgroundTransparency == 0 and f.Pip1.BackgroundColor3 == Color3.fromRGB(70, 150, 235))
check("current is a larger ring", f.Pip3.Size.X.Offset == 14 and f.Pip3.BackgroundTransparency == 1 and f.Pip3.UIStroke.Enabled)
check("upcoming dim", f.Pip5.BackgroundColor3 == Color3.fromRGB(70, 74, 84) and f.Pip5.UIStroke.Enabled == false)
pips.setStep(99)
check("clamped to the last step", pips.step() == 5 and f.StepText.Text == "Step 5 of 5")
check("zero steps rejected", not pcall(item.build, 0))
```
