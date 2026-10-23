---
id: gb-ui-status-chip-not-color-only
category: ui-style
topics: accessibility, colour blindness, status chip, text label, contrast
source: original
---
# Request
Our server browser shows a coloured dot per server: green for open, yellow for almost full, red for full. A colour-blind tester said they can't tell them apart. How should status be shown?

# Answer
Never encode state in colour alone: give each status a word and a distinct shape, and use colour as a supporting cue. A small chip with a label ("Open", "Almost full", "Full") and filled vs outlined styling reads for everyone, and the mapping lives in one table.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.StatusChip
local StatusChip = {}

export type Status = "open" | "almostFull" | "full"

type Style = { text: string, color: Color3, filled: boolean }

local STYLES: { [Status]: Style } = {
	open = { text = "Open", color = Color3.fromRGB(60, 170, 100), filled = true },
	almostFull = { text = "Almost full", color = Color3.fromRGB(215, 160, 40), filled = false },
	full = { text = "Full", color = Color3.fromRGB(200, 70, 70), filled = false },
}

function StatusChip.statusFor(players: number, capacity: number): Status
	if capacity <= 0 or players >= capacity then
		return "full"
	elseif players / capacity >= 0.8 then
		return "almostFull"
	end
	return "open"
end

function StatusChip.build(status: Status): TextLabel
	local style = STYLES[status]
	local chip = Instance.new("TextLabel")
	chip.Name = "Status"
	chip.AutomaticSize = Enum.AutomaticSize.X
	chip.Size = UDim2.fromOffset(0, 22)
	chip.TextSize = 13
	chip.Text = style.text
	chip.BackgroundColor3 = style.color
	chip.BackgroundTransparency = if style.filled then 0 else 1
	chip.TextColor3 = if style.filled then Color3.fromRGB(14, 16, 18) else style.color

	local stroke = Instance.new("UIStroke")
	stroke.ApplyStrokeMode = Enum.ApplyStrokeMode.Border
	stroke.Color = style.color
	stroke.Thickness = if status == "full" then 2 else 1
	stroke.Parent = chip

	local corner = Instance.new("UICorner")
	corner.CornerRadius = UDim.new(0.5, 0)
	corner.Parent = chip

	local padding = Instance.new("UIPadding")
	padding.PaddingLeft = UDim.new(0, 8)
	padding.PaddingRight = UDim.new(0, 8)
	padding.Parent = chip

	return chip
end

return StatusChip
```

- The word carries the meaning; filled vs outlined and stroke weight add a second non-colour cue for quick scanning.
- Dark text on the filled green chip keeps contrast above 4.5:1; coloured text on the dark list background should be checked the same way.
- Sorting the list by status (open first) helps more than any colour choice.

# Test
```lua
check("open below 80 percent", item.statusFor(5, 10) == "open")
check("almost full at 80 percent", item.statusFor(8, 10) == "almostFull")
check("full at capacity", item.statusFor(10, 10) == "full" and item.statusFor(12, 10) == "full")
check("zero capacity counts as full", item.statusFor(0, 0) == "full")
local open, full = item.build("open"), item.build("full")
check("status has words, not just colour", open.Text == "Open" and full.Text == "Full")
check("filled vs outlined shapes differ", open.BackgroundTransparency == 0 and full.BackgroundTransparency == 1)
check("full uses a heavier outline", full.UIStroke.Thickness > open.UIStroke.Thickness)
```
