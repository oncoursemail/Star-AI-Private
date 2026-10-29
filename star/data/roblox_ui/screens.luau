-- STAR UI screens: one builder per archetype. Each builds inside `root` for the current mode and returns the
-- control that gamepads focus first.
local SCREENS = {}

local function itemsOr(default: { any }): { any }
	return (DATA.items and #DATA.items > 0) and DATA.items or default
end

local function itemCard(item, w: number, h: number, order: number, onSelect: ((any) -> ())?): Frame
	local card = panel({ Name = "Card" .. order, Size = UDim2.fromOffset(w, h), LayoutOrder = order }, 2)
	local tint = rarityColor(item.rarity)
	new("Frame", {
		Name = "RarityStrip",
		BackgroundColor3 = tint,
		Size = UDim2.new(1, -2 * math.max(4, T.radius - 4), 0, 3),
		Position = UDim2.fromOffset(math.max(4, T.radius - 4), 0),
		BorderSizePixel = 0,
		Parent = card,
	})
	local iconSize = math.min(w - 24, h - 94)
	iconTile(item.kind, item.rarity, iconSize, {
		AnchorPoint = Vector2.new(0.5, 0),
		Position = UDim2.new(0.5, 0, 0, 12),
		Parent = card,
	})
	text("label", item.name or "Item", T.type.body, rgb(T.c.text), {
		Position = UDim2.fromOffset(10, iconSize + 16),
		Size = UDim2.new(1, -20, 0, 20),
		TextXAlignment = Enum.TextXAlignment.Center,
		Parent = card,
	})
	priceButton(item, UDim2.new(1, -20, 0, 42)).Parent = card
	for _, child in ipairs(card:GetChildren()) do
		if child.Name == "Owned" or child.Name:match("Button$") then
			child.AnchorPoint = Vector2.new(0.5, 1)
			child.Position = UDim2.new(0.5, 0, 1, -8)
		end
	end
	local hit = new("TextButton", {
		Name = "Select",
		BackgroundTransparency = 1,
		Text = "",
		Size = UDim2.new(1, 0, 1, -56),
		ZIndex = 5,
		Selectable = false,
		Parent = card,
	})
	hit.Activated:Connect(function()
		if onSelect then
			onSelect(item)
		end
	end)
	local scale = new("UIScale", { Parent = card })
	hit.MouseEnter:Connect(function()
		tween(scale, 0.14, { Scale = 1.03 }, "Quad")
	end)
	hit.MouseLeave:Connect(function()
		tween(scale, 0.14, { Scale = 1 }, "Quad")
	end)
	return card
end

local function scrollGrid(parent: Instance, size: UDim2, position: UDim2, cell: Vector2, gap: number, columns: number?): ScrollingFrame
	local scroller = new("ScrollingFrame", {
		Name = "Grid",
		BackgroundTransparency = 1,
		BorderSizePixel = 0,
		Size = size,
		Position = position,
		ScrollBarThickness = 4,
		ScrollBarImageColor3 = rgb(T.c.textDim),
		AutomaticCanvasSize = Enum.AutomaticSize.Y,
		CanvasSize = UDim2.new(),
		ScrollingDirection = Enum.ScrollingDirection.Y,
		Selectable = false,
		Parent = parent,
	})
	new("UIGridLayout", {
		CellSize = UDim2.fromOffset(cell.X, cell.Y),
		CellPadding = UDim2.fromOffset(gap, gap),
		SortOrder = Enum.SortOrder.LayoutOrder,
		FillDirectionMaxCells = columns or 0,
		Parent = scroller,
	})
	new("UIPadding", { PaddingTop = UDim.new(0, 6), PaddingLeft = UDim.new(0, 4), PaddingRight = UDim.new(0, 8), Parent = scroller })
	return scroller
end

local function detailPane(parent: Instance, size: UDim2, position: UDim2, actionLabel: string): (Frame, (any) -> ())
	local pane = panel({ Name = "Detail", Size = size, Position = position, Parent = parent }, 2)
	pad(16).Parent = pane
	local holder = new("Frame", { Name = "Content", BackgroundTransparency = 1, Size = UDim2.fromScale(1, 1), Parent = pane })
	local function show(item)
		holder:ClearAllChildren()
		list("Vertical", 10, "Center").Parent = holder
		iconTile(item.kind, item.rarity, 150, { LayoutOrder = 1, Parent = holder })
		text("display", item.name or "Item", T.type.h2, rgb(T.c.text), { LayoutOrder = 2, TextXAlignment = Enum.TextXAlignment.Center, Parent = holder })
		badge(item.rarity or "common", rarityColor(item.rarity), { LayoutOrder = 3, Parent = holder })
		text("body", item.stat or item.description or "", T.type.body, rgb(T.c.textDim), {
			LayoutOrder = 4,
			TextXAlignment = Enum.TextXAlignment.Center,
			TextWrapped = true,
			TextTruncate = Enum.TextTruncate.None,
			Size = UDim2.new(1, 0, 0, 44),
			Parent = holder,
		})
		local action = nil
		if actionLabel ~= "Buy" then
			action = button(item.equipped and "Unequip" or actionLabel, item.equipped and "secondary" or "primary", UDim2.new(1, 0, 0, 48))
		elseif item.owned then
			action = button("Equip", "secondary", UDim2.new(1, 0, 0, 48))
		else
			action = priceButton(item, UDim2.new(1, 0, 0, 48))
		end
		action.LayoutOrder = 5
		action.Parent = holder
	end
	return pane, show
end

SCREENS.shop = function(mode: string)
	local items = itemsOr({ { name = "Item", kind = "gem", rarity = "common", price = 100 } })
	local compact = mode == "compact"
	local w, h = compact and 800 or 1100, compact and 360 or 620
	local canvas, uiScale = makeCanvas(root, w, h)
	local frame = panel({ Name = "ShopPanel", Size = UDim2.fromScale(1, 1), Parent = canvas })
	pad(compact and 12 or 20).Parent = frame
	local top = header(frame, DATA.title, not compact and DATA.subtitle or nil, compact and 40 or 56, true)
	if DATA.currency then
		local p = pill(DATA.currency.amount or 0, nil, compact and 130 or 160)
		p.AnchorPoint = Vector2.new(1, 0.5)
		p.Position = UDim2.new(1, -52, 0.5, 0)
		p.Parent = top
	end
	local y = compact and 44 or 64
	if DATA.tabs and #DATA.tabs > 0 then
		local row = tabs(frame, DATA.tabs, compact and 38 or 40, compact and 104 or 120)
		row.Position = UDim2.fromOffset(0, y)
		frame:FindFirstChild("Indicator").Position = UDim2.fromOffset(0, y + (compact and 35 or 37))
		y += compact and 42 or 50
	end
	local detailW = compact and 0 or 330
	local gridW = (compact and 776 or 1060) - detailW - (compact and 0 or 16)
	local columns = compact and 5 or 4
	local cellW = math.floor((gridW - 12 - (columns - 1) * 12) / columns)
	local cellH = compact and math.floor(cellW * 1.32) or math.floor(cellW * 1.32)
	local grid = scrollGrid(frame, UDim2.new(0, gridW, 1, -y), UDim2.fromOffset(0, y), Vector2.new(cellW, cellH), 12, columns)
	local show = nil
	if not compact then
		local _, s = detailPane(frame, UDim2.new(0, detailW, 1, -y), UDim2.new(1, -detailW, 0, y), "Buy")
		show = s
		show(items[1])
	end
	for i, item in ipairs(items) do
		itemCard(item, cellW, cellH, i, show).Parent = grid
	end
	openAnimation(canvas, uiScale)
	local first = grid:FindFirstChild("Card1")
	return first and first:FindFirstChild("Face", true)
end

SCREENS.inventory = function(mode: string)
	local items = itemsOr({ { name = "Item", kind = "gem", rarity = "common" } })
	local compact = mode == "compact"
	local w, h = compact and 800 or 1060, compact and 360 or 600
	local canvas, uiScale = makeCanvas(root, w, h)
	local frame = panel({ Name = "InventoryPanel", Size = UDim2.fromScale(1, 1), Parent = canvas })
	pad(compact and 12 or 20).Parent = frame
	local top = header(frame, DATA.title, not compact and DATA.subtitle or nil, compact and 40 or 56, true)
	text("numeric", string.format("%d / %d", #items, DATA.capacity or 40), T.type.label, rgb(T.c.textDim), {
		AnchorPoint = Vector2.new(1, 0.5),
		Position = UDim2.new(1, -52, 0.5, 0),
		Size = UDim2.fromOffset(120, 24),
		TextXAlignment = Enum.TextXAlignment.Right,
		Parent = top,
	})
	local y = compact and 46 or 66
	local detailW = compact and 0 or 300
	local gridW = (compact and 776 or 1020) - detailW - (compact and 0 or 16)
	local slot = compact and 84 or 96
	local grid = scrollGrid(frame, UDim2.new(0, gridW, 1, -y), UDim2.fromOffset(0, y), Vector2.new(slot, slot), 10)
	local show = nil
	if not compact then
		local _, s = detailPane(frame, UDim2.new(0, detailW, 1, -y), UDim2.new(1, -detailW, 0, y), "Equip")
		show = s
		show(items[1])
	end
	for i, item in ipairs(items) do
		local cell = new("TextButton", {
			Name = "Slot" .. i,
			AutoButtonColor = false,
			Text = "",
			BackgroundColor3 = rgb(T.c.surface2),
			BackgroundTransparency = T.surface2Alpha,
			LayoutOrder = i,
			Selectable = true,
			SelectionImageObject = focusRing,
			Parent = grid,
		}, { corner(math.max(4, T.radius - 4)), stroke(rarityColor(item.rarity), item.equipped and 2.5 or 1, item.equipped and 0 or 0.4) })
		iconTile(item.kind, item.rarity, slot - 14, { AnchorPoint = Vector2.new(0.5, 0.5), Position = UDim2.fromScale(0.5, 0.5), Parent = cell })
		if item.count and item.count > 1 then
			text("numeric", "x" .. item.count, T.type.caption, rgb(T.c.text), {
				AnchorPoint = Vector2.new(1, 1),
				Position = UDim2.new(1, -6, 1, -4),
				Size = UDim2.fromOffset(40, 16),
				TextXAlignment = Enum.TextXAlignment.Right,
				ZIndex = 4,
				Parent = cell,
			})
		end
		if item.equipped then
			badge("E", rgb(T.c.accent), { Position = UDim2.fromOffset(4, 4), ZIndex = 4, Parent = cell })
		end
		cell.Activated:Connect(function()
			if show then
				show(item)
			end
		end)
	end
	openAnimation(canvas, uiScale)
	return grid:FindFirstChild("Slot1")
end

SCREENS.hud = function(mode: string)
	local compact = mode == "compact"
	local s = compact and 0.82 or 1
	-- Top-left: currencies.
	local tl, tlScale = makeCanvas(root, 200, 96, Vector2.new(0, 0), UDim2.fromOffset(12, 12))
	tlScale.Scale = s
	list("Vertical", 8).Parent = tl
	local currencies = DATA.currencies or { DATA.currency or { amount = 0 } }
	for i, c in ipairs(currencies) do
		local p = pill(c.amount or 0, c.color, 180)
		p.LayoutOrder = i
		p.Parent = tl
	end
	-- Top-right: objective tracker.
	if DATA.objective then
		local tr, trScale = makeCanvas(root, 300, 92, Vector2.new(1, 0), UDim2.new(1, -12, 0, 12))
		trScale.Scale = s
		local card = panel({ Name = "Objective", Size = UDim2.fromScale(1, 1), Parent = tr }, 2)
		pad(12).Parent = card
		text("label", string.upper(DATA.objective.label or "Objective"), T.type.caption, rgb(T.c.accent), { Size = UDim2.new(1, 0, 0, 16), Parent = card })
		text("body", DATA.objective.text or "", T.type.body, rgb(T.c.text), { Position = UDim2.fromOffset(0, 20), Size = UDim2.new(1, 0, 0, 22), Parent = card })
		local b = bar(DATA.objective.progress or 0.5, T.c.accent, 8)
		b.Position = UDim2.new(0, 0, 1, -10)
		b.Parent = card
	end
	-- Bottom-centre: vitals + hotbar.
	local slots = DATA.hotbar or {}
	local slotSize = compact and 54 or 64
	local width = math.max(420, #slots * (slotSize + 8))
	local bc, bcScale = makeCanvas(root, width, slotSize + 64, Vector2.new(0.5, 1), UDim2.new(0.5, 0, 1, -12))
	bcScale.Scale = s
	local hp = DATA.health or { value = 80, max = 100 }
	local hpBar = bar(hp.value / hp.max, T.c.good, 16, UDim.new(0, 360))
	hpBar.AnchorPoint = Vector2.new(0.5, 0)
	hpBar.Position = UDim2.fromScale(0.5, 0)
	hpBar.Parent = bc
	text("numeric", string.format("%d / %d", hp.value, hp.max), T.type.caption, rgb(T.c.text), {
		Size = UDim2.fromScale(1, 1),
		TextXAlignment = Enum.TextXAlignment.Center,
		ZIndex = 3,
		Parent = hpBar,
	})
	if DATA.stamina then
		local st = bar(DATA.stamina, T.c.secondary, 6, UDim.new(0, 300))
		st.AnchorPoint = Vector2.new(0.5, 0)
		st.Position = UDim2.new(0.5, 0, 0, 22)
		st.Parent = bc
	end
	local row = new("Frame", {
		Name = "Hotbar",
		BackgroundTransparency = 1,
		AnchorPoint = Vector2.new(0.5, 1),
		Position = UDim2.fromScale(0.5, 1),
		Size = UDim2.new(1, 0, 0, slotSize),
		Parent = bc,
	})
	list("Horizontal", 8, "Center").Parent = row
	local first = nil
	for i, slot in ipairs(slots) do
		local cell = new("TextButton", {
			Name = "Slot" .. i,
			AutoButtonColor = false,
			Text = "",
			BackgroundColor3 = rgb(T.c.surface),
			BackgroundTransparency = T.surfaceAlpha,
			Size = UDim2.fromOffset(slotSize, slotSize),
			LayoutOrder = i,
			Selectable = true,
			SelectionImageObject = focusRing,
			Parent = row,
		}, { corner(math.max(4, T.radius - 4)), stroke(rgb(i == 1 and T.c.accent or T.c.strokeSoft), i == 1 and 2.5 or 1, i == 1 and 0 or 0.3) })
		first = first or cell
		iconTile(slot.kind, slot.rarity, slotSize - 12, { AnchorPoint = Vector2.new(0.5, 0.5), Position = UDim2.fromScale(0.5, 0.5), Parent = cell })
		badge(slot.key or tostring(i), rgb(T.c.surface2), { Position = UDim2.fromOffset(-4, -6), ZIndex = 4, Parent = cell })
		if slot.cooldown and slot.cooldown > 0 then
			local veil = new("Frame", {
				Name = "Cooldown",
				BackgroundColor3 = Color3.new(0, 0, 0),
				BackgroundTransparency = 0.45,
				AnchorPoint = Vector2.new(0, 1),
				Position = UDim2.fromScale(0, 1),
				Size = UDim2.fromScale(1, slot.cooldown),
				ZIndex = 3,
				Parent = cell,
			}, { corner(math.max(4, T.radius - 4)) })
			text("numeric", string.format("%.0f", slot.cooldown * 10), T.type.h3, Color3.new(1, 1, 1), {
				Size = UDim2.fromScale(1, 1),
				TextXAlignment = Enum.TextXAlignment.Center,
				ZIndex = 4,
				Parent = cell,
			})
			tween(veil, slot.cooldown * 10, { Size = UDim2.fromScale(1, 0) }, "Linear")
		end
	end
	return first
end

SCREENS.settings = function(mode: string)
	local compact = mode == "compact"
	local w, h = compact and 760 or 820, compact and 360 or 580
	local canvas, uiScale = makeCanvas(root, w, h)
	local frame = panel({ Name = "SettingsPanel", Size = UDim2.fromScale(1, 1), Parent = canvas })
	pad(compact and 12 or 22).Parent = frame
	header(frame, DATA.title, nil, compact and 40 or 52, true)
	local y = compact and 46 or 64
	local sideW = compact and 0 or 190
	if DATA.tabs and #DATA.tabs > 0 then
		if compact then
			local row = tabs(frame, DATA.tabs, 38, 110)
			row.Position = UDim2.fromOffset(0, y)
			frame:FindFirstChild("Indicator").Position = UDim2.fromOffset(0, y + 35)
			y += 42
		else
			local side = new("Frame", { Name = "Sidebar", BackgroundTransparency = 1, Position = UDim2.fromOffset(0, y), Size = UDim2.new(0, sideW - 16, 1, -y - 60), Parent = frame })
			list("Vertical", 6).Parent = side
			for i, name in ipairs(DATA.tabs) do
				local b = button(name, i == 1 and "secondary" or "ghost", UDim2.new(1, 0, 0, 44))
				b.LayoutOrder = i
				b.Parent = side
				local face = b:FindFirstChild("Face")
				face.TextXAlignment = Enum.TextXAlignment.Left
				pad(0, 14).Parent = face
			end
		end
	end
	local rows = new("ScrollingFrame", {
		Name = "Rows",
		BackgroundTransparency = 1,
		BorderSizePixel = 0,
		Position = UDim2.fromOffset(sideW, y),
		Size = UDim2.new(1, -sideW, 1, -y - (compact and 50 or 64)),
		AutomaticCanvasSize = Enum.AutomaticSize.Y,
		CanvasSize = UDim2.new(),
		ScrollBarThickness = 4,
		ScrollBarImageColor3 = rgb(T.c.textDim),
		Selectable = false,
		Parent = frame,
	})
	list("Vertical", 8).Parent = rows
	local first = nil
	for i, opt in ipairs(DATA.options or {}) do
		local row = panel({ Name = "Row" .. i, Size = UDim2.new(1, -10, 0, compact and 52 or 58), LayoutOrder = i, Parent = rows }, 2)
		pad(0, 14).Parent = row
		text("label", opt.label or "Option", T.type.body, rgb(T.c.text), { Size = UDim2.new(0.5, 0, 1, 0), Parent = row })
		local kind = opt.kind or "toggle"
		if kind == "toggle" then
			local on = opt.value ~= false
			local switch = new("TextButton", {
				Name = "Toggle",
				AutoButtonColor = false,
				Text = "",
				AnchorPoint = Vector2.new(1, 0.5),
				Position = UDim2.new(1, 0, 0.5, 0),
				Size = UDim2.fromOffset(64, 36),
				BackgroundColor3 = rgb(on and T.c.accent or T.c.track),
				Selectable = true,
				SelectionImageObject = focusRing,
				Parent = row,
			}, { corner(18) })
			local knob = new("Frame", {
				BackgroundColor3 = Color3.new(1, 1, 1),
				Size = UDim2.fromOffset(28, 28),
				Position = on and UDim2.fromOffset(32, 4) or UDim2.fromOffset(4, 4),
				Parent = switch,
			}, { corner(14) })
			switch.Activated:Connect(function()
				on = not on
				tween(knob, 0.18, { Position = on and UDim2.fromOffset(32, 4) or UDim2.fromOffset(4, 4) }, "Quart")
				tween(switch, 0.18, { BackgroundColor3 = rgb(on and T.c.accent or T.c.track) }, "Quad")
			end)
			first = first or switch
		elseif kind == "slider" then
			local value = math.clamp(opt.value or 0.5, 0, 1)
			local track = bar(value, T.c.accent, 8, UDim.new(0, compact and 200 or 240))
			track.AnchorPoint = Vector2.new(1, 0.5)
			track.Position = UDim2.new(1, -56, 0.5, 0)
			track.Parent = row
			local knob = new("TextButton", {
				Name = "Knob",
				Text = "",
				AutoButtonColor = false,
				AnchorPoint = Vector2.new(0.5, 0.5),
				Position = UDim2.new(value, 0, 0.5, 0),
				Size = UDim2.fromOffset(38, 38),
				BackgroundTransparency = 1,
				Selectable = true,
				SelectionImageObject = focusRing,
				ZIndex = 3,
				Parent = track,
			})
			new("Frame", {
				AnchorPoint = Vector2.new(0.5, 0.5),
				Position = UDim2.fromScale(0.5, 0.5),
				Size = UDim2.fromOffset(22, 22),
				BackgroundColor3 = Color3.new(1, 1, 1),
				ZIndex = 3,
				Parent = knob,
			}, { corner(11), stroke(rgb(T.c.accent), 2, 0) })
			text("numeric", tostring(math.floor(value * 100)), T.type.label, rgb(T.c.textDim), {
				AnchorPoint = Vector2.new(1, 0.5),
				Position = UDim2.new(1, 0, 0.5, 0),
				Size = UDim2.fromOffset(44, 24),
				TextXAlignment = Enum.TextXAlignment.Right,
				Parent = row,
			})
			first = first or knob
		else
			local choices = opt.choices or { "Low", "Medium", "High" }
			local group = new("Frame", {
				Name = "Segmented",
				AnchorPoint = Vector2.new(1, 0.5),
				Position = UDim2.new(1, 0, 0.5, 0),
				Size = UDim2.fromOffset(#choices * (compact and 78 or 88), 42),
				BackgroundColor3 = rgb(T.c.track),
				Parent = row,
			}, { corner(math.max(4, T.radius - 4)), pad(3) })
			list("Horizontal", 2).Parent = group
			for j, choice in ipairs(choices) do
				local selected = (opt.value == choice) or (opt.value == nil and j == 2)
				local seg = new("TextButton", {
					Name = "Choice" .. j,
					AutoButtonColor = false,
					Size = UDim2.new(1 / #choices, -2, 1, 0),
					BackgroundColor3 = rgb(T.c.accent),
					BackgroundTransparency = selected and 0 or 1,
					FontFace = font("label"),
					Text = choice,
					TextSize = T.type.caption,
					TextColor3 = rgb(selected and T.c.accentText or T.c.textDim),
					LayoutOrder = j,
					Selectable = true,
					SelectionImageObject = focusRing,
					Parent = group,
				}, { corner(math.max(3, T.radius - 6)) })
				first = first or seg
			end
		end
	end
	local footer = new("Frame", { Name = "Footer", BackgroundTransparency = 1, AnchorPoint = Vector2.new(0, 1), Position = UDim2.fromScale(0, 1), Size = UDim2.new(1, 0, 0, compact and 42 or 50), Parent = frame })
	list("Horizontal", 12, "Right", "Center").Parent = footer
	local actions = DATA.actions or { "Apply", "Reset" }
	for i = #actions, 1, -1 do
		local b = button(actions[i], i == 1 and "primary" or "ghost", UDim2.fromOffset(compact and 130 or 150, compact and 44 or 48))
		b.LayoutOrder = #actions - i + 1
		b.Parent = footer
	end
	openAnimation(canvas, uiScale)
	return first
end

SCREENS.menu = function(mode: string)
	local compact = mode == "compact"
	-- Cinematic vignette over the game scene so the menu reads on any background.
	local vignette = new("Frame", {
		Name = "Vignette",
		BackgroundColor3 = rgb(T.c.vignette),
		Size = UDim2.new(1, 0, 1, 80),
		Position = UDim2.fromOffset(0, -60),
		BorderSizePixel = 0,
		Parent = root,
	}, {
		new("UIGradient", {
			Transparency = NumberSequence.new({
				NumberSequenceKeypoint.new(0, 0.05),
				NumberSequenceKeypoint.new(0.55, 0.55),
				NumberSequenceKeypoint.new(1, 0.95),
			}),
		}),
	})
	local w, h = compact and 800 or 1180, compact and 360 or 640
	local canvas, uiScale = makeCanvas(vignette, w, h, nil, UDim2.new(0.5, 0, 0.5, 40))
	local left = new("Frame", { Name = "Left", BackgroundTransparency = 1, Size = UDim2.new(0, compact and 380 or 480, 1, 0), Parent = canvas })
	text("display", DATA.title, compact and T.type.display * 0.8 or T.type.display, rgb(T.c.text), {
		Size = UDim2.new(1, 0, 0, compact and 96 or 140),
		TextWrapped = true,
		TextTruncate = Enum.TextTruncate.None,
		TextYAlignment = Enum.TextYAlignment.Bottom,
		LineHeight = 0.9,
		Parent = left,
	})
	if DATA.subtitle then
		text("body", DATA.subtitle, T.type.body, rgb(T.c.textDim), { Position = UDim2.fromOffset(2, compact and 100 or 148), Size = UDim2.new(1, 0, 0, 22), Parent = left })
	end
	local stack = new("Frame", {
		Name = "Buttons",
		BackgroundTransparency = 1,
		Position = UDim2.fromOffset(0, compact and 132 or 200),
		Size = UDim2.new(0, compact and 250 or 300, 1, compact and -132 or -200),
		Parent = left,
	})
	list("Vertical", compact and 8 or 12).Parent = stack
	local first = nil
	for i, label in ipairs(DATA.actions or { "Play", "Settings" }) do
		local b = button(label, i == 1 and "primary" or "secondary", UDim2.new(1, 0, 0, compact and 44 or 56))
		b.LayoutOrder = i
		b.Parent = stack
		first = first or b:FindFirstChild("Face")
			end
	if DATA.body and not compact then
		local news = panel({ Name = "News", AnchorPoint = Vector2.new(1, 1), Position = UDim2.new(1, 0, 1, -20), Size = UDim2.fromOffset(340, 210), Parent = canvas })
		pad(18).Parent = news
		badge(DATA.newsTag or "Update", rgb(T.c.accent), { Parent = news })
		text("display", DATA.newsTitle or "What's new", T.type.h2, rgb(T.c.text), { Position = UDim2.fromOffset(0, 32), Size = UDim2.new(1, 0, 0, 34), Parent = news })
		text("body", DATA.body, T.type.body, rgb(T.c.textDim), {
			Position = UDim2.fromOffset(0, 72),
			Size = UDim2.new(1, 0, 1, -72),
			TextWrapped = true,
			TextTruncate = Enum.TextTruncate.AtEnd,
			TextYAlignment = Enum.TextYAlignment.Top,
			Parent = news,
		})
	end
	openAnimation(canvas, uiScale)
	return first
end

SCREENS.dialog = function(mode: string)
	local compact = mode == "compact"
	local w, h = compact and 800 or 960, compact and 190 or 230
	local canvas, uiScale = makeCanvas(root, w, h, Vector2.new(0.5, 1), UDim2.new(0.5, 0, 1, -16))
	local frame = panel({ Name = "DialogPanel", Position = UDim2.fromOffset(0, 18), Size = UDim2.new(1, 0, 1, -18), Parent = canvas })
	local plate = new("Frame", { Name = "NamePlate", BackgroundColor3 = rgb(T.c.accent), Position = UDim2.fromOffset(compact and 140 or 170, 0), Size = UDim2.fromOffset(220, 34), ZIndex = 4, Parent = canvas }, { corner(math.max(4, T.radius - 4)) })
	text("label", DATA.speaker or "Stranger", T.type.label, rgb(T.c.accentText), { Size = UDim2.fromScale(1, 1), TextXAlignment = Enum.TextXAlignment.Center, ZIndex = 5, Parent = plate })
	local portraitSize = compact and 120 or 150
	local portrait = iconTile(DATA.portrait or "pet", "epic", portraitSize, { Position = UDim2.fromOffset(16, 16), Parent = frame })
	local textX = portraitSize + 32
	local choicesW = compact and 230 or 280
	local body = text("body", "", compact and T.type.body or T.type.h3 * 0.9, rgb(T.c.text), {
		Position = UDim2.fromOffset(textX, 30),
		Size = UDim2.new(1, -(textX + choicesW + 24), 1, -44),
		TextWrapped = true,
		TextTruncate = Enum.TextTruncate.None,
		TextYAlignment = Enum.TextYAlignment.Top,
		Parent = frame,
	})
	body.Text = DATA.body or ""
	body.MaxVisibleGraphemes = 0
	local total = utf8.len(body.Text) or #body.Text
	task.spawn(function()
		for i = 1, total do
			body.MaxVisibleGraphemes = i
			task.wait(0.018)
		end
		body.MaxVisibleGraphemes = -1
	end)
	local choices = new("Frame", { Name = "Choices", BackgroundTransparency = 1, AnchorPoint = Vector2.new(1, 0), Position = UDim2.new(1, -16, 0, 16), Size = UDim2.new(0, choicesW, 1, -32), Parent = frame })
	list("Vertical", 8, "Left", "Center").Parent = choices
	local first = nil
	local actions = DATA.actions or { "Continue" }
	local bh = math.min(compact and 44 or 48, math.floor(((compact and 190 or 230) - 18 - 32 - (#actions - 1) * 8) / math.max(1, #actions)))
	for i, label in ipairs(actions) do
		local b = button(label, i == 1 and "primary" or "secondary", UDim2.new(1, 0, 0, bh))
		b.LayoutOrder = i
		b.Parent = choices
		first = first or b:FindFirstChild("Face")
		local face = b:FindFirstChild("Face")
		face.TextXAlignment = Enum.TextXAlignment.Left
		pad(0, 40).Parent = face
		badge(tostring(i), shade(rgb(i == 1 and T.c.accent or T.c.secondary), -0.35), { AnchorPoint = Vector2.new(0, 0.5), Position = UDim2.new(0, -30, 0.5, 0), Parent = face })
	end
	openAnimation(canvas, uiScale)
	return first
end

SCREENS.leaderboard = function(mode: string)
	local compact = mode == "compact"
	local entries = DATA.entries or {}
	local w, h = compact and 720 or 560, compact and 360 or 640
	local canvas, uiScale = makeCanvas(root, w, h)
	local frame = panel({ Name = "LeaderboardPanel", Size = UDim2.fromScale(1, 1), Parent = canvas })
	pad(compact and 12 or 20).Parent = frame
	header(frame, DATA.title, nil, compact and 38 or 50, true)
	local y = compact and 42 or 58
	if DATA.tabs and #DATA.tabs > 0 then
		local row = tabs(frame, DATA.tabs, 38, 110)
		row.Position = UDim2.fromOffset(0, y)
		frame:FindFirstChild("Indicator").Position = UDim2.fromOffset(0, y + 35)
		y += 44
	end
	local medals = { T.c.gold, T.c.silver, T.c.bronze }
	local podiumH = compact and 0 or 150
	if not compact then
		local podium = new("Frame", { Name = "Podium", BackgroundTransparency = 1, Position = UDim2.fromOffset(0, y), Size = UDim2.new(1, 0, 0, podiumH), Parent = frame })
		list("Horizontal", 12, "Center", "Bottom").Parent = podium
		local order = { 2, 1, 3 }
		for slotIndex, rank in ipairs(order) do
			local e = entries[rank]
			if e then
				local hh = rank == 1 and podiumH or podiumH - 22
				local card = panel({ Name = "Podium" .. rank, Size = UDim2.fromOffset(150, hh), LayoutOrder = slotIndex }, 2)
				card.Parent = podium
				stroke(rgb(medals[rank]), 2, 0).Parent = card
				badge("#" .. rank, rgb(medals[rank]), { AnchorPoint = Vector2.new(0.5, 0), Position = UDim2.new(0.5, 0, 0, 10), Parent = card })
				text("label", e.name, T.type.body, rgb(T.c.text), { Position = UDim2.new(0, 8, 1, -64), Size = UDim2.new(1, -16, 0, 22), TextXAlignment = Enum.TextXAlignment.Center, Parent = card })
				text("numeric", formatNumber(e.value or 0), T.type.h3, rgb(medals[rank]), { Position = UDim2.new(0, 8, 1, -38), Size = UDim2.new(1, -16, 0, 26), TextXAlignment = Enum.TextXAlignment.Center, Parent = card })
			end
		end
		y += podiumH + 12
	end
	local listFrame = new("ScrollingFrame", {
		Name = "Rows",
		BackgroundTransparency = 1,
		BorderSizePixel = 0,
		Position = UDim2.fromOffset(0, y),
		Size = UDim2.new(1, 0, 1, -y - 54),
		AutomaticCanvasSize = Enum.AutomaticSize.Y,
		CanvasSize = UDim2.new(),
		ScrollBarThickness = 4,
		ScrollBarImageColor3 = rgb(T.c.textDim),
		Selectable = false,
		Parent = frame,
	})
	list("Vertical", 6).Parent = listFrame
	local function row(rank: number, e, parent: Instance, highlight: boolean)
		local r = panel({ Name = "Rank" .. rank, Size = UDim2.new(1, -8, 0, 40), LayoutOrder = rank, Parent = parent }, 2)
		if highlight then
			r.BackgroundColor3 = rgb(T.c.accent)
			r.BackgroundTransparency = 0.75
			stroke(rgb(T.c.accent), 1.5, 0).Parent = r
		end
		pad(0, 14).Parent = r
		text("numeric", tostring(rank), T.type.label, rgb(medals[rank] or T.c.textDim), { Size = UDim2.new(0, 40, 1, 0), Parent = r })
		text("label", e.name, T.type.body, rgb(T.c.text), { Position = UDim2.fromOffset(44, 0), Size = UDim2.new(1, -164, 1, 0), Parent = r })
		text("numeric", formatNumber(e.value or 0), T.type.label, rgb(T.c.text), { AnchorPoint = Vector2.new(1, 0), Position = UDim2.fromScale(1, 0), Size = UDim2.new(0, 110, 1, 0), TextXAlignment = Enum.TextXAlignment.Right, Parent = r })
		return r
	end
	for rank, e in ipairs(entries) do
		if compact or rank > 3 then
			row(rank, e, listFrame, false)
		end
	end
	if DATA.you then
		local mine = row(DATA.you.rank or 99, DATA.you, frame, true)
		mine.AnchorPoint = Vector2.new(0, 1)
		mine.Position = UDim2.new(0, 0, 1, -4)
		mine.Size = UDim2.new(1, 0, 0, 44)
	end
	openAnimation(canvas, uiScale)
	return frame:FindFirstChild("Tab1", true)
end

SCREENS.rewards = function(mode: string)
	local compact = mode == "compact"
	local days = itemsOr({})
	local w, h = compact and 800 or 1000, compact and 350 or 460
	local canvas, uiScale = makeCanvas(root, w, h)
	local frame = panel({ Name = "RewardsPanel", Size = UDim2.fromScale(1, 1), Parent = canvas })
	pad(compact and 14 or 24).Parent = frame
	local top = header(frame, DATA.title, DATA.subtitle, compact and 44 or 60, true)
	local count = math.max(1, #days)
	local gap = compact and 8 or 12
	local cardW = math.floor(((compact and 772 or 952) - (count - 1) * gap) / count)
	local cardH = compact and 170 or 230
	local row = new("Frame", { Name = "Days", BackgroundTransparency = 1, Position = UDim2.fromOffset(0, compact and 54 or 78), Size = UDim2.new(1, 0, 0, cardH), Parent = frame })
	list("Horizontal", gap, "Center").Parent = row
	local today = DATA.today or 1
	for i, item in ipairs(days) do
		local state = i < today and "claimed" or i == today and "today" or "locked"
		local card = panel({ Name = "Day" .. i, Size = UDim2.fromOffset(cardW, cardH), LayoutOrder = i, Parent = row }, 2)
		if state == "today" then
			local glow = stroke(rgb(T.c.accent), 2.5, 0)
			glow.Parent = card
			TweenService:Create(glow, TweenInfo.new(0.9, Enum.EasingStyle.Sine, Enum.EasingDirection.InOut, -1, true), { Transparency = 0.6 }):Play()
		end
		text("label", "DAY " .. i, T.type.caption, rgb(state == "today" and T.c.accent or T.c.textDim), { Position = UDim2.fromOffset(0, 8), Size = UDim2.new(1, 0, 0, 18), TextXAlignment = Enum.TextXAlignment.Center, Parent = card })
		local iconSize = math.min(cardW - 20, cardH - 80)
		local tile = iconTile(item.kind, item.rarity, iconSize, { AnchorPoint = Vector2.new(0.5, 0), Position = UDim2.new(0.5, 0, 0, 30), Parent = card })
		text("numeric", item.amount and ("x" .. formatNumber(item.amount)) or (item.name or ""), T.type.label, rgb(T.c.text), { Position = UDim2.new(0, 4, 1, -34), Size = UDim2.new(1, -8, 0, 24), TextXAlignment = Enum.TextXAlignment.Center, Parent = card })
		if state == "claimed" then
			card.BackgroundTransparency = 0.6
			tile.BackgroundTransparency = 0.5
			local check = new("Frame", { Name = "Claimed", BackgroundColor3 = rgb(T.c.good), AnchorPoint = Vector2.new(0.5, 0.5), Position = UDim2.fromScale(0.5, 0.5), Size = UDim2.fromOffset(34, 34), ZIndex = 4, Parent = tile }, { corner(17) })
			-- check mark drawn from two rotated bars (no glyph or image needed)
			new("Frame", { BackgroundColor3 = Color3.fromRGB(16, 40, 22), BorderSizePixel = 0, AnchorPoint = Vector2.new(0.5, 0.5), Position = UDim2.fromScale(0.36, 0.58), Size = UDim2.fromOffset(11, 4), Rotation = 45, ZIndex = 5, Parent = check }, { corner(2) })
			new("Frame", { BackgroundColor3 = Color3.fromRGB(16, 40, 22), BorderSizePixel = 0, AnchorPoint = Vector2.new(0.5, 0.5), Position = UDim2.fromScale(0.58, 0.48), Size = UDim2.fromOffset(18, 4), Rotation = -50, ZIndex = 5, Parent = check }, { corner(2) })
		elseif state == "locked" then
			local veil = new("Frame", { Name = "Locked", BackgroundColor3 = Color3.new(0, 0, 0), BackgroundTransparency = 0.55, Size = UDim2.fromScale(1, 1), ZIndex = 3, Parent = tile }, { corner(math.max(4, T.radius - 2)) })
		end
	end
	local claim = button((DATA.actions and DATA.actions[1]) or "Claim", "primary", UDim2.fromOffset(compact and 220 or 260, compact and 46 or 54), nil, {
		AnchorPoint = Vector2.new(0.5, 1),
		Position = UDim2.new(0.5, 0, 1, 0),
		Parent = frame,
	})
	openAnimation(canvas, uiScale)
	return claim:FindFirstChild("Face")
end

SCREENS.quest = function(mode: string)
	local compact = mode == "compact"
	local quests = DATA.quests or {}
	local w, h = compact and 800 or 900, compact and 360 or 580
	local canvas, uiScale = makeCanvas(root, w, h)
	local frame = panel({ Name = "QuestPanel", Size = UDim2.fromScale(1, 1), Parent = canvas })
	pad(compact and 12 or 20).Parent = frame
	header(frame, DATA.title, nil, compact and 40 or 52, true)
	local y = compact and 46 or 64
	local listW = compact and 330 or 380
	local listFrame = new("ScrollingFrame", {
		Name = "QuestList",
		BackgroundTransparency = 1,
		BorderSizePixel = 0,
		Position = UDim2.fromOffset(0, y),
		Size = UDim2.new(0, listW, 1, -y),
		AutomaticCanvasSize = Enum.AutomaticSize.Y,
		CanvasSize = UDim2.new(),
		ScrollBarThickness = 4,
		ScrollBarImageColor3 = rgb(T.c.textDim),
		Selectable = false,
		Parent = frame,
	})
	list("Vertical", 8).Parent = listFrame
	local detail = panel({ Name = "QuestDetail", Position = UDim2.fromOffset(listW + 16, y), Size = UDim2.new(1, -(listW + 16), 1, -y), Parent = frame }, 2)
	pad(compact and 12 or 18).Parent = detail
	local function show(q)
		detail:ClearAllChildren()
		pad(compact and 12 or 18).Parent = detail
		text("display", q.title or "Quest", T.type.h2, rgb(T.c.text), { Size = UDim2.new(1, 0, 0, 34), Parent = detail })
		text("body", q.description or "", T.type.body, rgb(T.c.textDim), { Position = UDim2.fromOffset(0, 40), Size = UDim2.new(1, 0, 0, compact and 40 or 64), TextWrapped = true, TextTruncate = Enum.TextTruncate.AtEnd, TextYAlignment = Enum.TextYAlignment.Top, Parent = detail })
		local objectives = new("Frame", { Name = "Objectives", BackgroundTransparency = 1, Position = UDim2.fromOffset(0, compact and 86 or 112), Size = UDim2.new(1, 0, 0, 120), Parent = detail })
		list("Vertical", 6).Parent = objectives
		for i, o in ipairs(q.objectives or {}) do
			local line = new("Frame", { Name = "Objective" .. i, BackgroundTransparency = 1, Size = UDim2.new(1, 0, 0, 24), LayoutOrder = i, Parent = objectives })
			new("Frame", { BackgroundColor3 = rgb(o.done and T.c.good or T.c.track), Size = UDim2.fromOffset(14, 14), Position = UDim2.fromOffset(0, 5), Parent = line }, { corner(4) })
			text("body", o.text or "", T.type.body, rgb(o.done and T.c.textDim or T.c.text), { Position = UDim2.fromOffset(24, 0), Size = UDim2.new(1, -24, 1, 0), Parent = line })
		end
		local track = button((DATA.actions and DATA.actions[1]) or "Track", "primary", UDim2.fromOffset(compact and 150 or 180, compact and 44 or 48), nil, {
			AnchorPoint = Vector2.new(1, 1),
			Position = UDim2.fromScale(1, 1),
			Parent = detail,
		})
		if q.reward then
			local reward = new("Frame", { Name = "Reward", BackgroundTransparency = 1, AnchorPoint = Vector2.new(0, 1), Position = UDim2.fromScale(0, 1), Size = UDim2.fromOffset(220, 40), Parent = detail })
			local c = coin(26)
			c.Position = UDim2.fromOffset(0, 7)
			c.Parent = reward
			text("numeric", "+" .. formatNumber(q.reward), T.type.h3, rgb(T.c.currency), { Position = UDim2.fromOffset(34, 0), Size = UDim2.new(1, -34, 1, 0), Parent = reward })
		end
	end
	local first = nil
	for i, q in ipairs(quests) do
		local b = new("TextButton", {
			Name = "Quest" .. i,
			AutoButtonColor = false,
			Text = "",
			BackgroundColor3 = rgb(i == 1 and T.c.accent or T.c.surface2),
			BackgroundTransparency = i == 1 and 0.78 or T.surface2Alpha,
			Size = UDim2.new(1, -8, 0, compact and 58 or 66),
			LayoutOrder = i,
			Selectable = true,
			SelectionImageObject = focusRing,
			Parent = listFrame,
		}, { corner(math.max(4, T.radius - 4)), pad(10, 12) })
		first = first or b
		text("label", q.title or "Quest", T.type.body, rgb(T.c.text), { Size = UDim2.new(1, -60, 0, 20), Parent = b })
		text("numeric", string.format("%d%%", math.floor((q.progress or 0) * 100)), T.type.caption, rgb(T.c.textDim), { AnchorPoint = Vector2.new(1, 0), Position = UDim2.fromScale(1, 0), Size = UDim2.fromOffset(56, 20), TextXAlignment = Enum.TextXAlignment.Right, Parent = b })
		local p = bar(q.progress or 0, T.c.accent, 6)
		p.AnchorPoint = Vector2.new(0, 1)
		p.Position = UDim2.fromScale(0, 1)
		p.Parent = b
		b.Activated:Connect(function()
			show(q)
		end)
	end
	if quests[1] then
		show(quests[1])
	end
	openAnimation(canvas, uiScale)
	return first
end

SCREENS.results = function(mode: string)
	local compact = mode == "compact"
	local stats = DATA.stats or {}
	local rewards = itemsOr({})
	local w, h = compact and 800 or 900, compact and 360 or 600
	local backdrop = new("Frame", {
		Name = "Backdrop",
		BackgroundColor3 = rgb(T.c.vignette),
		BackgroundTransparency = 0.3,
		Size = UDim2.new(1, 0, 1, 80),
		Position = UDim2.fromOffset(0, -60),
		BorderSizePixel = 0,
		Parent = root,
	})
	local canvas, uiScale = makeCanvas(backdrop, w, h, nil, UDim2.new(0.5, 0, 0.5, 20))
	local banner = text("display", DATA.title, compact and T.type.display * 0.9 or T.type.display * 1.25, Color3.new(1, 1, 1), {
		Size = UDim2.new(1, 0, 0, compact and 64 or 96),
		TextXAlignment = Enum.TextXAlignment.Center,
		Parent = canvas,
	})
	new("UIGradient", { Color = ColorSequence.new(rgb(T.c.bannerTop), rgb(T.c.bannerBottom)), Rotation = 90, Parent = banner })
	if DATA.subtitle then
		text("body", DATA.subtitle, T.type.body, rgb(T.c.textDim), { Position = UDim2.fromOffset(0, compact and 64 or 98), Size = UDim2.new(1, 0, 0, 22), TextXAlignment = Enum.TextXAlignment.Center, Parent = canvas })
	end
	local statsY = compact and 96 or 140
	local cols = math.min(#stats, compact and 4 or 3)
	local tileW = compact and 180 or 270
	local tileH = compact and 66 or 84
	local statGrid = new("Frame", { Name = "Stats", BackgroundTransparency = 1, Position = UDim2.fromOffset(0, statsY), Size = UDim2.new(1, 0, 0, compact and tileH or tileH * 2 + 12), Parent = canvas })
	new("UIGridLayout", { CellSize = UDim2.fromOffset(tileW, tileH), CellPadding = UDim2.fromOffset(12, 12), HorizontalAlignment = Enum.HorizontalAlignment.Center, SortOrder = Enum.SortOrder.LayoutOrder, Parent = statGrid })
	for i, s in ipairs(stats) do
		if compact and i > 4 then
			break
		end
		local tile = panel({ Name = "Stat" .. i, LayoutOrder = i, Parent = statGrid }, 2)
		pad(10, 14).Parent = tile
		text("label", string.upper(s.label or ""), T.type.caption, rgb(T.c.textDim), { Size = UDim2.new(1, 0, 0, 16), Parent = tile })
		text("numeric", tostring(s.value or ""), compact and T.type.h3 or T.type.h2, rgb(T.c.text), { Position = UDim2.fromOffset(0, 18), Size = UDim2.new(1, 0, 1, -18), Parent = tile })
	end
	local rewardsY = statsY + (compact and tileH + 10 or tileH * 2 + 28)
	local rewardRow = new("Frame", { Name = "Rewards", BackgroundTransparency = 1, Position = UDim2.fromOffset(0, rewardsY), Size = UDim2.new(1, 0, 0, compact and 70 or 100), Parent = canvas })
	list("Horizontal", 12, "Center").Parent = rewardRow
	for i, r in ipairs(rewards) do
		if i > 5 then
			break
		end
		local holder = new("Frame", { Name = "Reward" .. i, BackgroundTransparency = 1, Size = UDim2.fromOffset(compact and 64 or 88, compact and 70 or 100), LayoutOrder = i, Parent = rewardRow })
		iconTile(r.kind, r.rarity, compact and 52 or 72, { AnchorPoint = Vector2.new(0.5, 0), Position = UDim2.fromScale(0.5, 0), Parent = holder })
		text("numeric", r.amount and ("+" .. formatNumber(r.amount)) or (r.name or ""), T.type.caption, rgb(T.c.text), { AnchorPoint = Vector2.new(0, 1), Position = UDim2.fromScale(0, 1), Size = UDim2.new(1, 0, 0, 18), TextXAlignment = Enum.TextXAlignment.Center, Parent = holder })
	end
	local buttonsRow = new("Frame", { Name = "Actions", BackgroundTransparency = 1, AnchorPoint = Vector2.new(0, 1), Position = UDim2.fromScale(0, 1), Size = UDim2.new(1, 0, 0, compact and 46 or 56), Parent = canvas })
	list("Horizontal", 14, "Center", "Center").Parent = buttonsRow
	local first = nil
	for i, label in ipairs(DATA.actions or { "Play Again", "Lobby" }) do
		local b = button(label, i == 1 and "primary" or "secondary", UDim2.fromOffset(compact and 190 or 230, compact and 44 or 54))
		b.LayoutOrder = i
		b.Parent = buttonsRow
		first = first or b:FindFirstChild("Face")
	end
	openAnimation(canvas, uiScale)
	return first
end

SCREENS.loading = function(mode: string)
	local compact = mode == "compact"
	local bg = new("Frame", { Name = "Backdrop", BackgroundColor3 = rgb(T.c.vignette), Size = UDim2.new(1, 0, 1, 80), Position = UDim2.fromOffset(0, -60), BorderSizePixel = 0, Parent = root })
	new("UIGradient", { Color = ColorSequence.new(rgb(T.c.loadingTop), rgb(T.c.vignette)), Rotation = 90, Parent = bg })
	local w, h = compact and 800 or 1100, compact and 360 or 620
	local canvas = makeCanvas(bg, w, h, nil, UDim2.new(0.5, 0, 0.5, 20))
	text("display", DATA.title, compact and T.type.display * 0.9 or T.type.display * 1.2, rgb(T.c.text), {
		AnchorPoint = Vector2.new(0.5, 0.5),
		Position = UDim2.fromScale(0.5, 0.38),
		Size = UDim2.new(1, 0, 0, compact and 70 or 110),
		TextXAlignment = Enum.TextXAlignment.Center,
		Parent = canvas,
	})
	if DATA.subtitle then
		text("body", DATA.subtitle, T.type.body, rgb(T.c.textDim), { AnchorPoint = Vector2.new(0.5, 0), Position = UDim2.fromScale(0.5, 0.5), Size = UDim2.new(1, 0, 0, 22), TextXAlignment = Enum.TextXAlignment.Center, Parent = canvas })
	end
	local progress = bar(DATA.progress or 0.6, T.c.accent, 10, UDim.new(0, compact and 420 or 560))
	progress.AnchorPoint = Vector2.new(0.5, 1)
	progress.Position = UDim2.new(0.5, 0, 1, compact and -70 or -110)
	progress.Parent = canvas
	text("numeric", string.format("%d%%", math.floor((DATA.progress or 0.6) * 100)), T.type.label, rgb(T.c.text), {
		AnchorPoint = Vector2.new(0.5, 1),
		Position = UDim2.new(0.5, 0, 1, compact and -84 or -126),
		Size = UDim2.fromOffset(compact and 420 or 560, 22),
		TextXAlignment = Enum.TextXAlignment.Right,
		Parent = canvas,
	})
	local spinner = new("Frame", { Name = "Spinner", BackgroundTransparency = 1, AnchorPoint = Vector2.new(0.5, 0.5), Position = UDim2.new(0.5, compact and -232 or -302, 1, compact and -75 or -115), Size = UDim2.fromOffset(22, 22), Parent = canvas }, { corner(11), stroke(rgb(T.c.accent), 3, 0) })
	new("UIGradient", { Transparency = NumberSequence.new(0, 1), Parent = spinner:FindFirstChildWhichIsA("UIStroke") })
	TweenService:Create(spinner, TweenInfo.new(1, Enum.EasingStyle.Linear, Enum.EasingDirection.In, -1), { Rotation = 360 }):Play()
	if DATA.body then
		local tip = new("Frame", { Name = "Tip", BackgroundTransparency = 1, AnchorPoint = Vector2.new(0.5, 1), Position = UDim2.new(0.5, 0, 1, compact and -16 or -40), Size = UDim2.fromOffset(compact and 640 or 760, 28), Parent = canvas })
		list("Horizontal", 10, "Center", "Center").Parent = tip
		badge("Tip", rgb(T.c.accent), { LayoutOrder = 1, Parent = tip })
		text("body", DATA.body, T.type.body, rgb(T.c.textDim), { LayoutOrder = 2, AutomaticSize = Enum.AutomaticSize.X, Size = UDim2.fromOffset(0, 24), TextTruncate = Enum.TextTruncate.None, Parent = tip })
	end
	return nil
end

-- Build for the current mode; rebuild when the screen crosses the phone/desktop boundary.
local currentMode = nil
local function build()
	local mode = modeFor(root.AbsoluteSize)
	if mode == currentMode then
		return
	end
	currentMode = mode
	for _, child in ipairs(root:GetChildren()) do
		child:Destroy()
	end
	table.clear(buttons)
	local builder = SCREENS[DATA.screen] or SCREENS.menu
	local first = builder(mode)
	focusFirst(first)
end
build()
root:GetPropertyChangedSignal("AbsoluteSize"):Connect(build)
