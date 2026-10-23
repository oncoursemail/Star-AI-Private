---
id: gb-ui-dropdown-outside-click
category: ui-interaction
topics: dropdown, click outside to close, AbsolutePosition, AbsoluteSize, InputBegan
source: original
---
# Request
I made a dropdown for picking a graphics preset. It opens fine, but it only closes when you pick an option. Players expect it to close when they click or tap anywhere else. How do I detect a click outside it?

# Answer
While the dropdown is open, listen to `UserInputService.InputBegan` for mouse and touch presses and test whether the press position lies inside the header or the option list, using their AbsolutePosition and AbsoluteSize. A press outside both closes it. The hit test is a tiny pure function.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Dropdown
local UserInputService = game:GetService("UserInputService")

local Dropdown = {}

export type Dropdown = {
	open: () -> (),
	close: () -> (),
	isOpen: () -> boolean,
}

function Dropdown.contains(position: Vector2, size: Vector2, point: Vector2): boolean
	local px: number, py: number = point.X, point.Y
	local x: number, y: number = position.X, position.Y
	local w: number, h: number = size.X, size.Y
	return px >= x and px <= x + w and py >= y and py <= y + h
end

local function hit(gui: GuiObject, point: Vector2): boolean
	return gui.Visible and Dropdown.contains(gui.AbsolutePosition, gui.AbsoluteSize, point)
end

function Dropdown.new(header: GuiButton, list: GuiObject): Dropdown
	local outside: RBXScriptConnection? = nil

	local function close()
		list.Visible = false
		if outside then
			outside:Disconnect()
			outside = nil
		end
	end

	local function open()
		list.Visible = true
		if outside then
			return
		end
		outside = UserInputService.InputBegan:Connect(function(input: InputObject)
			local kind = input.UserInputType
			if kind ~= Enum.UserInputType.MouseButton1 and kind ~= Enum.UserInputType.Touch then
				return
			end
			local point = Vector2.new(input.Position.X, input.Position.Y)
			if not hit(list, point) and not hit(header, point) then
				close()
			end
		end)
	end

	header.Activated:Connect(function()
		if list.Visible then
			close()
		else
			open()
		end
	end)

	return {
		open = open,
		close = close,
		isOpen = function()
			return list.Visible
		end,
	}
end

return Dropdown
```

- Presses on the header are ignored by the outside check, so the header's own toggle is not fought by an immediate close.
- `gameProcessedEvent` is not checked on purpose: a press on another button still counts as "outside" and should close the list.
- If the option list sits inside a clipped or scrolling frame, also test against that frame, or presses on clipped-away options would count as inside.

# Test
```lua
local UIS = game:GetService("UserInputService")
check("inside", item.contains(Vector2.new(10, 10), Vector2.new(100, 50), Vector2.new(60, 30)))
check("on the edge counts", item.contains(Vector2.new(10, 10), Vector2.new(100, 50), Vector2.new(110, 60)))
check("outside", not item.contains(Vector2.new(10, 10), Vector2.new(100, 50), Vector2.new(111, 30)))
local header = Instance.new("TextButton")
header.AbsolutePosition = Vector2.new(100, 100)
header.AbsoluteSize = Vector2.new(200, 40)
local list = Instance.new("Frame")
list.Visible = false
list.AbsolutePosition = Vector2.new(100, 140)
list.AbsoluteSize = Vector2.new(200, 160)
local dd = item.new(header, list)
header.Activated:Fire()
check("header opens", dd.isOpen())
UIS.InputBegan:Fire({ UserInputType = Enum.UserInputType.MouseButton1, Position = Vector3.new(150, 200, 0) }, false)
check("press inside the list keeps it open", dd.isOpen())
UIS.InputBegan:Fire({ UserInputType = Enum.UserInputType.MouseMovement, Position = Vector3.new(900, 600, 0) }, false)
check("mouse movement ignored", dd.isOpen())
UIS.InputBegan:Fire({ UserInputType = Enum.UserInputType.Touch, Position = Vector3.new(900, 600, 0) }, false)
check("tap outside closes", not dd.isOpen())
```
