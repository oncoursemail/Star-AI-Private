---
id: gb-ui-scroll-selected-into-view
category: ui-overflow
topics: ScrollingFrame, CanvasPosition, scroll into view, keyboard navigation, selection
source: original
---
# Request
In my settings list, players can move the selection with arrow keys or a d-pad, but when the selected row is below the visible area the list doesn't scroll, so they lose track of where they are. How do I scroll just enough to reveal the selected row?

# Answer
Compute the row's top inside the canvas, then move `CanvasPosition.Y` only if the row is above or below the visible window, by the smallest amount that shows it plus a little padding. If it is already fully visible, leave the scroll alone so the list does not jump.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.RevealRow
local RevealRow = {}

function RevealRow.offset(scrollY: number, windowHeight: number, rowTop: number, rowHeight: number, padding: number): number
	if rowTop - padding < scrollY then
		return math.max(0, rowTop - padding)
	end
	local rowBottom = rowTop + rowHeight + padding
	if rowBottom > scrollY + windowHeight then
		return rowBottom - windowHeight
	end
	return scrollY
end

function RevealRow.reveal(scroller: ScrollingFrame, row: GuiObject, padding: number?)
	local scrollY: number = scroller.CanvasPosition.Y
	local windowHeight: number = scroller.AbsoluteWindowSize.Y
	local rowScreenY: number = row.AbsolutePosition.Y
	local frameScreenY: number = scroller.AbsolutePosition.Y
	local rowHeight: number = row.AbsoluteSize.Y
	local rowTop = rowScreenY - frameScreenY + scrollY
	local y = RevealRow.offset(scrollY, windowHeight, rowTop, rowHeight, padding or 8)
	if y ~= scrollY then
		scroller.CanvasPosition = Vector2.new(scroller.CanvasPosition.X, y)
	end
end

return RevealRow
```

```lua
--!strict
local GuiService = game:GetService("GuiService")
local RevealRow = require(game:GetService("ReplicatedStorage"):WaitForChild("RevealRow"))

local function follow(scroller: ScrollingFrame): RBXScriptConnection
	return GuiService:GetPropertyChangedSignal("SelectedObject"):Connect(function()
		local selected = GuiService.SelectedObject
		if selected and selected:IsDescendantOf(scroller) then
			RevealRow.reveal(scroller, selected)
		end
	end)
end

return follow
```

- `AbsolutePosition` is on screen, so subtracting the frame's own position and adding the current scroll gives the row's position inside the canvas.
- Smallest-move scrolling keeps context: the newly selected row appears at the edge it came from, not centred.
- Set `ScrollingFrame.SelectionGroup = true` too, so gamepad navigation stays inside the list while it has rows left.

# Test
```lua
check("visible row leaves scroll alone", item.offset(100, 300, 200, 40, 8) == 100)
check("row below scrolls down just enough", item.offset(0, 300, 400, 40, 8) == 400 + 40 + 8 - 300)
check("row above scrolls up", item.offset(500, 300, 200, 40, 8) == 192)
check("never negative", item.offset(50, 300, 0, 40, 8) == 0)
local scroller = Instance.new("ScrollingFrame")
scroller.CanvasPosition = Vector2.new(0, 0)
scroller.AbsoluteWindowSize = Vector2.new(300, 300)
scroller.AbsolutePosition = Vector2.new(0, 100)
local row = Instance.new("TextButton")
row.AbsolutePosition = Vector2.new(0, 100 + 480)
row.AbsoluteSize = Vector2.new(300, 40)
row.Parent = scroller
item.reveal(scroller, row)
check("reveal moves the canvas", scroller.CanvasPosition.Y == 480 + 40 + 8 - 300)
```
