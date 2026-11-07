---
id: gb-ui-topbar-inset-button
category: ui-layout
topics: GuiService.TopbarInset, top bar, IgnoreGuiInset, ScreenInsets, custom topbar button
source: original
---
# Request
I want a small "Codes" button up in the Roblox top bar row, next to the menu and chat buttons. I hard-coded `Position = UDim2.new(0, 104, 0, 4)` but it overlaps the Roblox buttons on some devices and floats too low on others. How do I place it correctly?

# Answer
Read `GuiService.TopbarInset`: a Rect of the free part of the top bar, in screen pixels. Put the button in a ScreenGui that ignores the inset and has no ScreenInsets so its coordinates match the screen, place it at the start of that free area with the bar's height, and follow the property when it changes. Hide it when the free area is too narrow.

```lua
--!strict
-- ModuleScript: StarterPlayerScripts.TopbarButton
local GuiService = game:GetService("GuiService")

local TopbarButton = {}

local GAP = 8
local WIDTH = 84

function TopbarButton.mount(playerGui: Instance, text: string, onClick: () -> ()): (TextButton, () -> ())
	local gui = Instance.new("ScreenGui")
	gui.Name = "TopbarExtras"
	gui.IgnoreGuiInset = true
	gui.ScreenInsets = Enum.ScreenInsets.None
	gui.ResetOnSpawn = false
	gui.DisplayOrder = 5

	local button = Instance.new("TextButton")
	button.Name = "TopbarButton"
	button.BackgroundColor3 = Color3.fromRGB(18, 19, 23)
	button.BackgroundTransparency = 0.3
	button.TextColor3 = Color3.fromRGB(255, 255, 255)
	button.TextSize = 16
	button.Text = text
	button.Parent = gui

	local corner = Instance.new("UICorner")
	corner.CornerRadius = UDim.new(1, 0)
	corner.Parent = button

	local function place()
		local inset = GuiService.TopbarInset
		local left: number, top: number = inset.Min.X, inset.Min.Y
		local height: number, freeWidth: number = inset.Height, inset.Width
		button.Visible = height > 0 and freeWidth >= WIDTH + GAP
		local buttonHeight = math.max(height - GAP, 0)
		button.Size = UDim2.fromOffset(WIDTH, buttonHeight)
		button.Position = UDim2.fromOffset(left + GAP, top + (height - buttonHeight) / 2)
	end

	local connections = {
		GuiService:GetPropertyChangedSignal("TopbarInset"):Connect(place),
		button.Activated:Connect(onClick),
	}
	place()
	gui.Parent = playerGui

	return button, function()
		for _, connection in connections do
			connection:Disconnect()
		end
		gui:Destroy()
	end
end

return TopbarButton
```

- TopbarInset already accounts for the platform and changes when Roblox adds or removes its own buttons, which the property listener follows.
- A zero-height inset means there is no top bar space to use, so the button hides instead of sitting at the very top.
- The pill corner (`UDim.new(1, 0)`) matches the shape of the Roblox buttons it sits beside.

# Test
```lua
local GuiService = game:GetService("GuiService")
GuiService.TopbarInset = { Min = Vector2.new(120, 0), Max = Vector2.new(1180, 58), Width = 1060, Height = 58 }
local clicks = 0
local playerGui = Instance.new("Folder")
local button, unmount = item.mount(playerGui, "Codes", function()
	clicks += 1
end)
check("starts after the Roblox buttons", button.Position.X.Offset == 128)
check("matches the bar height", button.Size.Y.Offset == 50 and button.Position.Y.Offset == 4)
GuiService.TopbarInset = { Min = Vector2.new(60, 0), Max = Vector2.new(800, 44), Width = 740, Height = 44 }
check("follows inset changes", button.Position.X.Offset == 68 and button.Size.Y.Offset == 36)
GuiService.TopbarInset = { Min = Vector2.new(0, 0), Max = Vector2.new(0, 0), Width = 0, Height = 0 }
check("hidden without a top bar", button.Visible == false)
button.Activated:Fire()
check("click handler wired", clicks == 1)
unmount()
check("unmount removes the gui", playerGui:FindFirstChild("TopbarExtras") == nil)
```
