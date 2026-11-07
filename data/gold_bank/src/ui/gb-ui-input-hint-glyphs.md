---
id: gb-ui-input-hint-glyphs
category: ui-interaction
topics: LastInputTypeChanged, input hints, gamepad, touch, keyboard prompts
source: original
---
# Request
My hint text says "Press E to open" everywhere, which is wrong for controller and mobile players. How do I switch the hint when the player changes input device mid-game, like picking up a controller?

# Answer
Map every `UserInputType` to one of three families (keyboard and mouse, gamepad, touch), listen to `UserInputService.LastInputTypeChanged`, and only update labels when the family actually changes. Mouse movement and focus events then do not cause flicker.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.InputHints
local UserInputService = game:GetService("UserInputService")

local InputHints = {}

export type Family = "keyboard" | "gamepad" | "touch"

function InputHints.familyOf(inputType: Enum.UserInputType): Family?
	if inputType == Enum.UserInputType.Touch then
		return "touch"
	elseif string.sub(inputType.Name, 1, 7) == "Gamepad" then
		return "gamepad"
	elseif inputType == Enum.UserInputType.Keyboard
		or inputType == Enum.UserInputType.MouseButton1
		or inputType == Enum.UserInputType.MouseButton2
		or inputType == Enum.UserInputType.MouseMovement
		or inputType == Enum.UserInputType.MouseWheel then
		return "keyboard"
	end
	return nil
end

local HINTS: { [Family]: string } = {
	keyboard = "Press E to open",
	gamepad = "Press X to open",
	touch = "Tap to open",
}

function InputHints.bind(label: TextLabel): RBXScriptConnection
	local current: Family = InputHints.familyOf(UserInputService:GetLastInputType()) or "keyboard"
	label.Text = HINTS[current]
	return UserInputService.LastInputTypeChanged:Connect(function(inputType: Enum.UserInputType)
		local family = InputHints.familyOf(inputType)
		if family ~= nil and family ~= current then
			current = family
			label.Text = HINTS[current]
		end
	end)
end

return InputHints
```

- Types such as `Focus`, `Gyro` and `TextInput` return nil and are ignored, so alt-tabbing does not reset a controller player to keyboard hints.
- Keep the key in one place: if the interact key changes, edit the hint table together with the binding.
- ProximityPrompts already switch their own glyphs; use this for your custom hints and tutorials.

# Test
```lua
local UIS = game:GetService("UserInputService")
check("gamepad family", item.familyOf(Enum.UserInputType.Gamepad2) == "gamepad")
check("touch family", item.familyOf(Enum.UserInputType.Touch) == "touch")
check("mouse counts as keyboard", item.familyOf(Enum.UserInputType.MouseMovement) == "keyboard")
check("focus ignored", item.familyOf(Enum.UserInputType.Focus) == nil)
local label = Instance.new("TextLabel")
local conn = item.bind(label)
check("starts from the last input", label.Text == "Press E to open")
UIS.LastInputTypeChanged:Fire(Enum.UserInputType.Gamepad1)
check("switches to controller hint", label.Text == "Press X to open")
UIS.LastInputTypeChanged:Fire(Enum.UserInputType.Focus)
check("non-device events keep the hint", label.Text == "Press X to open")
UIS.LastInputTypeChanged:Fire(Enum.UserInputType.Touch)
check("switches to touch", label.Text == "Tap to open")
conn:Disconnect()
```
