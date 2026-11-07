---
id: gb-ui-gamepad-menu-selection
category: ui-interaction
topics: GuiService.SelectedObject, NextSelectionDown, NextSelectionUp, gamepad, Selectable
source: original
---
# Request
On Xbox my pause menu opens but nothing is selected, so the player has to press the thumbstick around before anything happens, and pressing down on the last option jumps to some random HUD button. How do I make the menu controller-friendly?

# Answer
When the menu opens with a gamepad, select its first button through `GuiService.SelectedObject`, and wire `NextSelectionUp`/`NextSelectionDown` explicitly with wrap-around so the cursor never leaves the menu. On close, clear the selection only if it is still inside the menu.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.MenuNavigation
local GuiService = game:GetService("GuiService")

local MenuNavigation = {}

export type Nav = {
	open: (usingGamepad: boolean) -> (),
	close: () -> (),
}

function MenuNavigation.new(menu: GuiObject, buttons: { GuiButton }): Nav
	assert(#buttons > 0, "menu needs at least one button")
	local count = #buttons
	for i, button in buttons do
		button.Selectable = true
		button.NextSelectionUp = buttons[(i - 2) % count + 1]
		button.NextSelectionDown = buttons[i % count + 1]
		-- Left and right point back at the button itself so sideways input cannot escape to the HUD.
		button.NextSelectionLeft = button
		button.NextSelectionRight = button
	end

	local function open(usingGamepad: boolean)
		menu.Visible = true
		if usingGamepad then
			GuiService.SelectedObject = buttons[1]
		end
	end

	local function close()
		menu.Visible = false
		local selected = GuiService.SelectedObject
		if selected ~= nil and selected:IsDescendantOf(menu) then
			GuiService.SelectedObject = nil
		end
	end

	return { open = open, close = close }
end

return MenuNavigation
```

```lua
--!strict
-- LocalScript: wires the pause menu
local UserInputService = game:GetService("UserInputService")
local MenuNavigation = require(game:GetService("ReplicatedStorage"):WaitForChild("MenuNavigation"))

local function isGamepad(inputType: Enum.UserInputType): boolean
	return inputType.Name:sub(1, 7) == "Gamepad"
end

local function setup(menu: Frame, resume: TextButton, settings: TextButton, leave: TextButton)
	local nav = MenuNavigation.new(menu, { resume, settings, leave })
	return function(show: boolean)
		if show then
			nav.open(isGamepad(UserInputService:GetLastInputType()))
		else
			nav.close()
		end
	end
end

return setup
```

- Only selecting with a gamepad avoids the selection highlight appearing for mouse players.
- `(i - 2) % count + 1` is the previous index with wrap-around (1 goes to the last button).
- For grids, set all four `NextSelection*` per cell from row and column math the same way.

# Test
```lua
local GuiService = game:GetService("GuiService")
local menu = Instance.new("Frame")
local buttons = {}
for i = 1, 3 do
	local b = Instance.new("TextButton")
	b.Name = "Option" .. i
	b.Parent = menu
	buttons[i] = b
end
local nav = item.new(menu, buttons)
check("down wraps from last to first", buttons[3].NextSelectionDown == buttons[1])
check("up wraps from first to last", buttons[1].NextSelectionUp == buttons[3])
check("middle links both ways", buttons[2].NextSelectionUp == buttons[1] and buttons[2].NextSelectionDown == buttons[3])
nav.open(false)
check("mouse open leaves selection alone", GuiService.SelectedObject == nil and menu.Visible)
nav.open(true)
check("gamepad open selects the first option", GuiService.SelectedObject == buttons[1])
nav.close()
check("close clears selection inside the menu", GuiService.SelectedObject == nil and not menu.Visible)
local hud = Instance.new("TextButton")
GuiService.SelectedObject = hud
nav.close()
check("close keeps an outside selection", GuiService.SelectedObject == hud)
check("empty menu is rejected", not pcall(item.new, menu, {}))
```
