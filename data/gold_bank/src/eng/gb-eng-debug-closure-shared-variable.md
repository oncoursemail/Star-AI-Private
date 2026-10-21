---
id: gb-eng-debug-closure-shared-variable
category: engineering-debugging
topics: closures, upvalues, loop variables, button handlers, shop UI
source: original
---
# Request
I build one button per shop item in a loop, but every button buys the last item in the list. Why?

```lua
local item
local index = 1
while index <= #catalog do
	item = catalog[index]
	local button = template:Clone()
	button.Text = item.name
	button.Parent = frame
	button.Activated:Connect(function()
		buyRemote:FireServer(item.id)
	end)
	index += 1
end
```

# Answer
A closure captures the variable, not its value at the time. All handlers share the single `item` declared above the loop, and by the time anyone clicks, the loop has finished and `item` holds the last entry. Declare the variable inside the loop body (a new local per iteration), or use a numeric/generic `for`, whose loop variables are fresh for every iteration in Luau.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.ShopButtons (client)
export type CatalogEntry = { id: string, name: string }

local ShopButtons = {}

function ShopButtons.build(catalog: { CatalogEntry }, template: TextButton, frame: GuiObject, onBuy: (id: string) -> ()): { TextButton }
	local buttons: { TextButton } = {}
	for _, entry in catalog do
		-- `entry` is a new local each iteration, so each handler keeps its own item
		local button = template:Clone()
		button.Name = entry.id
		button.Text = entry.name
		button.Activated:Connect(function()
			onBuy(entry.id)
		end)
		button.Parent = frame
		table.insert(buttons, button)
	end
	return buttons
end

return ShopButtons
```

- Passing `onBuy` in (for example `function(id) buyRemote:FireServer(id) end`) keeps the module testable and the remote in one place.
- The id is the only thing sent; the server looks up the price in its own catalog and checks the player's coins, so a client cannot buy at a forged price.
- The same trap exists with any variable declared outside a loop and assigned inside it, including `local i = 0; while ... do i += 1 ... end`.

# Test
```lua
local frame = Instance.new("Frame")
local template = Instance.new("TextButton")
local bought = {}
local buttons = item.build({
	{ id = "sword", name = "Sword" },
	{ id = "shield", name = "Shield" },
	{ id = "potion", name = "Potion" },
}, template, frame, function(id)
	table.insert(bought, id)
end)
buttons[1].Activated:Fire()
buttons[2].Activated:Fire()
buttons[3].Activated:Fire()
check("each button buys its own item", bought[1] == "sword" and bought[2] == "shield" and bought[3] == "potion")
check("buttons parented and labelled", #frame:GetChildren() == 3 and buttons[2].Text == "Shield")
check("template untouched", template.Parent == nil and #item.build({}, template, frame, function() end) == 0)
```
