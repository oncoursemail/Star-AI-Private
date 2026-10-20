---
id: gb-ui-tooltip-automatic-size
category: ui-layout
topics: AutomaticSize, tooltip, UISizeConstraint, TextWrapped, edge flipping
source: original
---
# Request
I'm making item tooltips that follow the mouse. Short descriptions leave a huge empty box, long ones overflow, and near the right edge of the screen the tooltip goes off screen. How do I size and place it properly?

# Answer
Let the label size itself with `AutomaticSize = XY`, wrap text, and cap the width with a UISizeConstraint so long text grows downward instead of sideways. Placement is pure math: put the tooltip right of and below the cursor, flipping to the other side on whichever axis would leave the screen.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Tooltip
local Tooltip = {}

local OFFSET = 16

function Tooltip.build(): TextLabel
	local label = Instance.new("TextLabel")
	label.Name = "Tooltip"
	label.AutomaticSize = Enum.AutomaticSize.XY
	label.Size = UDim2.fromOffset(0, 0)
	label.TextWrapped = true
	label.TextXAlignment = Enum.TextXAlignment.Left
	label.TextSize = 15
	label.TextColor3 = Color3.fromRGB(236, 236, 240)
	label.BackgroundColor3 = Color3.fromRGB(22, 24, 28)
	label.ZIndex = 100
	label.Visible = false

	local cap = Instance.new("UISizeConstraint")
	cap.MaxSize = Vector2.new(260, math.huge)
	cap.Parent = label

	local padding = Instance.new("UIPadding")
	padding.PaddingTop = UDim.new(0, 8)
	padding.PaddingBottom = UDim.new(0, 8)
	padding.PaddingLeft = UDim.new(0, 10)
	padding.PaddingRight = UDim.new(0, 10)
	padding.Parent = label

	return label
end

-- Returns the top-left pixel position for a tooltip of `size` next to `cursor` inside `screen`.
function Tooltip.place(cursor: Vector2, size: Vector2, screen: Vector2): Vector2
	local cx: number, cy: number = cursor.X, cursor.Y
	local w: number, h: number = size.X, size.Y
	local x = cx + OFFSET
	if x + w > screen.X then
		x = cx - OFFSET - w
	end
	local y = cy + OFFSET
	if y + h > screen.Y then
		y = cy - OFFSET - h
	end
	return Vector2.new(math.max(0, x), math.max(0, y))
end

function Tooltip.show(label: TextLabel, text: string, cursor: Vector2, screen: Vector2)
	label.Text = text
	label.Visible = true
	local size: Vector2 = label.AbsoluteSize
	local spot = Tooltip.place(cursor, size, screen)
	label.Position = UDim2.fromOffset(spot.X, spot.Y)
end

return Tooltip
```

- AbsoluteSize updates after the text change is laid out, so call `show` again on the next mouse move; the tooltip settles within a frame.
- Clamping to zero keeps a tooltip on a tiny screen at the top-left corner instead of off-screen.
- Put tooltips in their own ScreenGui with a high `DisplayOrder` so they always draw above menus.

# Test
```lua
local screen = Vector2.new(1280, 720)
local size = Vector2.new(200, 80)
local p = item.place(Vector2.new(100, 100), size, screen)
check("right and below by default", p.X == 116 and p.Y == 116)
p = item.place(Vector2.new(1200, 100), size, screen)
check("flips left near the right edge", p.X == 1200 - 16 - 200)
p = item.place(Vector2.new(100, 700), size, screen)
check("flips up near the bottom", p.Y == 700 - 16 - 80)
p = item.place(Vector2.new(5, 5), Vector2.new(2000, 2000), screen)
check("never negative", p.X >= 0 and p.Y >= 0)
local label = item.build()
check("auto sized and width capped", label.AutomaticSize == Enum.AutomaticSize.XY
	and label:FindFirstChildOfClass("UISizeConstraint").MaxSize.X == 260 and label.TextWrapped)
label.AbsoluteSize = size
item.show(label, "Deals 12 damage", Vector2.new(1200, 700), screen)
check("show positions with the measured size", label.Visible and label.Position.X.Offset == 984 and label.Position.Y.Offset == 604)
```
