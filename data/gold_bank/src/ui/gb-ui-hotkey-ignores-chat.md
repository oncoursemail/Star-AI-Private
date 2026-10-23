---
id: gb-ui-hotkey-ignores-chat
category: ui-interaction
topics: UserInputService.InputBegan, gameProcessedEvent, hotkey, TextBox focus, inventory toggle
source: original
---
# Request
My inventory opens with the I key, but whenever someone types a word with an "i" in chat, the inventory pops open. Here's my code:

```lua
UIS.InputBegan:Connect(function(input)
	if input.KeyCode == Enum.KeyCode.I then
		inventory.Visible = not inventory.Visible
	end
end)
```

# Answer
InputBegan passes a second argument, `gameProcessedEvent`, which is true when the engine already used the input (typing in chat or any TextBox, clicking a core button). Return early when it is set. While at it, accept the controller's Y button so the hotkey works on console too.

```lua
--!strict
-- ModuleScript: StarterPlayerScripts.InventoryHotkey
local UserInputService = game:GetService("UserInputService")

local InventoryHotkey = {}

local KEYS = {
	[Enum.KeyCode.I] = true,
	[Enum.KeyCode.ButtonY] = true,
}

function InventoryHotkey.bind(inventory: GuiObject): RBXScriptConnection
	return UserInputService.InputBegan:Connect(function(input: InputObject, gameProcessedEvent: boolean)
		if gameProcessedEvent then
			return
		end
		if KEYS[input.KeyCode] then
			local visible: boolean = inventory.Visible
			inventory.Visible = not visible
		end
	end)
end

return InventoryHotkey
```

- `gameProcessedEvent` also covers your own TextBoxes, such as a search field inside the inventory, so typing "i" there no longer closes it.
- A lookup table of keys keeps rebinding in one place; add `Enum.KeyCode.Tab` or similar without touching the handler.
- For actions that should also get a mobile button, ContextActionService is the better fit; for a plain toggle this is enough.

# Test
```lua
local UIS = game:GetService("UserInputService")
local inventory = Instance.new("Frame")
inventory.Visible = false
local conn = item.bind(inventory)
UIS.InputBegan:Fire({ KeyCode = Enum.KeyCode.I, UserInputType = Enum.UserInputType.Keyboard }, true)
check("typing in chat is ignored", inventory.Visible == false)
UIS.InputBegan:Fire({ KeyCode = Enum.KeyCode.I, UserInputType = Enum.UserInputType.Keyboard }, false)
check("I opens the inventory", inventory.Visible == true)
UIS.InputBegan:Fire({ KeyCode = Enum.KeyCode.ButtonY, UserInputType = Enum.UserInputType.Gamepad1 }, false)
check("controller Y toggles it closed", inventory.Visible == false)
UIS.InputBegan:Fire({ KeyCode = Enum.KeyCode.K, UserInputType = Enum.UserInputType.Keyboard }, false)
check("other keys do nothing", inventory.Visible == false)
conn:Disconnect()
```
