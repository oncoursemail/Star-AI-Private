---
id: gb-ui-sidebar-layoutorder
category: ui-layout
topics: UIListLayout, SortOrder, LayoutOrder, UIPadding, sidebar menu
source: original
---
# Request
Weird bug: my main menu is supposed to read Play / Shop / Settings / Credits from top to bottom, and that's the order my table has, yet in game it shows Credits first and Shop last. The frame has a UIListLayout in it.

```lua
local names = { "Play", "Shop", "Settings", "Credits" }
for i = 1, #names do
	local btn = template:Clone()
	btn.Name = names[i]
	btn.Text = names[i]
	btn.Parent = menuFrame
end
```

# Answer
Credits, Play, Settings, Shop is alphabetical: that layout's `SortOrder` is `Name`, so creation order is ignored. Set `SortOrder = Enum.SortOrder.LayoutOrder` and give each button its index as `LayoutOrder`; add UIPadding and the layout's `Padding` for spacing instead of offsetting buttons by hand.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Sidebar
local Sidebar = {}

export type Entry = { id: string, label: string }

function Sidebar.build(entries: { Entry }, onSelect: (id: string) -> ()): (Frame, { RBXScriptConnection })
	local frame = Instance.new("Frame")
	frame.Name = "Sidebar"
	frame.Size = UDim2.new(0, 200, 1, 0)
	frame.BackgroundColor3 = Color3.fromRGB(26, 28, 33)

	local layout = Instance.new("UIListLayout")
	layout.SortOrder = Enum.SortOrder.LayoutOrder
	layout.FillDirection = Enum.FillDirection.Vertical
	layout.Padding = UDim.new(0, 6)
	layout.Parent = frame

	local padding = Instance.new("UIPadding")
	padding.PaddingTop = UDim.new(0, 16)
	padding.PaddingLeft = UDim.new(0, 12)
	padding.PaddingRight = UDim.new(0, 12)
	padding.Parent = frame

	local connections: { RBXScriptConnection } = {}
	for index, entry in entries do
		local button = Instance.new("TextButton")
		button.Name = entry.id
		button.LayoutOrder = index
		button.Size = UDim2.new(1, 0, 0, 40)
		button.BackgroundColor3 = Color3.fromRGB(40, 43, 50)
		button.TextColor3 = Color3.fromRGB(236, 236, 240)
		button.TextSize = 18
		button.TextXAlignment = Enum.TextXAlignment.Left
		button.Text = entry.label
		button.Parent = frame
		local connection = button.Activated:Connect(function()
			onSelect(entry.id)
		end)
		table.insert(connections, connection)
	end

	return frame, connections
end

return Sidebar
```

- Give every item a distinct LayoutOrder (equal values leave the order to the engine); leaving gaps (10, 20, 30) makes later inserts easy.
- Button ids stay stable for code while labels can change or be translated.
- The connections are returned so the caller can disconnect them if it rebuilds the menu.

# Test
```lua
local picked = nil
local frame, conns = item.build({
	{ id = "Play", label = "Play" },
	{ id = "Shop", label = "Shop" },
	{ id = "Settings", label = "Settings" },
	{ id = "Credits", label = "Credits" },
}, function(id)
	picked = id
end)
check("layout sorts by LayoutOrder", frame.UIListLayout.SortOrder == Enum.SortOrder.LayoutOrder)
check("creation order kept", frame.Play.LayoutOrder == 1 and frame.Credits.LayoutOrder == 4)
check("spacing from layout padding", frame.UIListLayout.Padding.Offset == 6)
frame.Settings.Activated:Fire()
check("clicks report the id", picked == "Settings")
check("one connection per button", #conns == 4)
```
