-- STAR UI kit (client presentation only). Inserted above the generated screen by star/roblox_ui_designer.py.
-- Design tokens live in T (theme) and DATA (screen content); every size here is in reference pixels and the
-- canvas UIScale maps them onto the real screen, so layouts never depend on the device resolution.
local Players = game:GetService("Players")
local TweenService = game:GetService("TweenService")
local UserInputService = game:GetService("UserInputService")
local GuiService = game:GetService("GuiService")
local ContextActionService = game:GetService("ContextActionService")
local RunService = game:GetService("RunService")

local player = Players.LocalPlayer

local function rgb(hex: string): Color3
	return Color3.fromHex(hex)
end

local function new(className: string, props: { [string]: any }?, children: { Instance }?): any
	local object = Instance.new(className)
	local parent = nil
	for key, value in pairs(props or {}) do
		if key == "Parent" then
			parent = value
		else
			object[key] = value
		end
	end
	for _, child in ipairs(children or {}) do
		child.Parent = object
	end
	object.Parent = parent
	return object
end

local function font(role: string): Font
	local f = T.fonts[role]
	return Font.new("rbxasset://fonts/families/" .. f.family .. ".json", Enum.FontWeight[f.weight])
end

local function corner(radius: number?): UICorner
	return new("UICorner", { CornerRadius = UDim.new(0, radius or T.radius) })
end

local function stroke(color: Color3, thickness: number?, transparency: number?): UIStroke
	return new("UIStroke", {
		Color = color,
		Thickness = thickness or T.strokeWidth,
		Transparency = transparency or 0,
		ApplyStrokeMode = Enum.ApplyStrokeMode.Border,
	})
end

local function pad(all: number, horizontal: number?): UIPadding
	local h = horizontal or all
	return new("UIPadding", {
		PaddingTop = UDim.new(0, all),
		PaddingBottom = UDim.new(0, all),
		PaddingLeft = UDim.new(0, h),
		PaddingRight = UDim.new(0, h),
	})
end

local function list(direction: string, gap: number, hAlign: string?, vAlign: string?): UIListLayout
	return new("UIListLayout", {
		FillDirection = Enum.FillDirection[direction],
		Padding = UDim.new(0, gap),
		HorizontalAlignment = Enum.HorizontalAlignment[hAlign or "Left"],
		VerticalAlignment = Enum.VerticalAlignment[vAlign or "Top"],
		SortOrder = Enum.SortOrder.LayoutOrder,
	})
end

local function vgradient(top: Color3, bottom: Color3, rotation: number?): UIGradient
	return new("UIGradient", {
		Color = ColorSequence.new(top, bottom),
		Rotation = rotation or 90,
	})
end

local function shade(color: Color3, amount: number): Color3
	-- amount > 0 lightens towards white, < 0 darkens towards black
	if amount >= 0 then
		return color:Lerp(Color3.new(1, 1, 1), amount)
	end
	return color:Lerp(Color3.new(0, 0, 0), -amount)
end

local function tween(object: Instance, seconds: number, goals: { [string]: any }, style: string?, direction: string?)
	local info = TweenInfo.new(seconds, Enum.EasingStyle[style or "Quart"], Enum.EasingDirection[direction or "Out"])
	local t = TweenService:Create(object, info, goals)
	t:Play()
	return t
end

local function text(role: string, value: string, size: number, color: Color3?, props: { [string]: any }?): TextLabel
	local label = new("TextLabel", {
		BackgroundTransparency = 1,
		FontFace = font(role),
		Text = value,
		TextSize = size,
		TextColor3 = color or rgb(T.c.text),
		TextXAlignment = Enum.TextXAlignment.Left,
		TextYAlignment = Enum.TextYAlignment.Center,
		TextTruncate = Enum.TextTruncate.AtEnd,
		Size = UDim2.new(1, 0, 0, math.ceil(size * 1.3)),
	})
	for key, v in pairs(props or {}) do
		label[key] = v
	end
	if role == "display" and T.textOutline then
		new("UIStroke", {
			Color = rgb(T.c.outline),
			Thickness = math.max(1.5, size / 14),
			ApplyStrokeMode = Enum.ApplyStrokeMode.Contextual,
			Parent = label,
		})
	end
	return label
end

local function shadow(parent: GuiObject, radius: number?)
	-- Roblox has no box-shadow: a soft offset plate behind the panel reads as depth without a texture asset.
	if T.shadow == "none" then
		return
	end
	local plate = new("Frame", {
		Name = "Shadow",
		AnchorPoint = parent.AnchorPoint,
		Position = parent.Position + UDim2.fromOffset(0, T.shadow == "drop" and 6 or 0),
		Size = parent.Size + UDim2.fromOffset(T.shadow == "glow" and 10 or 0, T.shadow == "glow" and 10 or 0),
		BackgroundColor3 = T.shadow == "glow" and rgb(T.c.accent) or Color3.new(0, 0, 0),
		BackgroundTransparency = T.shadow == "glow" and 0.86 or 0.55,
		ZIndex = parent.ZIndex - 1,
		LayoutOrder = parent.LayoutOrder,
		Parent = parent.Parent,
	}, { corner((radius or T.radius) + (T.shadow == "glow" and 5 or 0)) })
	if T.shadow == "glow" then
		plate.Position = parent.Position
	end
	return plate
end

local function panel(props: { [string]: any }, level: number?): Frame
	local isInner = (level or 1) > 1
	local frame = new("Frame", {
		BackgroundColor3 = rgb(isInner and T.c.surface2 or T.c.surface),
		BackgroundTransparency = isInner and T.surface2Alpha or T.surfaceAlpha,
		BorderSizePixel = 0,
	}, { corner(isInner and math.max(0, T.radius - 4) or T.radius) })
	for key, v in pairs(props) do
		if key ~= "Parent" then
			frame[key] = v
		end
	end
	if T.panelGradient and not isInner then
		vgradient(Color3.new(1, 1, 1), rgb(T.c.gradientTo)).Parent = frame
	end
	stroke(rgb(isInner and T.c.strokeSoft or T.c.stroke), isInner and 1 or T.strokeWidth, isInner and 0.35 or T.strokeAlpha).Parent = frame
	if T.doubleStroke and not isInner then
		local inset = new("Frame", {
			Name = "Inlay",
			BackgroundTransparency = 1,
			Position = UDim2.fromOffset(5, 5),
			Size = UDim2.new(1, -10, 1, -10),
			ZIndex = frame.ZIndex,
		}, { corner(math.max(0, T.radius - 3)), stroke(rgb(T.c.stroke), 1, 0.55) })
		inset.Parent = frame
	end
	frame.Parent = props.Parent
	if not isInner and props.Parent then
		shadow(frame)
	end
	return frame
end

-- Gamepad focus ring shared by every selectable control.
local focusRing = new("Frame", {
	Name = "StarFocusRing",
	BackgroundTransparency = 1,
	Size = UDim2.new(1, 8, 1, 8),
	Position = UDim2.fromOffset(-4, -4),
}, { corner(T.radius + 4), stroke(rgb(T.c.focus), 3, 0) })

local buttons = {}

local function button(label: string, variant: string, size: UDim2, onClick: (() -> ())?, props: { [string]: any }?): TextButton
	-- variant: primary | secondary | ghost | danger. Chunky buttons get a darker lip that the face presses into.
	local face = rgb(variant == "primary" and T.c.accent or variant == "danger" and T.c.bad
		or variant == "secondary" and T.c.secondary or T.c.surface2)
	local ink = rgb(variant == "primary" and T.c.accentText or variant == "danger" and "#FFFFFF"
		or variant == "secondary" and T.c.secondaryText or T.c.text)
	local chunky = T.button == "chunky" and variant ~= "ghost"
	local lipHeight = chunky and 5 or 0
	local holder = new("Frame", {
		Name = label:gsub("%W", "") .. "Button",
		BackgroundTransparency = 1,
		Size = size,
	})
	local lip = nil
	if chunky then
		lip = new("Frame", {
			Name = "Lip",
			BackgroundColor3 = shade(face, -0.32),
			Size = UDim2.new(1, 0, 1, -lipHeight),
			Position = UDim2.fromOffset(0, lipHeight),
			Parent = holder,
		}, { corner(math.max(4, T.radius - 2)) })
	end
	local btn = new("TextButton", {
		Name = "Face",
		AutoButtonColor = false,
		BackgroundColor3 = face,
		BackgroundTransparency = variant == "ghost" and 1 or (T.button == "glass" and 0.78 or 0),
		Size = UDim2.new(1, 0, 1, -lipHeight),
		FontFace = font("label"),
		Text = label,
		TextSize = T.type.label,
		TextColor3 = (T.button == "glass" and variant == "primary") and rgb(T.c.accent) or ink,
		TextTruncate = Enum.TextTruncate.AtEnd,
		Selectable = true,
		SelectionImageObject = focusRing,
		Parent = holder,
	}, { corner(math.max(4, T.radius - 2)) })
	if T.button == "glass" or variant == "ghost" or T.button == "outline" then
		stroke(variant == "ghost" and rgb(T.c.strokeSoft) or face, 1.5, variant == "ghost" and 0.2 or 0).Parent = btn
	end
	if T.button == "chunky" and variant ~= "ghost" then
		vgradient(Color3.new(1, 1, 1), Color3.fromRGB(214, 214, 214)).Parent = btn
		if T.textOutline then
			new("UIStroke", {
				Color = shade(face, -0.55),
				Thickness = 1.6,
				ApplyStrokeMode = Enum.ApplyStrokeMode.Contextual,
				Parent = btn,
			})
		end
	end
	local scale = new("UIScale", { Parent = holder })
	local hovered = false
	local function settle()
		tween(scale, 0.14, { Scale = hovered and 1.04 or 1 }, "Quad")
		tween(btn, 0.14, { BackgroundColor3 = hovered and shade(face, 0.1) or face, Position = UDim2.fromOffset(0, 0) }, "Quad")
	end
	btn.MouseEnter:Connect(function()
		hovered = true
		settle()
	end)
	btn.MouseLeave:Connect(function()
		hovered = false
		settle()
	end)
	btn.SelectionGained:Connect(function()
		hovered = true
		settle()
	end)
	btn.SelectionLost:Connect(function()
		hovered = false
		settle()
	end)
	btn.MouseButton1Down:Connect(function()
		tween(scale, 0.08, { Scale = 0.97 }, "Quad")
		tween(btn, 0.08, { Position = UDim2.fromOffset(0, lipHeight) }, "Quad")
	end)
	btn.MouseButton1Up:Connect(settle)
	btn.Activated:Connect(function()
		if onClick then
			onClick()
		end
	end)
	for key, v in pairs(props or {}) do
		holder[key] = v
	end
	table.insert(buttons, btn)
	return holder
end

local function coin(size: number, color: string?): Frame
	local c = rgb(color or T.c.currency)
	return new("Frame", {
		Name = "Coin",
		BackgroundColor3 = c,
		Size = UDim2.fromOffset(size, size),
	}, {
		corner(size),
		stroke(shade(c, -0.45), math.max(1, size / 10), 0),
		new("Frame", {
			BackgroundColor3 = shade(c, 0.35),
			BackgroundTransparency = 0.25,
			AnchorPoint = Vector2.new(0.5, 0.5),
			Position = UDim2.fromScale(0.5, 0.5),
			Size = UDim2.fromScale(0.5, 0.5),
		}, { corner(size) }),
	})
end

local function formatNumber(n: number): string
	local s = tostring(math.floor(n))
	local formatted = s:reverse():gsub("(%d%d%d)", "%1,"):reverse()
	return (formatted:gsub("^,", ""))
end

local function pill(amount: number, color: string?, width: number?): Frame
	local p = new("Frame", {
		Name = "CurrencyPill",
		BackgroundColor3 = rgb(T.c.surface2),
		BackgroundTransparency = T.surface2Alpha,
		Size = UDim2.fromOffset(width or 150, 40),
	}, { corner(20), stroke(rgb(T.c.strokeSoft), 1, 0.3), pad(4, 6) })
	local c = coin(30, color)
	c.Position = UDim2.fromOffset(0, 1)
	c.Parent = p
	text("numeric", formatNumber(amount), T.type.h3, rgb(T.c.text), {
		Position = UDim2.fromOffset(38, 0),
		Size = UDim2.new(1, -38, 1, 0),
		TextXAlignment = Enum.TextXAlignment.Left,
		Parent = p,
	})
	return p
end

local function bar(fraction: number, color: string, height: number, width: UDim?): Frame
	local track = new("Frame", {
		Name = "Bar",
		BackgroundColor3 = rgb(T.c.track),
		BackgroundTransparency = 0.1,
		Size = UDim2.new(width or UDim.new(1, 0), UDim.new(0, height)),
	}, { corner(height) })
	local fill = new("Frame", {
		Name = "Fill",
		BackgroundColor3 = rgb(color),
		Size = UDim2.fromScale(0, 1),
		Parent = track,
	}, { corner(height), vgradient(Color3.new(1, 1, 1), Color3.fromRGB(200, 200, 200)) })
	tween(fill, 0.7, { Size = UDim2.fromScale(math.clamp(fraction, 0, 1), 1) }, "Quart")
	return track
end

local function rarityColor(rarity: string?): Color3
	return rgb(T.rarity[rarity or "common"] or T.rarity.common)
end

local function badge(label: string, color: Color3, props: { [string]: any }?): Frame
	local b = new("Frame", {
		Name = "Badge",
		BackgroundColor3 = color,
		AutomaticSize = Enum.AutomaticSize.X,
		Size = UDim2.fromOffset(0, 22),
	}, { corner(6), pad(0, 8) })
	text("label", string.upper(label), T.type.caption, (color.R * 0.299 + color.G * 0.587 + color.B * 0.114) > 0.6
		and Color3.fromRGB(20, 20, 24) or Color3.new(1, 1, 1), {
		AutomaticSize = Enum.AutomaticSize.X,
		Size = UDim2.fromScale(0, 1),
		TextTruncate = Enum.TextTruncate.None,
		Parent = b,
	})
	for key, v in pairs(props or {}) do
		b[key] = v
	end
	return b
end

-- Item models: a few parts in a ViewportFrame read as a real game item (no image assets needed).
local MODELS = {}
local function part(model: Model, shape: string, size: Vector3, cf: CFrame, color: Color3, material: string?)
	local p = new("Part", {
		Shape = Enum.PartType[shape],
		Size = size,
		CFrame = cf,
		Color = color,
		Material = Enum.Material[material or "SmoothPlastic"],
		Anchored = true,
		CanCollide = false,
		CastShadow = false,
		Parent = model,
	})
	return p
end
local GOLD, STEEL, WOOD = Color3.fromRGB(240, 188, 70), Color3.fromRGB(205, 214, 226), Color3.fromRGB(120, 78, 44)
MODELS.sword = function(m, tint)
	part(m, "Block", Vector3.new(0.34, 3.0, 0.1), CFrame.new(0, 1.0, 0), STEEL, "SmoothPlastic")
	part(m, "Block", Vector3.new(1.3, 0.22, 0.3), CFrame.new(0, -0.55, 0), tint)
	part(m, "Block", Vector3.new(0.24, 0.9, 0.24), CFrame.new(0, -1.1, 0), WOOD, "Wood")
	part(m, "Ball", Vector3.new(0.38, 0.38, 0.38), CFrame.new(0, -1.62, 0), tint)
	return CFrame.Angles(0, 0, math.rad(-40))
end
MODELS.shield = function(m, tint)
	part(m, "Cylinder", Vector3.new(0.25, 2.6, 2.6), CFrame.Angles(0, math.rad(90), 0), shade(tint, -0.35), "SmoothPlastic")
	part(m, "Cylinder", Vector3.new(0.3, 2.2, 2.2), CFrame.new(0, 0, -0.04) * CFrame.Angles(0, math.rad(90), 0), tint)
	part(m, "Ball", Vector3.new(0.7, 0.7, 0.7), CFrame.new(0, 0, -0.18), STEEL, "SmoothPlastic")
	return CFrame.Angles(math.rad(-10), math.rad(25), 0)
end
MODELS.potion = function(m, tint)
	part(m, "Ball", Vector3.new(1.8, 1.8, 1.8), CFrame.new(0, -0.3, 0), tint, "Glass")
	part(m, "Cylinder", Vector3.new(0.8, 0.55, 0.55), CFrame.new(0, 0.85, 0) * CFrame.Angles(0, 0, math.rad(90)), shade(tint, 0.4), "Glass")
	part(m, "Cylinder", Vector3.new(0.35, 0.62, 0.62), CFrame.new(0, 1.35, 0) * CFrame.Angles(0, 0, math.rad(90)), WOOD, "Wood")
	return CFrame.Angles(0, 0, math.rad(12))
end
MODELS.gem = function(m, tint)
	part(m, "Block", Vector3.new(1.4, 1.4, 1.4), CFrame.Angles(math.rad(45), math.rad(35), math.rad(45)), tint, "Glass")
	part(m, "Block", Vector3.new(0.9, 0.9, 0.9), CFrame.Angles(math.rad(45), math.rad(35), math.rad(45)), shade(tint, 0.45), "Neon")
	return CFrame.new()
end
MODELS.coin = function(m, tint)
	part(m, "Cylinder", Vector3.new(0.3, 2.2, 2.2), CFrame.Angles(0, math.rad(70), 0), GOLD, "SmoothPlastic")
	part(m, "Cylinder", Vector3.new(0.34, 1.5, 1.5), CFrame.Angles(0, math.rad(70), 0), shade(GOLD, 0.25), "SmoothPlastic")
	return CFrame.new()
end
MODELS.chest = function(m, tint)
	part(m, "Block", Vector3.new(2.2, 1.2, 1.4), CFrame.new(0, -0.3, 0), WOOD, "Wood")
	part(m, "Cylinder", Vector3.new(2.2, 1.4, 1.4), CFrame.new(0, 0.3, 0), shade(WOOD, 0.1), "Wood")
	part(m, "Block", Vector3.new(0.3, 1.9, 1.5), CFrame.new(0, 0, 0), tint, "SmoothPlastic")
	part(m, "Block", Vector3.new(0.4, 0.45, 0.2), CFrame.new(0, 0.05, -0.78), GOLD, "SmoothPlastic")
	return CFrame.Angles(math.rad(12), math.rad(-25), 0)
end
MODELS.bow = function(m, tint)
	part(m, "Block", Vector3.new(0.18, 1.6, 0.18), CFrame.new(-0.25, 0.7, 0) * CFrame.Angles(0, 0, math.rad(-18)), WOOD, "Wood")
	part(m, "Block", Vector3.new(0.18, 1.6, 0.18), CFrame.new(-0.25, -0.7, 0) * CFrame.Angles(0, 0, math.rad(18)), WOOD, "Wood")
	part(m, "Block", Vector3.new(0.04, 2.9, 0.04), CFrame.new(0.05, 0, 0), Color3.fromRGB(240, 240, 240))
	part(m, "Block", Vector3.new(0.26, 0.4, 0.26), CFrame.new(-0.42, 0, 0), tint)
	return CFrame.Angles(0, 0, math.rad(-35))
end
MODELS.staff = function(m, tint)
	part(m, "Cylinder", Vector3.new(3.4, 0.22, 0.22), CFrame.new(0, -0.3, 0) * CFrame.Angles(0, 0, math.rad(90)), WOOD, "Wood")
	part(m, "Ball", Vector3.new(0.8, 0.8, 0.8), CFrame.new(0, 1.65, 0), tint, "Neon")
	part(m, "Cylinder", Vector3.new(0.25, 0.7, 0.7), CFrame.new(0, 1.2, 0) * CFrame.Angles(0, 0, math.rad(90)), GOLD, "SmoothPlastic")
	return CFrame.Angles(0, 0, math.rad(-30))
end
MODELS.helmet = function(m, tint)
	part(m, "Ball", Vector3.new(2, 2, 2), CFrame.new(0, 0.1, 0), tint, "SmoothPlastic")
	part(m, "Block", Vector3.new(1.6, 0.35, 0.4), CFrame.new(0, -0.1, -0.8), Color3.fromRGB(25, 25, 30))
	part(m, "Block", Vector3.new(0.2, 0.8, 1.6), CFrame.new(0, 1.0, 0.1), shade(tint, 0.3))
	return CFrame.Angles(0, math.rad(-25), 0)
end
MODELS.pet = function(m, tint)
	part(m, "Ball", Vector3.new(2, 2, 2), CFrame.new(), tint)
	part(m, "Ball", Vector3.new(0.6, 0.9, 0.5), CFrame.new(-0.6, 1.0, 0), shade(tint, -0.15))
	part(m, "Ball", Vector3.new(0.6, 0.9, 0.5), CFrame.new(0.6, 1.0, 0), shade(tint, -0.15))
	part(m, "Ball", Vector3.new(0.32, 0.32, 0.32), CFrame.new(-0.38, 0.15, -0.88), Color3.fromRGB(20, 20, 24))
	part(m, "Ball", Vector3.new(0.32, 0.32, 0.32), CFrame.new(0.38, 0.15, -0.88), Color3.fromRGB(20, 20, 24))
	return CFrame.Angles(0, math.rad(-20), 0)
end
MODELS.crown = function(m, tint)
	part(m, "Cylinder", Vector3.new(0.9, 2.0, 2.0), CFrame.Angles(0, 0, math.rad(90)), GOLD, "SmoothPlastic")
	for i = 0, 4 do
		local a = math.rad(i * 72)
		part(m, "Block", Vector3.new(0.35, 0.7, 0.2), CFrame.new(math.cos(a) * 0.9, 0.7, math.sin(a) * 0.9), GOLD, "SmoothPlastic")
	end
	part(m, "Ball", Vector3.new(0.45, 0.45, 0.45), CFrame.new(0, 0.05, -1.0), tint, "Neon")
	return CFrame.Angles(math.rad(15), 0, 0)
end
MODELS.key = function(m, tint)
	part(m, "Cylinder", Vector3.new(0.25, 1.2, 1.2), CFrame.new(0, 1.0, 0) * CFrame.Angles(0, math.rad(90), 0), GOLD, "SmoothPlastic")
	part(m, "Block", Vector3.new(0.25, 2.0, 0.25), CFrame.new(0, -0.3, 0), GOLD, "SmoothPlastic")
	part(m, "Block", Vector3.new(0.55, 0.22, 0.25), CFrame.new(0.3, -1.1, 0), GOLD, "SmoothPlastic")
	part(m, "Block", Vector3.new(0.4, 0.22, 0.25), CFrame.new(0.25, -0.7, 0), GOLD, "SmoothPlastic")
	return CFrame.Angles(0, 0, math.rad(-35))
end
MODELS.scroll = function(m, tint)
	part(m, "Block", Vector3.new(1.8, 2.0, 0.08), CFrame.new(), Color3.fromRGB(236, 218, 176))
	part(m, "Cylinder", Vector3.new(2.2, 0.32, 0.32), CFrame.new(0, 1.05, 0), WOOD, "Wood")
	part(m, "Cylinder", Vector3.new(2.2, 0.32, 0.32), CFrame.new(0, -1.05, 0), WOOD, "Wood")
	part(m, "Block", Vector3.new(0.4, 0.4, 0.1), CFrame.new(0, -0.3, -0.06), tint)
	return CFrame.Angles(0, math.rad(-15), math.rad(-10))
end
MODELS.bomb = function(m, tint)
	part(m, "Ball", Vector3.new(2, 2, 2), CFrame.new(), Color3.fromRGB(40, 40, 48), "SmoothPlastic")
	part(m, "Cylinder", Vector3.new(0.4, 0.6, 0.6), CFrame.new(0, 1.0, 0) * CFrame.Angles(0, 0, math.rad(90)), Color3.fromRGB(90, 90, 100), "SmoothPlastic")
	part(m, "Ball", Vector3.new(0.4, 0.4, 0.4), CFrame.new(0.15, 1.4, 0), tint, "Neon")
	return CFrame.Angles(0, 0, math.rad(-15))
end
MODELS.food = function(m, tint)
	part(m, "Ball", Vector3.new(2, 1.9, 2), CFrame.new(), Color3.fromRGB(214, 48, 49))
	part(m, "Block", Vector3.new(0.14, 0.6, 0.14), CFrame.new(0, 1.1, 0) * CFrame.Angles(0, 0, math.rad(12)), WOOD, "Wood")
	part(m, "Block", Vector3.new(0.6, 0.08, 0.32), CFrame.new(0.32, 1.12, 0) * CFrame.Angles(0, 0, math.rad(-20)), Color3.fromRGB(80, 170, 80))
	return CFrame.new()
end
MODELS.heart = function(m, tint)
	local red = Color3.fromRGB(235, 64, 90)
	part(m, "Ball", Vector3.new(1.3, 1.3, 1.0), CFrame.new(-0.45, 0.3, 0), red)
	part(m, "Ball", Vector3.new(1.3, 1.3, 1.0), CFrame.new(0.45, 0.3, 0), red)
	part(m, "Block", Vector3.new(1.25, 1.25, 0.95), CFrame.new(0, -0.25, 0) * CFrame.Angles(0, 0, math.rad(45)), red)
	return CFrame.new()
end
MODELS.boots = function(m, tint)
	part(m, "Block", Vector3.new(0.8, 1.4, 0.8), CFrame.new(-0.55, 0.2, 0), shade(tint, -0.2))
	part(m, "Block", Vector3.new(0.8, 0.5, 1.3), CFrame.new(-0.55, -0.45, -0.25), shade(tint, -0.2))
	part(m, "Block", Vector3.new(0.8, 1.4, 0.8), CFrame.new(0.55, 0.2, 0.2), tint)
	part(m, "Block", Vector3.new(0.8, 0.5, 1.3), CFrame.new(0.55, -0.45, -0.05), tint)
	return CFrame.Angles(math.rad(18), math.rad(-35), 0)
end
MODELS.lightning = function(m, tint)
	part(m, "Block", Vector3.new(0.35, 1.4, 0.2), CFrame.new(0.2, 0.6, 0) * CFrame.Angles(0, 0, math.rad(-25)), tint, "Neon")
	part(m, "Block", Vector3.new(0.9, 0.3, 0.2), CFrame.new(0, 0, 0), tint, "Neon")
	part(m, "Block", Vector3.new(0.35, 1.4, 0.2), CFrame.new(-0.2, -0.6, 0) * CFrame.Angles(0, 0, math.rad(-25)), tint, "Neon")
	return CFrame.new()
end

local function iconTile(kind: string?, rarity: string?, size: number, props: { [string]: any }?): Frame
	local tint = rarityColor(rarity)
	local tile = new("Frame", {
		Name = "Icon",
		BackgroundColor3 = shade(tint, -0.55),
		Size = UDim2.fromOffset(size, size),
	}, { corner(math.max(4, T.radius - 2)) })
	new("UIGradient", {
		Color = ColorSequence.new(shade(tint, -0.15), shade(tint, -0.7)),
		Rotation = 90,
		Parent = tile,
	})
	local vp = new("ViewportFrame", {
		BackgroundTransparency = 1,
		Size = UDim2.fromScale(1, 1),
		Ambient = Color3.fromRGB(150, 150, 160),
		LightColor = Color3.fromRGB(255, 246, 230),
		LightDirection = Vector3.new(-1, -1.4, -0.8),
		Parent = tile,
	})
	local model = new("Model", { Parent = vp })
	local build = MODELS[kind or "gem"] or MODELS.gem
	local pose = build(model, tint)
	-- Pose about the model's centre, then fit the camera to the world-axis bounds of every part corner.
	local function bounds()
		local lo, hi = Vector3.new(math.huge, math.huge, math.huge), Vector3.new(-math.huge, -math.huge, -math.huge)
		for _, p in ipairs(model:GetChildren()) do
			local h = p.Size / 2
			for _, sx in ipairs({ -1, 1 }) do
				for _, sy in ipairs({ -1, 1 }) do
					for _, sz in ipairs({ -1, 1 }) do
						local c = p.CFrame * Vector3.new(h.X * sx, h.Y * sy, h.Z * sz)
						lo, hi = lo:Min(c), hi:Max(c)
					end
				end
			end
		end
		return lo, hi
	end
	local lo, hi = bounds()
	local centre = (lo + hi) / 2
	for _, p in ipairs(model:GetChildren()) do
		p.CFrame = pose * (CFrame.new(-centre) * p.CFrame)
	end
	lo, hi = bounds()
	local extents = hi - lo
	local camera = new("Camera", { FieldOfView = 30, Parent = vp })
	local distance = math.max(extents.X, extents.Y) / (2 * math.tan(math.rad(15))) * 1.18 + extents.Z / 2
	camera.CFrame = CFrame.lookAt((lo + hi) / 2 + Vector3.new(0, 0, -distance), (lo + hi) / 2)
	vp.CurrentCamera = camera
	for key, v in pairs(props or {}) do
		tile[key] = v
	end
	return tile
end

-- Responsive root: one canvas of reference size, scaled to fit; layouts switch to "compact" on phones.
local screenGui = new("ScreenGui", {
	Name = "StarUI_" .. DATA.id,
	ResetOnSpawn = false,
	IgnoreGuiInset = false,
	ScreenInsets = Enum.ScreenInsets.CoreUISafeInsets,
	ZIndexBehavior = Enum.ZIndexBehavior.Sibling,
	Parent = player:WaitForChild("PlayerGui"),
})
local root = new("Frame", {
	Name = "Root",
	BackgroundTransparency = 1,
	Size = UDim2.fromScale(1, 1),
	Parent = screenGui,
})

local function modeFor(size: Vector2): string
	return (size.Y < 560 or size.X < 900) and "compact" or "wide"
end

local function makeCanvas(parent: Instance, refW: number, refH: number, anchor: Vector2?, position: UDim2?): (Frame, UIScale)
	local canvas = new("Frame", {
		Name = "Canvas",
		BackgroundTransparency = 1,
		AnchorPoint = anchor or Vector2.new(0.5, 0.5),
		Position = position or UDim2.fromScale(0.5, 0.5),
		Size = UDim2.fromOffset(refW, refH),
		Parent = parent,
	})
	local uiScale = new("UIScale", { Parent = canvas })
	local function fit()
		local s = root.AbsoluteSize
		if s.X < 1 or s.Y < 1 then
			return
		end
		uiScale.Scale = math.clamp(math.min((s.X - 16) / refW, (s.Y - 12) / refH), 0.5, 1.6)
	end
	fit()
	root:GetPropertyChangedSignal("AbsoluteSize"):Connect(fit)
	return canvas, uiScale
end

local function openAnimation(canvas: Frame, uiScale: UIScale)
	local target = uiScale.Scale
	uiScale.Scale = target * 0.94
	local finalPosition = canvas.Position
	canvas.Position = finalPosition + UDim2.fromOffset(0, 18)
	tween(uiScale, 0.32, { Scale = target }, "Back")
	tween(canvas, 0.32, { Position = finalPosition }, "Quart")
end

local function close()
	tween(root, 0.18, { Position = UDim2.fromOffset(0, 24) }, "Quad", "In")
	task.delay(0.18, function()
		screenGui.Enabled = false
		root.Position = UDim2.new()
	end)
end

local function focusFirst(target: GuiObject?)
	if target and (UserInputService.GamepadEnabled or GuiService:IsTenFootInterface()) then
		GuiService.SelectedObject = target
	end
end

ContextActionService:BindAction("StarUIClose_" .. DATA.id, function(_, state)
	if state == Enum.UserInputState.Begin and screenGui.Enabled and DATA.closable then
		close()
	end
	return Enum.ContextActionResult.Pass
end, false, Enum.KeyCode.ButtonB)

local function header(parent: Instance, title: string, subtitle: string?, height: number, withClose: boolean)
	local bar = new("Frame", { Name = "Header", BackgroundTransparency = 1, Size = UDim2.new(1, 0, 0, height), Parent = parent })
	text("display", title, T.type.h1, rgb(T.c.text), {
		Position = UDim2.fromOffset(0, subtitle and 2 or 0),
		Size = UDim2.new(0.6, 0, 0, subtitle and math.floor(height * 0.62) or height),
		Parent = bar,
	})
	if subtitle then
		text("body", subtitle, T.type.caption, rgb(T.c.textDim), {
			Position = UDim2.fromOffset(0, math.floor(height * 0.62)),
			Size = UDim2.new(0.6, 0, 0, math.floor(height * 0.34)),
			Parent = bar,
		})
	end
	if withClose then
		local x = button("X", "ghost", UDim2.fromOffset(40, 40), close, {
			AnchorPoint = Vector2.new(1, 0.5),
			Position = UDim2.new(1, 0, 0.5, 0),
			Parent = bar,
		})
		x.Name = "CloseButton"
	end
	return bar
end

local function tabs(parent: Instance, names: { string }, height: number, width: number?)
	local row = new("Frame", { Name = "Tabs", BackgroundTransparency = 1, Size = UDim2.new(1, 0, 0, height), Parent = parent })
	list("Horizontal", 6).Parent = row
	local indicator = new("Frame", {
		Name = "Indicator",
		BackgroundColor3 = rgb(T.c.accent),
		Size = UDim2.new(0, width or 120, 0, 3),
		Position = UDim2.new(0, 0, 1, -3),
		ZIndex = 3,
		Parent = parent,
	}, { corner(2) })
	indicator.Position = UDim2.new(0, 0, 0, height - 3)
	local tabButtons = {}
	for i, name in ipairs(names) do
		local b = new("TextButton", {
			Name = "Tab" .. i,
			AutoButtonColor = false,
			BackgroundTransparency = 1,
			Size = UDim2.fromOffset(width or 120, height),
			FontFace = font("label"),
			Text = name,
			TextSize = T.type.label,
			TextColor3 = rgb(i == 1 and T.c.text or T.c.textDim),
			TextTruncate = Enum.TextTruncate.AtEnd,
			LayoutOrder = i,
			Selectable = true,
			SelectionImageObject = focusRing,
			Parent = row,
		})
		table.insert(tabButtons, b)
		b.Activated:Connect(function()
			for j, other in ipairs(tabButtons) do
				tween(other, 0.15, { TextColor3 = rgb(j == i and T.c.text or T.c.textDim) }, "Quad")
			end
			tween(indicator, 0.22, { Position = UDim2.new(0, (i - 1) * ((width or 120) + 6), 0, height - 3) }, "Quart")
		end)
	end
	return row, tabButtons
end

local function priceButton(item: { [string]: any }, size: UDim2): Frame
	if item.owned then
		local holder = new("Frame", { Name = "Owned", BackgroundColor3 = rgb(T.c.surface2), BackgroundTransparency = 0.2, Size = size }, { corner(math.max(4, T.radius - 2)) })
		text("label", "OWNED", T.type.caption, rgb(T.c.good), { Size = UDim2.fromScale(1, 1), TextXAlignment = Enum.TextXAlignment.Center, Parent = holder })
		return holder
	end
	local b = button(formatNumber(item.price or 0), "primary", size)
	local face = b:FindFirstChild("Face")
	if face then
		face.TextXAlignment = Enum.TextXAlignment.Center
		local c = coin(16)
		c.AnchorPoint = Vector2.new(0, 0.5)
		c.Position = UDim2.new(0, 10, 0.5, 0)
		c.Parent = face
	end
	return b
end
