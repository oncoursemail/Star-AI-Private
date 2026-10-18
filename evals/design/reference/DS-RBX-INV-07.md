```luau
local Players = game:GetService("Players")
local TweenService = game:GetService("TweenService")

local Theme = {
	ground = Color3.fromRGB(24, 26, 31),
	surface = Color3.fromRGB(40, 43, 50),
	surfaceHover = Color3.fromRGB(52, 56, 64),
	ink = Color3.fromRGB(240, 240, 236),
	muted = Color3.fromRGB(180, 182, 176),
	accent = Color3.fromRGB(31, 79, 90),
	font = "rbxasset://fonts/families/GothamSSm.json",
	pad = 16,
	radius = 8,
}
local tweenOut = TweenInfo.new(0.12, Enum.EasingStyle.Quad, Enum.EasingDirection.Out)

local function text(parent: Instance, label: string, size: number, weight, color: Color3): TextLabel
	local t = Instance.new("TextLabel")
	t.Text = label
	t.FontFace = Font.new(Theme.font, weight)
	t.TextSize = size
	t.TextColor3 = color
	t.TextXAlignment = Enum.TextXAlignment.Left
	t.BackgroundTransparency = 1
	t.Size = UDim2.new(1, 0, 0, size + 8)
	t.Parent = parent
	return t
end

local function corner(parent: Instance)
	local c = Instance.new("UICorner")
	c.CornerRadius = UDim.new(0, Theme.radius)
	c.Parent = parent
end

local function padding(parent: Instance)
	local p = Instance.new("UIPadding")
	p.PaddingLeft = UDim.new(0, Theme.pad)
	p.PaddingRight = UDim.new(0, Theme.pad)
	p.PaddingTop = UDim.new(0, Theme.pad)
	p.PaddingBottom = UDim.new(0, Theme.pad)
	p.Parent = parent
end

local function feedback(button: GuiButton)
	button.AutoButtonColor = false
	button.MouseEnter:Connect(function()
		TweenService:Create(button, tweenOut, {BackgroundColor3 = Theme.surfaceHover}):Play()
	end)
	button.MouseLeave:Connect(function()
		TweenService:Create(button, tweenOut, {BackgroundColor3 = Theme.surface}):Play()
	end)
end

local gui = Instance.new("ScreenGui")
gui.Name = "Inventory"
gui.ResetOnSpawn = false
gui.IgnoreGuiInset = false

local panel = Instance.new("Frame")
panel.Name = "Panel"
panel.AnchorPoint = Vector2.new(0.5, 0.5)
panel.Position = UDim2.fromScale(0.5, 0.5)
panel.Size = UDim2.new(0.7, 0, 0.75, 0)
panel.BackgroundColor3 = Theme.ground
panel.Parent = gui
corner(panel)
padding(panel)
local ratio = Instance.new("UIAspectRatioConstraint")
ratio.AspectRatio = 1.5
ratio.Parent = panel
local sizeLimit = Instance.new("UISizeConstraint")
sizeLimit.MinSize = Vector2.new(320, 220)
sizeLimit.Parent = panel
local column = Instance.new("UIListLayout")
column.Padding = UDim.new(0, 8)
column.SortOrder = Enum.SortOrder.LayoutOrder
column.Parent = panel

text(panel, "Inventory", 28, Enum.FontWeight.Bold, Theme.ink)

local slots = Instance.new("ScrollingFrame")
slots.Name = "Slots"
slots.Size = UDim2.new(0.55, 0, 1, -48)
slots.BackgroundTransparency = 1
slots.ScrollBarThickness = 4
slots.AutomaticCanvasSize = Enum.AutomaticSize.Y
slots.CanvasSize = UDim2.new()
slots.Parent = panel
local grid = Instance.new("UIGridLayout")
grid.CellSize = UDim2.new(0, 72, 0, 72)
grid.CellPadding = UDim2.new(0, 8, 0, 8)
grid.Parent = slots

local detail = Instance.new("Frame")
detail.Name = "Detail"
detail.Size = UDim2.new(0.42, 0, 1, -48)
detail.Position = UDim2.new(0.58, 0, 0, 48)
detail.BackgroundColor3 = Theme.surface
detail.Parent = panel
corner(detail)
padding(detail)
local detailList = Instance.new("UIListLayout")
detailList.Padding = UDim.new(0, 8)
detailList.Parent = detail
local nameLabel = text(detail, "Choose an item", 20, Enum.FontWeight.Bold, Theme.ink)
local descLabel = text(detail, "", 16, Enum.FontWeight.Medium, Theme.muted)
descLabel.TextWrapped = true
descLabel.Size = UDim2.new(1, 0, 0, 64)
local equip = Instance.new("TextButton")
equip.Name = "Equip"
equip.Text = "Equip"
equip.FontFace = Font.new(Theme.font, Enum.FontWeight.Medium)
equip.TextSize = 16
equip.TextColor3 = Theme.ink
equip.BackgroundColor3 = Theme.accent
equip.Size = UDim2.new(1, 0, 0, 44)
corner(equip)
equip.Parent = detail

local function slot(name: string, description: string)
	local b = Instance.new("TextButton")
	b.Name = name
	b.Text = name
	b.FontFace = Font.new(Theme.font, Enum.FontWeight.Medium)
	b.TextSize = 14
	b.TextWrapped = true
	b.TextColor3 = Theme.ink
	b.BackgroundColor3 = Theme.surface
	b.Size = UDim2.new(0, 72, 0, 72)
	corner(b)
	feedback(b)
	b.Activated:Connect(function()
		nameLabel.Text = name
		descLabel.Text = description
	end)
	b.Parent = slots
end
slot("Pumpkin", "Sells for 40 coins")
slot("Carrot", "Feeds the rabbits")
slot("Sunflower", "Decoration")

gui.Parent = Players.LocalPlayer:WaitForChild("PlayerGui")
```
