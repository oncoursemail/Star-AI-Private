---
id: gb-ui-description-max-lines
category: ui-overflow
topics: TextWrapped, TextTruncate, LineHeight, max lines, show more
source: original
---
# Request
Item descriptions in my shop vary from one line to a whole paragraph. I want them limited to three lines with "..." at the end and a "More" button that expands the full text. How do I do max lines in Roblox?

# Answer
Combine `TextWrapped` with `TextTruncate = AtEnd` and a height of exactly N lines (`TextSize * LineHeight * N`): the engine wraps and puts the ellipsis on the last visible line. Expanding switches the label to `AutomaticSize = Y` without truncation; the "More" button only shows when the text does not fit (`TextFits`).

```lua
--!strict
-- ModuleScript: ReplicatedStorage.ClampedText
local ClampedText = {}

export type Clamped = {
	label: TextLabel,
	setText: (text: string) -> (),
	setExpanded: (expanded: boolean) -> (),
	isExpanded: () -> boolean,
}

function ClampedText.heightFor(textSize: number, lineHeight: number, lines: number): number
	return math.ceil(textSize * lineHeight * lines)
end

function ClampedText.new(maxLines: number, textSize: number): Clamped
	local expanded = false
	local label = Instance.new("TextLabel")
	label.Name = "Description"
	label.BackgroundTransparency = 1
	label.TextWrapped = true
	label.TextXAlignment = Enum.TextXAlignment.Left
	label.TextYAlignment = Enum.TextYAlignment.Top
	label.TextColor3 = Color3.fromRGB(200, 204, 212)
	label.TextSize = textSize
	label.LineHeight = 1.15

	local collapsedHeight = ClampedText.heightFor(textSize, label.LineHeight, maxLines)

	local function setExpanded(value: boolean)
		expanded = value
		if expanded then
			label.TextTruncate = Enum.TextTruncate.None
			label.Size = UDim2.new(1, 0, 0, collapsedHeight)
			label.AutomaticSize = Enum.AutomaticSize.Y
		else
			label.AutomaticSize = Enum.AutomaticSize.None
			label.Size = UDim2.new(1, 0, 0, collapsedHeight)
			label.TextTruncate = Enum.TextTruncate.AtEnd
		end
	end

	local function setText(text: string)
		label.Text = text
		setExpanded(false)
	end

	setExpanded(false)
	return {
		label = label,
		setText = setText,
		setExpanded = setExpanded,
		isExpanded = function()
			return expanded
		end,
	}
end

return ClampedText
```

```lua
--!strict
local ClampedText = require(game:GetService("ReplicatedStorage"):WaitForChild("ClampedText"))

local function mountDescription(parent: Frame, moreButton: TextButton, text: string)
	local clamped = ClampedText.new(3, 15)
	clamped.setText(text)
	clamped.label.Parent = parent
	-- TextFits is computed after layout, so check it once the label is on screen.
	task.defer(function()
		moreButton.Visible = not clamped.label.TextFits
	end)
	moreButton.Activated:Connect(function()
		clamped.setExpanded(not clamped.isExpanded())
		moreButton.Text = if clamped.isExpanded() then "Less" else "More"
	end)
end

return mountDescription
```

- Collapsed height is computed from the same TextSize and LineHeight the label uses, so changing the font size keeps exactly three lines.
- Expanding keeps the collapsed height as the minimum and lets AutomaticSize grow it, so short texts do not jump.
- Setting new text collapses again, which is what players expect when they select a different item.

# Test
```lua
check("height for three lines", item.heightFor(15, 1.15, 3) == 52)
local c = item.new(3, 15)
c.setText("A very long description that will need more than three lines on a narrow card.")
check("collapsed truncates at a fixed height", c.label.TextTruncate == Enum.TextTruncate.AtEnd and c.label.Size.Y.Offset == 52)
check("wrapping on", c.label.TextWrapped and c.label.AutomaticSize == Enum.AutomaticSize.None)
c.setExpanded(true)
check("expanded grows with the text", c.label.AutomaticSize == Enum.AutomaticSize.Y and c.label.TextTruncate == Enum.TextTruncate.None)
c.setText("Short")
check("new text collapses again", not c.isExpanded() and c.label.TextTruncate == Enum.TextTruncate.AtEnd)
```
