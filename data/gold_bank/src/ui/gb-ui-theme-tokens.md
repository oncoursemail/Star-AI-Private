---
id: gb-ui-theme-tokens
category: ui-style
topics: theme, design tokens, UICorner, UIPadding, consistent styling
source: original
---
# Request
Every menu in my game was styled by hand and now there are six slightly different greys and four corner radii. I want one theme module that all UI code uses. How should it look?

# Answer
Put raw values (colours, spacing, radius, text sizes) in one frozen token table, and expose a few `style` functions that apply them to an instance by role. UI code then asks for "a panel" or "a primary button" instead of picking numbers, and the helpers are safe to call twice.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Theme
local Theme = {}

Theme.tokens = table.freeze({
	color = table.freeze({
		surface = Color3.fromRGB(28, 30, 35),
		surfaceRaised = Color3.fromRGB(38, 41, 48),
		text = Color3.fromRGB(236, 237, 240),
		textMuted = Color3.fromRGB(160, 164, 172),
		accent = Color3.fromRGB(46, 120, 220),
		danger = Color3.fromRGB(205, 64, 64),
	}),
	space = table.freeze({ xs = 4, sm = 8, md = 12, lg = 20 }),
	radius = table.freeze({ sm = 4, md = 8 }),
	textSize = table.freeze({ body = 16, label = 14, title = 22 }),
})

local tokens = Theme.tokens

local function corner(gui: GuiObject, radius: number)
	local existing = gui:FindFirstChildOfClass("UICorner")
	local c = existing or Instance.new("UICorner")
	c.CornerRadius = UDim.new(0, radius)
	c.Parent = gui
end

local function padding(gui: GuiObject, amount: number)
	local existing = gui:FindFirstChildOfClass("UIPadding")
	local p = existing or Instance.new("UIPadding")
	local u = UDim.new(0, amount)
	p.PaddingTop, p.PaddingBottom, p.PaddingLeft, p.PaddingRight = u, u, u, u
	p.Parent = gui
end

function Theme.panel(frame: Frame)
	frame.BackgroundColor3 = tokens.color.surface
	frame.BackgroundTransparency = 0
	frame.BorderSizePixel = 0
	corner(frame, tokens.radius.md)
	padding(frame, tokens.space.lg)
end

function Theme.button(button: TextButton, variant: ("primary" | "secondary" | "danger")?)
	local kind = variant or "secondary"
	button.BackgroundColor3 = if kind == "primary" then tokens.color.accent
		elseif kind == "danger" then tokens.color.danger
		else tokens.color.surfaceRaised
	button.TextColor3 = tokens.color.text
	button.TextSize = tokens.textSize.body
	button.BorderSizePixel = 0
	corner(button, tokens.radius.sm)
	padding(button, tokens.space.sm)
end

function Theme.label(label: TextLabel, muted: boolean?)
	label.BackgroundTransparency = 1
	label.TextColor3 = if muted then tokens.color.textMuted else tokens.color.text
	label.TextSize = tokens.textSize.label
end

return Theme
```

- `table.freeze` makes an accidental `Theme.tokens.color.accent = ...` from one menu an error instead of a silent global restyle.
- Reusing an existing UICorner or UIPadding means re-styling a cloned template never stacks duplicates.
- Run every text/background token pair through a contrast check once; muted text on the raised surface is the pair most likely to fail.

# Test
```lua
local frame = Instance.new("Frame")
item.panel(frame)
item.panel(frame)
local corners = 0
for _, c in frame:GetChildren() do
	if c:IsA("UICorner") then
		corners += 1
	end
end
check("panel uses the surface token", frame.BackgroundColor3 == item.tokens.color.surface)
check("styling twice does not duplicate corners", corners == 1 and frame.UICorner.CornerRadius.Offset == 8)
local b = Instance.new("TextButton")
item.button(b, "danger")
check("danger variant", b.BackgroundColor3 == item.tokens.color.danger and b.TextSize == 16)
item.button(b)
check("default variant is secondary", b.BackgroundColor3 == item.tokens.color.surfaceRaised)
check("tokens are frozen", not pcall(function()
	item.tokens.color.accent = Color3.new(1, 0, 1)
end))
```
