---
id: gb-ui-panel-grow-then-scroll
category: ui-overflow
topics: AbsoluteContentSize, UIListLayout, ScrollingFrame, dynamic height, max height
source: original
---
# Request
I have a party panel that lists members. With 2 members it should be a small box, with 4 it gets taller, and past a certain height it should stop growing and scroll instead. AutomaticSize grows forever and a fixed size wastes space. What's the right approach?

# Answer
Drive the ScrollingFrame's height from its UIListLayout's `AbsoluteContentSize`: height = min(content, max). The canvas height always matches the content, so scrolling only kicks in once the cap is reached. One small function, re-run whenever the content size changes.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.GrowingList
local GrowingList = {}

function GrowingList.heightFor(contentHeight: number, padding: number, maxHeight: number): number
	return math.min(contentHeight + padding, maxHeight)
end

function GrowingList.bind(scroller: ScrollingFrame, layout: UIListLayout, maxHeight: number, padding: number?): RBXScriptConnection
	local pad = padding or 0
	scroller.AutomaticCanvasSize = Enum.AutomaticSize.None
	scroller.ScrollingDirection = Enum.ScrollingDirection.Y

	local function update()
		local content: number = layout.AbsoluteContentSize.Y
		local height = GrowingList.heightFor(content, pad, maxHeight)
		scroller.Size = UDim2.new(scroller.Size.X.Scale, scroller.Size.X.Offset, 0, height)
		scroller.CanvasSize = UDim2.fromOffset(0, content + pad)
		scroller.ScrollBarThickness = if content + pad > maxHeight then 6 else 0
	end

	update()
	return layout:GetPropertyChangedSignal("AbsoluteContentSize"):Connect(update)
end

return GrowingList
```

- `padding` is the sum of the frame's top and bottom UIPadding, which AbsoluteContentSize does not include.
- Hiding the scrollbar until it is needed stops a scrollbar appearing on a list that fits.
- Width is preserved from the existing Size, so the panel's horizontal layout is untouched.

# Test
```lua
local scroller = Instance.new("ScrollingFrame")
scroller.Size = UDim2.new(0, 240, 0, 10)
local layout = Instance.new("UIListLayout")
layout.Parent = scroller
layout.AbsoluteContentSize = Vector2.new(240, 80)
local conn = item.bind(scroller, layout, 200, 12)
check("small content gives a small panel", scroller.Size.Y.Offset == 92 and scroller.ScrollBarThickness == 0)
check("width preserved", scroller.Size.X.Offset == 240)
layout.AbsoluteContentSize = Vector2.new(240, 160)
check("grows with content", scroller.Size.Y.Offset == 172)
layout.AbsoluteContentSize = Vector2.new(240, 400)
check("caps at max and scrolls", scroller.Size.Y.Offset == 200 and scroller.CanvasSize.Y.Offset == 412 and scroller.ScrollBarThickness == 6)
conn:Disconnect()
```
