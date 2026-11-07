---
id: gb-ui-scrolling-canvas-cutoff
category: ui-overflow
topics: ScrollingFrame, AutomaticCanvasSize, CanvasSize, VerticalScrollBarInset, UIPadding
source: original
---
# Request
My quest list ScrollingFrame won't scroll far enough: the last two quests are cut off, and the scrollbar covers the right edge of every entry. I set `CanvasSize = UDim2.new(0, 0, 2, 0)` because I thought that doubles the height.

# Answer
A Scale CanvasSize is relative to the frame's own size, so `2` is twice the window, not "enough for the content". Let the engine size the canvas with `AutomaticCanvasSize = Y` and a zero CanvasSize, add bottom padding inside the canvas, and reserve room for the scrollbar with `VerticalScrollBarInset` so it never sits on top of entries.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.QuestList
local QuestList = {}

function QuestList.build(): ScrollingFrame
	local scroller = Instance.new("ScrollingFrame")
	scroller.Name = "QuestList"
	scroller.Size = UDim2.fromScale(1, 1)
	scroller.BackgroundTransparency = 1
	scroller.BorderSizePixel = 0
	scroller.ScrollingDirection = Enum.ScrollingDirection.Y
	scroller.CanvasSize = UDim2.new(0, 0, 0, 0)
	scroller.AutomaticCanvasSize = Enum.AutomaticSize.Y
	scroller.ScrollBarThickness = 6
	scroller.VerticalScrollBarInset = Enum.ScrollBarInset.ScrollBar
	scroller.ScrollBarImageColor3 = Color3.fromRGB(150, 155, 165)

	local layout = Instance.new("UIListLayout")
	layout.SortOrder = Enum.SortOrder.LayoutOrder
	layout.Padding = UDim.new(0, 6)
	layout.Parent = scroller

	local padding = Instance.new("UIPadding")
	padding.PaddingTop = UDim.new(0, 8)
	padding.PaddingBottom = UDim.new(0, 12)
	padding.PaddingLeft = UDim.new(0, 8)
	padding.PaddingRight = UDim.new(0, 8)
	padding.Parent = scroller

	return scroller
end

function QuestList.add(scroller: ScrollingFrame, order: number, text: string): TextLabel
	local row = Instance.new("TextLabel")
	row.Name = "Quest" .. order
	row.LayoutOrder = order
	row.Size = UDim2.new(1, 0, 0, 0)
	row.AutomaticSize = Enum.AutomaticSize.Y
	row.TextWrapped = true
	row.TextXAlignment = Enum.TextXAlignment.Left
	row.TextSize = 16
	row.TextColor3 = Color3.fromRGB(230, 230, 236)
	row.BackgroundColor3 = Color3.fromRGB(36, 38, 45)
	row.Text = text
	row.Parent = scroller
	return row
end

return QuestList
```

- Rows use `AutomaticSize = Y` with wrapping, so a long quest description makes its row taller and the canvas follows.
- `ScrollBarInset.ScrollBar` shrinks the canvas width by the bar's thickness only when the bar is showing.
- Bottom padding inside the canvas leaves breathing room after the last entry instead of ending flush with the edge.

# Test
```lua
local scroller = item.build()
check("canvas sized by content", scroller.AutomaticCanvasSize == Enum.AutomaticSize.Y)
check("no fixed canvas height", scroller.CanvasSize.Y.Scale == 0 and scroller.CanvasSize.Y.Offset == 0)
check("scrollbar does not cover entries", scroller.VerticalScrollBarInset == Enum.ScrollBarInset.ScrollBar)
local row = item.add(scroller, 3, "Collect 10 mushrooms in the Whispering Woods before nightfall")
check("rows grow with wrapped text", row.AutomaticSize == Enum.AutomaticSize.Y and row.TextWrapped)
check("rows ordered by LayoutOrder", scroller.UIListLayout.SortOrder == Enum.SortOrder.LayoutOrder and row.LayoutOrder == 3)
check("bottom padding present", scroller.UIPadding.PaddingBottom.Offset > 0)
```
