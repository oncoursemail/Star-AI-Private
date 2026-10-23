---
id: gb-ui-sidebar-content-split
category: ui-layout
topics: UDim2 scale and offset mix, split layout, narrow screens, AbsoluteSize, settings menu
source: original
---
# Request
My settings menu has a category list on the left and the options on the right. I want the list to be exactly 220 px wide and the options to take the rest, but on narrow phone screens the list should move on top instead. I've been trying `UDim2.new(0.75, 0, 1, 0)` for the options and the gap is never right.

# Answer
Mix Scale and Offset in one UDim2: the content is `UDim2.new(1, -220, 1, 0)` positioned at `UDim2.new(0, 220, 0, 0)`, which is "full width minus the sidebar" on every screen. For narrow windows switch to a stacked arrangement, decided from the container's AbsoluteSize in one function.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.SplitLayout
local SplitLayout = {}

export type Mode = "side" | "stacked"

local SIDEBAR_WIDTH = 220
local TABS_HEIGHT = 48
local STACK_BELOW = 560

function SplitLayout.modeFor(width: number): Mode
	return if width < STACK_BELOW then "stacked" else "side"
end

function SplitLayout.apply(mode: Mode, sidebar: GuiObject, content: GuiObject)
	if mode == "side" then
		sidebar.Position = UDim2.fromOffset(0, 0)
		sidebar.Size = UDim2.new(0, SIDEBAR_WIDTH, 1, 0)
		content.Position = UDim2.fromOffset(SIDEBAR_WIDTH, 0)
		content.Size = UDim2.new(1, -SIDEBAR_WIDTH, 1, 0)
	else
		sidebar.Position = UDim2.fromOffset(0, 0)
		sidebar.Size = UDim2.new(1, 0, 0, TABS_HEIGHT)
		content.Position = UDim2.fromOffset(0, TABS_HEIGHT)
		content.Size = UDim2.new(1, 0, 1, -TABS_HEIGHT)
	end
end

function SplitLayout.bind(container: GuiObject, sidebar: GuiObject, content: GuiObject): RBXScriptConnection
	local current: Mode? = nil
	local function update()
		local width: number = container.AbsoluteSize.X
		local mode = SplitLayout.modeFor(width)
		if mode ~= current then
			current = mode
			SplitLayout.apply(mode, sidebar, content)
		end
	end
	update()
	return container:GetPropertyChangedSignal("AbsoluteSize"):Connect(update)
end

return SplitLayout
```

- Scale 1 with Offset -220 always sums to exactly the remaining width; a pure Scale guess like 0.75 is only right at one resolution.
- In stacked mode, switch the sidebar's UIListLayout to horizontal so the categories become a tab row.
- Applying only on mode changes avoids rewriting sizes on every resize event.

# Test
```lua
local container, sidebar, content = Instance.new("Frame"), Instance.new("Frame"), Instance.new("Frame")
container.AbsoluteSize = Vector2.new(1000, 600)
local conn = item.bind(container, sidebar, content)
check("side by side on wide screens", content.Size.X.Scale == 1 and content.Size.X.Offset == -220 and content.Position.X.Offset == 220)
check("sidebar fixed width", sidebar.Size.X.Offset == 220 and sidebar.Size.X.Scale == 0)
container.AbsoluteSize = Vector2.new(420, 800)
check("stacked on narrow screens", sidebar.Size.X.Scale == 1 and content.Position.Y.Offset == 48 and content.Size.Y.Offset == -48)
check("threshold", item.modeFor(559) == "stacked" and item.modeFor(560) == "side")
conn:Disconnect()
```
