---
id: gb-ui-modal-backdrop-close
category: ui-interaction
topics: modal dialog, backdrop, ContextActionService, ButtonB, GuiService.SelectedObject
source: original
---
# Request
Write me a reusable confirm-style modal for my game: a dark backdrop that blocks clicks to the HUD behind it, closes when you click the backdrop, the close button, or press B on a controller, and gives gamepad selection back to whatever was selected before.

# Answer
Build the modal as one root frame holding a full-screen backdrop button and a centred panel. Bind ButtonB at high priority only while the modal is open, under an action name unique to that modal, and sink it so nothing underneath also reacts; every close path goes through one idempotent `close`.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Modal
local ContextActionService = game:GetService("ContextActionService")
local GuiService = game:GetService("GuiService")

local Modal = {}

export type Handle = {
	root: Frame,
	close: () -> (),
	isOpen: () -> boolean,
}

local ACTION_PREFIX = "CloseModal"
local opened = 0

local function makeLabel(text: string, size: UDim2, position: UDim2, textSize: number): TextLabel
	local label = Instance.new("TextLabel")
	label.BackgroundTransparency = 1
	label.Size = size
	label.Position = position
	label.TextSize = textSize
	label.TextWrapped = true
	label.TextColor3 = Color3.fromRGB(236, 236, 240)
	label.TextXAlignment = Enum.TextXAlignment.Left
	label.Text = text
	return label
end

function Modal.open(screenGui: ScreenGui, title: string, body: string, onClose: (() -> ())?): Handle
	local open = true
	opened += 1
	-- One name per modal: with a shared name, closing a stacked modal would unbind the one still open.
	local action = ACTION_PREFIX .. opened
	local previousSelection = GuiService.SelectedObject
	local connections: { RBXScriptConnection } = {}

	local root = Instance.new("Frame")
	root.Name = "Modal"
	root.Size = UDim2.fromScale(1, 1)
	root.BackgroundTransparency = 1
	root.ZIndex = 50

	-- A button, not a Frame, so clicks land here instead of on the HUD below.
	local backdrop = Instance.new("TextButton")
	backdrop.Name = "Backdrop"
	backdrop.Size = UDim2.fromScale(1, 1)
	backdrop.BackgroundColor3 = Color3.new(0, 0, 0)
	backdrop.BackgroundTransparency = 0.45
	backdrop.AutoButtonColor = false
	backdrop.Selectable = false
	backdrop.Text = ""
	backdrop.Parent = root

	local panel = Instance.new("Frame")
	panel.Name = "Panel"
	panel.AnchorPoint = Vector2.new(0.5, 0.5)
	panel.Position = UDim2.fromScale(0.5, 0.5)
	panel.Size = UDim2.new(0.4, 0, 0, 200)
	panel.BackgroundColor3 = Color3.fromRGB(32, 34, 40)
	panel.Parent = root

	makeLabel(title, UDim2.new(1, -32, 0, 28), UDim2.fromOffset(16, 14), 22).Parent = panel
	makeLabel(body, UDim2.new(1, -32, 1, -110), UDim2.fromOffset(16, 50), 16).Parent = panel

	local closeButton = Instance.new("TextButton")
	closeButton.Name = "Close"
	closeButton.AnchorPoint = Vector2.new(1, 1)
	closeButton.Position = UDim2.new(1, -16, 1, -16)
	closeButton.Size = UDim2.fromOffset(110, 40)
	closeButton.BackgroundColor3 = Color3.fromRGB(58, 62, 72)
	closeButton.TextColor3 = Color3.fromRGB(240, 240, 240)
	closeButton.TextSize = 18
	closeButton.Text = "Close"
	closeButton.Parent = panel

	local function close()
		if not open then
			return
		end
		open = false
		ContextActionService:UnbindAction(action)
		for _, connection in connections do
			connection:Disconnect()
		end
		root:Destroy()
		if previousSelection ~= nil and previousSelection.Parent ~= nil then
			GuiService.SelectedObject = previousSelection
		else
			GuiService.SelectedObject = nil
		end
		if onClose then
			onClose()
		end
	end

	local function onBack(_action: string, state: Enum.UserInputState, _input: InputObject): Enum.ContextActionResult
		if state ~= Enum.UserInputState.Begin then
			return Enum.ContextActionResult.Pass
		end
		close()
		return Enum.ContextActionResult.Sink
	end

	connections = { backdrop.Activated:Connect(close), closeButton.Activated:Connect(close) }
	ContextActionService:BindActionAtPriority(action, onBack, false, Enum.ContextActionPriority.High.Value, Enum.KeyCode.ButtonB)

	root.Parent = screenGui
	GuiService.SelectedObject = closeButton

	return {
		root = root,
		close = close,
		isOpen = function()
			return open
		end,
	}
end

return Modal
```

- Give the modal's ScreenGui a higher `DisplayOrder` than the HUD so it draws on top regardless of creation order.
- Escape belongs to the Roblox menu, so keyboard players close with the button or the backdrop; ButtonB is the console convention for "back".
- A stacked modal binds after the one below it at the same priority, so B closes the top one first; each modal unbinds only its own action.
- Returning `Pass` for the release keeps the binding from swallowing input it did not use.
- Restoring the old selection only if it still exists avoids pointing the gamepad at a destroyed button.

# Test
```lua
local GuiService = game:GetService("GuiService")
local CAS = game:GetService("ContextActionService")
local gui = Instance.new("ScreenGui")
local hudButton = Instance.new("TextButton")
hudButton.Parent = gui
GuiService.SelectedObject = hudButton
local closed = 0
local modal = item.open(gui, "Leave match?", "You will lose this round's progress.", function()
	closed += 1
end)
local function boundNames()
	local names = {}
	for name in CAS.__bound do
		if string.sub(name, 1, 10) == "CloseModal" then
			table.insert(names, name)
		end
	end
	return names
end
check("selection moves into the modal", GuiService.SelectedObject == modal.root.Panel.Close)
local names = boundNames()
check("ButtonB bound while open", #names == 1 and CAS.__bound[names[1]].inputs[1] == Enum.KeyCode.ButtonB)
local bound = CAS.__bound[names[1]]
check("release passes through", bound.fn(names[1], Enum.UserInputState.End, {}) == Enum.ContextActionResult.Pass and modal.isOpen())
check("press closes and sinks", bound.fn(names[1], Enum.UserInputState.Begin, {}) == Enum.ContextActionResult.Sink)
check("closed, unbound and destroyed", not modal.isOpen() and #boundNames() == 0 and modal.root.Parent == nil)
check("selection restored", GuiService.SelectedObject == hudButton)
modal.close()
check("onClose runs once", closed == 1)
local second = item.open(gui, "Info", "Text")
second.root.Backdrop.Activated:Fire()
check("backdrop click closes", not second.isOpen())
local lower = item.open(gui, "Settings", "Lower modal")
local upper = item.open(gui, "Confirm", "Upper modal")
check("stacked modals each bind their own action", #boundNames() == 2)
upper.close()
check("closing the top modal keeps B bound for the one below", lower.isOpen() and #boundNames() == 1)
check("selection returns to the lower modal", GuiService.SelectedObject == lower.root.Panel.Close)
lower.close()
check("all bindings gone", #boundNames() == 0)
```
