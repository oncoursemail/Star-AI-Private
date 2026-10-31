---
id: gb-ui-drag-reorder-loadout
category: ui-interaction
topics: drag and drop, reorder list, InputChanged, drop index, loadout
source: original
---
# Request
I want players to reorder their loadout list by dragging a row up or down. I have the drag following the mouse, but I can't figure out how to work out where it should be dropped and how to reorder the table without bugs at the ends.

# Answer
Split it in two pure pieces: the drop index from the pointer's Y inside the list (clamped to the ends), and a `moveItem` that returns a new array with one element moved. The UI just feeds the pointer position in on release and redraws from the returned order.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Reorder
local Reorder = {}

-- Index (1..count) of the slot under `localY`, measured from the top of the list.
function Reorder.dropIndex(localY: number, rowHeight: number, gap: number, count: number): number
	assert(rowHeight > 0 and count >= 1, "invalid list")
	local index = math.floor(localY / (rowHeight + gap)) + 1
	return math.clamp(index, 1, count)
end

function Reorder.moveItem<T>(list: { T }, from: number, to: number): { T }
	local out: { T } = {}
	local moving = list[from]
	assert(moving ~= nil, "from is out of range")
	for i, value in list do
		if i ~= from then
			out[#out + 1] = value
		end
	end
	local target = math.clamp(to, 1, #out + 1)
	for i = #out, target, -1 do
		out[i + 1] = out[i]
	end
	out[target] = moving
	return out
end

return Reorder
```

```lua
--!strict
-- LocalScript: drives the drag for a loadout list
local UserInputService = game:GetService("UserInputService")
local Reorder = require(game:GetService("ReplicatedStorage"):WaitForChild("Reorder"))

local ROW, GAP = 44, 4

local function enableDrag(list: Frame, getOrder: () -> { string }, setOrder: (order: { string }) -> ())
	for _, row in list:GetChildren() do
		if not row:IsA("GuiButton") then
			continue
		end
		local connection = row.MouseButton1Down:Connect(function()
			local from = row.LayoutOrder
			local released: RBXScriptConnection
			released = UserInputService.InputEnded:Connect(function(input: InputObject)
				if input.UserInputType ~= Enum.UserInputType.MouseButton1 and input.UserInputType ~= Enum.UserInputType.Touch then
					return
				end
				released:Disconnect()
				local order = getOrder()
				local pointerY: number = input.Position.Y
				local top: number = list.AbsolutePosition.Y
				setOrder(Reorder.moveItem(order, from, Reorder.dropIndex(pointerY - top, ROW, GAP, #order)))
			end)
		end)
		row.Destroying:Once(function()
			connection:Disconnect()
		end)
	end
end

return enableDrag
```

- `moveItem` never mutates the input, so a cancelled drag simply keeps the old table and nothing is half-updated.
- Clamping the drop index means releasing above the first row or below the last one still lands at an end.
- Rows read their current position from `LayoutOrder`, so after `setOrder` redraws, the next drag uses the new order.
- If the order matters to the server (an equip order), send the new order as a list of item ids and validate that it is a permutation of what the player owns.

# Test
```lua
check("drop index inside the list", item.dropIndex(100, 44, 4, 5) == 3)
check("above the list clamps to first", item.dropIndex(-30, 44, 4, 5) == 1)
check("below the list clamps to last", item.dropIndex(9999, 44, 4, 5) == 5)
local list = { "Sword", "Bow", "Potion", "Shield" }
local down = item.moveItem(list, 1, 3)
check("move down", table.concat(down, ",") == "Bow,Potion,Sword,Shield")
local up = item.moveItem(list, 4, 1)
check("move up to the top", table.concat(up, ",") == "Shield,Sword,Bow,Potion")
check("input untouched", table.concat(list, ",") == "Sword,Bow,Potion,Shield")
check("same slot is a no-op", table.concat(item.moveItem(list, 2, 2), ",") == "Sword,Bow,Potion,Shield")
check("bad index rejected", not pcall(item.moveItem, list, 9, 1))
```
