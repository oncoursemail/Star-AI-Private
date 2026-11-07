---
id: gb-ui-flex-search-toolbar
category: ui-layout
topics: UIFlexItem, UIListLayout, horizontal toolbar, FlexMode, AutomaticSize
source: original
---
# Request
I have a horizontal toolbar: back button, search box, filter button. I want the two buttons to keep their size and the search box to take all the space left over, on any screen width. Right now I compute the search box width in a script on every resize. Is there a layout way?

# Answer
Yes: a horizontal UIListLayout with a UIFlexItem on the search box. The buttons keep their own size (the filter button sizes to its text with AutomaticSize) and the flex item grows into the remaining width, so no resize script is needed.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.SearchToolbar
local SearchToolbar = {}

export type Toolbar = {
	frame: Frame,
	search: TextBox,
	back: TextButton,
	filter: TextButton,
}

local function button(name: string, text: string): TextButton
	local b = Instance.new("TextButton")
	b.Name = name
	b.Text = text
	b.TextSize = 16
	b.TextColor3 = Color3.fromRGB(236, 236, 240)
	b.BackgroundColor3 = Color3.fromRGB(44, 47, 55)
	return b
end

function SearchToolbar.build(): Toolbar
	local frame = Instance.new("Frame")
	frame.Name = "Toolbar"
	frame.Size = UDim2.new(1, 0, 0, 48)
	frame.BackgroundTransparency = 1

	local layout = Instance.new("UIListLayout")
	layout.FillDirection = Enum.FillDirection.Horizontal
	layout.VerticalAlignment = Enum.VerticalAlignment.Center
	layout.SortOrder = Enum.SortOrder.LayoutOrder
	layout.Padding = UDim.new(0, 8)
	layout.Parent = frame

	local back = button("Back", "Back")
	back.LayoutOrder = 1
	back.Size = UDim2.fromOffset(72, 40)
	back.Parent = frame

	local search = Instance.new("TextBox")
	search.Name = "Search"
	search.LayoutOrder = 2
	search.Size = UDim2.fromOffset(120, 40)
	search.PlaceholderText = "Search items"
	search.Text = ""
	search.ClearTextOnFocus = false
	search.TextSize = 16
	search.TextXAlignment = Enum.TextXAlignment.Left
	search.Parent = frame

	local grow = Instance.new("UIFlexItem")
	grow.FlexMode = Enum.UIFlexMode.Grow
	grow.Parent = search

	local filter = button("Filter", "Filter")
	filter.LayoutOrder = 3
	filter.AutomaticSize = Enum.AutomaticSize.X
	filter.Size = UDim2.fromOffset(0, 40)
	filter.Parent = frame

	local filterPadding = Instance.new("UIPadding")
	filterPadding.PaddingLeft = UDim.new(0, 14)
	filterPadding.PaddingRight = UDim.new(0, 14)
	filterPadding.Parent = filter

	return { frame = frame, search = search, back = back, filter = filter }
end

return SearchToolbar
```

- The search box's 120 px width is its minimum; Grow only adds space, so on a tiny screen it never collapses below that.
- AutomaticSize on the filter button means a longer translated label widens the button instead of clipping.
- Use `Enum.UIFlexMode.Fill` instead when items should also shrink below their base size.

# Test
```lua
local bar = item.build()
local flex = bar.search:FindFirstChildOfClass("UIFlexItem")
check("search box grows", flex ~= nil and flex.FlexMode == Enum.UIFlexMode.Grow)
check("horizontal ordered layout", bar.frame.UIListLayout.FillDirection == Enum.FillDirection.Horizontal
	and bar.back.LayoutOrder < bar.search.LayoutOrder and bar.search.LayoutOrder < bar.filter.LayoutOrder)
check("filter sizes to its text", bar.filter.AutomaticSize == Enum.AutomaticSize.X)
check("buttons keep fixed sizes", bar.back:FindFirstChildOfClass("UIFlexItem") == nil and bar.back.Size.X.Offset == 72)
check("search keeps typed text on refocus", bar.search.ClearTextOnFocus == false)
```
