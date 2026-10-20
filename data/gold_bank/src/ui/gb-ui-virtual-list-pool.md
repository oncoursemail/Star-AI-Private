---
id: gb-ui-virtual-list-pool
category: ui-overflow
topics: ScrollingFrame, virtualised list, object pool, CanvasPosition, thousands of rows
source: original
---
# Request
My trade history can have 5,000+ entries. Creating a TextLabel for each one inside a ScrollingFrame with a UIListLayout makes the menu freeze for a second when it opens. How do I show a huge list without making thousands of instances?

# Answer
Virtualise it: the canvas is as tall as all rows would be, but only enough labels to fill the viewport (plus a small overscan) exist. When the canvas scrolls, the same labels are moved to the rows now in view and given their new text. No UIListLayout: rows are positioned by index.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.VirtualList
local VirtualList = {}

export type List = {
	setItems: (items: { string }) -> (),
	refresh: () -> (),
	destroy: () -> (),
}

function VirtualList.new(scroller: ScrollingFrame, rowHeight: number, overscan: number?): List
	assert(rowHeight > 0, "rowHeight must be positive")
	local extra = overscan or 2
	local items: { string } = {}
	local pool: { TextLabel } = {}

	scroller.AutomaticCanvasSize = Enum.AutomaticSize.None
	scroller.ScrollingDirection = Enum.ScrollingDirection.Y

	local function ensurePool(count: number)
		while #pool < count do
			local row = Instance.new("TextLabel")
			row.Name = "Row"
			row.Size = UDim2.new(1, 0, 0, rowHeight)
			row.BackgroundTransparency = 1
			row.TextColor3 = Color3.fromRGB(230, 230, 235)
			row.TextSize = 16
			row.TextXAlignment = Enum.TextXAlignment.Left
			row.TextTruncate = Enum.TextTruncate.AtEnd
			row.Parent = scroller
			table.insert(pool, row)
		end
	end

	local function refresh()
		local scrollY: number = scroller.CanvasPosition.Y
		local viewportHeight: number = scroller.AbsoluteSize.Y
		local first = math.max(1, math.floor(scrollY / rowHeight) + 1 - extra)
		ensurePool(math.ceil(viewportHeight / rowHeight) + extra * 2 + 1)
		for i, row in pool do
			local index = first + i - 1
			local text = items[index]
			row.Visible = text ~= nil
			if text ~= nil then
				row.Position = UDim2.fromOffset(0, (index - 1) * rowHeight)
				row.Text = text
			end
		end
	end

	local connections = {
		scroller:GetPropertyChangedSignal("CanvasPosition"):Connect(refresh),
		scroller:GetPropertyChangedSignal("AbsoluteSize"):Connect(refresh),
	}

	local function setItems(newItems: { string })
		items = newItems
		scroller.CanvasSize = UDim2.fromOffset(0, #items * rowHeight)
		refresh()
	end

	local function destroy()
		for _, connection in connections do
			connection:Disconnect()
		end
		for _, row in pool do
			row:Destroy()
		end
		pool = {}
	end

	return { setItems = setItems, refresh = refresh, destroy = destroy }
end

return VirtualList
```

- The cost of opening the menu is now about 15 labels whatever the list length; the data stays a plain table of strings.
- Rows need a fixed height for the index math; for mixed heights keep a prefix-sum array of offsets and binary search it.
- Listening to `AbsoluteSize` re-fills the pool when the window is resized or the phone rotates.
- Keep the backing table on the client and page it from the server in chunks if the history itself is large.

# Test
```lua
local scroller = Instance.new("ScrollingFrame")
scroller.AbsoluteSize = Vector2.new(300, 280)
scroller.CanvasPosition = Vector2.zero
local list = item.new(scroller, 28, 2)
local data = {}
for i = 1, 5000 do
	data[i] = "Trade " .. i
end
list.setItems(data)
local function rows()
	local out = {}
	for _, c in scroller:GetChildren() do
		if c:IsA("TextLabel") then
			table.insert(out, c)
		end
	end
	return out
end
local function shown(text)
	for _, r in rows() do
		if r.Visible and r.Text == text then
			return r
		end
	end
	return nil
end
check("canvas is as tall as all rows", scroller.CanvasSize.Y.Offset == 5000 * 28)
check("only a screenful of labels exists", #rows() <= 15)
check("first row visible at the top", shown("Trade 1") ~= nil)
scroller.CanvasPosition = Vector2.new(0, 28 * 1000)
local r = shown("Trade 1001")
check("scrolling reuses labels for the rows in view", r ~= nil and r.Position.Y.Offset == 28000 and #rows() <= 15)
check("rows far above are no longer shown", shown("Trade 1") == nil)
scroller.CanvasPosition = Vector2.new(0, 28 * 4995)
check("last row reachable", shown("Trade 5000") ~= nil)
list.setItems({})
check("empty list hides every row", shown("Trade 5000") == nil and scroller.CanvasSize.Y.Offset == 0)
```
