---
id: gb-ui-button-visual-states
category: ui-interaction
topics: TextButton, hover, pressed, disabled, AutoButtonColor, gamepad selection
source: original
---
# Request
I want my buttons to have proper hover, pressed and disabled looks instead of the default darkening, and a disabled button must not do anything when clicked. Controller players should see the hover look on the selected button too. How would you structure that?

# Answer
Derive the look from a few booleans (enabled, hovering, pressing) through one `visual()` function and render from it, so the states cannot contradict each other. Turn `AutoButtonColor` off, treat gamepad selection like hover, and guard the click handler itself rather than relying on looks.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.StatefulButton
local StatefulButton = {}

export type Visual = "idle" | "hover" | "pressed" | "disabled"
export type Button = {
	instance: TextButton,
	setEnabled: (enabled: boolean) -> (),
	visual: () -> Visual,
	destroy: () -> (),
}

local FILL: { [Visual]: Color3 } = {
	idle = Color3.fromRGB(38, 99, 196),
	hover = Color3.fromRGB(52, 116, 216),
	pressed = Color3.fromRGB(30, 80, 160),
	disabled = Color3.fromRGB(64, 68, 76),
}

function StatefulButton.new(text: string, onActivated: () -> ()): Button
	local enabled, hovering, pressing = true, false, false

	local button = Instance.new("TextButton")
	button.AutoButtonColor = false
	button.Size = UDim2.fromOffset(180, 44)
	button.TextSize = 18
	button.TextColor3 = Color3.fromRGB(255, 255, 255)
	button.Text = text

	local function visual(): Visual
		if not enabled then
			return "disabled"
		elseif pressing then
			return "pressed"
		elseif hovering then
			return "hover"
		end
		return "idle"
	end

	local function render()
		local v = visual()
		button.BackgroundColor3 = FILL[v]
		button.TextTransparency = if v == "disabled" then 0.5 else 0
	end

	local function setHover(on: boolean)
		hovering = on
		if not on then
			pressing = false
		end
		render()
	end

	local connections = {
		button.MouseEnter:Connect(function()
			setHover(true)
		end),
		button.MouseLeave:Connect(function()
			setHover(false)
		end),
		button.SelectionGained:Connect(function()
			setHover(true)
		end),
		button.SelectionLost:Connect(function()
			setHover(false)
		end),
		button.MouseButton1Down:Connect(function()
			pressing = true
			render()
		end),
		button.MouseButton1Up:Connect(function()
			pressing = false
			render()
		end),
		button.Activated:Connect(function()
			if enabled then
				onActivated()
			end
		end),
	}

	local function setEnabled(value: boolean)
		enabled = value
		pressing = false
		button.Selectable = value
		render()
	end

	local function destroy()
		for _, connection in connections do
			connection:Disconnect()
		end
		button:Destroy()
	end

	render()
	return { instance = button, setEnabled = setEnabled, visual = visual, destroy = destroy }
end

return StatefulButton
```

- The disabled look is a muted fill plus faded text, not just a colour change, so it reads for colour-blind players too.
- `Selectable = false` while disabled stops the gamepad cursor landing on a button that cannot be used.
- Leaving the button cancels the press, which matches how a release outside a button does not click it.
- For buttons that send a request, disable on click and re-enable when the server answers.

# Test
```lua
local clicks = 0
local b = item.new("Buy", function()
	clicks += 1
end)
local btn = b.instance
check("starts idle", b.visual() == "idle" and btn.AutoButtonColor == false)
btn.MouseEnter:Fire()
check("hover", b.visual() == "hover")
btn.MouseButton1Down:Fire()
check("pressed look while held", b.visual() == "pressed" and btn.BackgroundColor3 == Color3.fromRGB(30, 80, 160))
btn.MouseLeave:Fire()
check("leaving cancels the press", b.visual() == "idle")
btn.Activated:Fire()
check("enabled click runs", clicks == 1)
b.setEnabled(false)
btn.Activated:Fire()
btn.MouseEnter:Fire()
check("disabled ignores clicks and hover", clicks == 1 and b.visual() == "disabled" and btn.Selectable == false)
btn.SelectionGained:Fire()
b.setEnabled(true)
check("gamepad selection shows hover", b.visual() == "hover")
```
