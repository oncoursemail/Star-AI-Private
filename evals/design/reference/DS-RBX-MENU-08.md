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
gui.Name = "MainMenu"
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

text(panel, "Granite Falls Parkour", 40, Enum.FontWeight.Bold, Theme.ink)
text(panel, "Round-based, 16 players, no pay to win", 16, Enum.FontWeight.Medium, Theme.muted)

local function menuButton(label: string, order: number)
	local b = Instance.new("TextButton")
	b.Name = label
	b.Text = label
	b.LayoutOrder = order
	b.FontFace = Font.new(Theme.font, Enum.FontWeight.Medium)
	b.TextSize = 20
	b.TextColor3 = Theme.ink
	b.BackgroundColor3 = Theme.surface
	b.Size = UDim2.new(0.5, 0, 0, 48)
	corner(b)
	feedback(b)
	b.Parent = panel
end
menuButton("Run", 10)
menuButton("Trails", 11)
menuButton("Settings", 12)

gui.Parent = Players.LocalPlayer:WaitForChild("PlayerGui")
```
