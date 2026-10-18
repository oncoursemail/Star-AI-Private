```luau
local Players = game:GetService("Players")

local Theme = {
	ink = Color3.fromRGB(240, 240, 236),
	muted = Color3.fromRGB(180, 182, 176),
	scrim = Color3.fromRGB(24, 26, 31),
	font = "rbxasset://fonts/families/GothamSSm.json",
}

local gui = Instance.new("ScreenGui")
gui.Name = "Hud"
gui.ResetOnSpawn = false

local corner = Instance.new("Frame")
corner.Name = "TopLeft"
corner.Position = UDim2.new(0, 16, 0, 16)
corner.Size = UDim2.new(0.28, 0, 0.2, 0)
corner.BackgroundColor3 = Theme.scrim
corner.BackgroundTransparency = 0.25
corner.Parent = gui
local round = Instance.new("UICorner")
round.CornerRadius = UDim.new(0, 8)
round.Parent = corner
local pad = Instance.new("UIPadding")
pad.PaddingLeft = UDim.new(0, 16)
pad.PaddingRight = UDim.new(0, 16)
pad.PaddingTop = UDim.new(0, 12)
pad.PaddingBottom = UDim.new(0, 12)
pad.Parent = corner
local sizeLimit = Instance.new("UISizeConstraint")
sizeLimit.MinSize = Vector2.new(180, 96)
sizeLimit.MaxSize = Vector2.new(360, 200)
sizeLimit.Parent = corner
local list = Instance.new("UIListLayout")
list.Padding = UDim.new(0, 4)
list.SortOrder = Enum.SortOrder.LayoutOrder
list.Parent = corner

local function hudLabel(name: string, value: string): TextLabel
	local t = Instance.new("TextLabel")
	t.Name = name
	t.Text = value
	t.FontFace = Font.new(Theme.font, Enum.FontWeight.SemiBold)
	t.TextSize = 18
	t.TextColor3 = Theme.ink
	t.TextXAlignment = Enum.TextXAlignment.Left
	t.BackgroundTransparency = 1
	t.Size = UDim2.new(1, 0, 0, 24)
	t.Parent = corner
	return t
end

hudLabel("Pickaxe durability", "Pickaxe durability: 0")
hudLabel("Ore carried", "Ore carried: 0")
hudLabel("Depth", "Depth: 0")
hudLabel("Oxygen", "Oxygen: 0")

gui.Parent = Players.LocalPlayer:WaitForChild("PlayerGui")
```
