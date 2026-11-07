--!strict
--[[
Clean sample place for the X-ray Eyes exam: a small two-storey house (door, window, stairs up to a roof
terrace with railings, furniture, textures, a poster decal), a separate annex room, a spawn, and a HUD.
Built entirely in code on a 1-stud grid, so every planted defect is the only thing wrong with it.

`R` carries the constructors (Lune: require("@lune/roblox"); Studio: the globals), so the same file builds
the place headless or in a throwaway Studio place:
	R = { Instance, Vector3, CFrame, Color3, UDim2, UDim, Vector2, Enum }
]]

export type Meta = { parts: { [string]: any }, ui: { [string]: any }, house: any, annex: any, gui: any }

local Sample = {}

local function rgb(R: any, r: number, g: number, b: number): any
	return R.Color3.fromRGB(r, g, b)
end

-- An anchored block from its min and max corner.
local function box(R: any, parent: any, name: string, x0: number, y0: number, z0: number, x1: number, y1: number, z1: number,
	color: any, material: string?): any
	local p = R.Instance.new("Part")
	p.Name = name
	p.Anchored = true
	p.Size = R.Vector3.new(x1 - x0, y1 - y0, z1 - z0)
	p.CFrame = R.CFrame.new((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
	p.Color = color
	p.Material = R.Enum.Material[material or "SmoothPlastic"]
	p.TopSurface = R.Enum.SurfaceType.Smooth
	p.BottomSurface = R.Enum.SurfaceType.Smooth
	p.Parent = parent
	return p
end

local function texture(R: any, part: any, name: string, face: string, studs: number): any
	local t = R.Instance.new("Texture")
	t.Name = name
	t.Face = R.Enum.NormalId[face]
	t.StudsPerTileU = studs
	t.StudsPerTileV = studs
	t.Texture = "rbxassetid://6372755229"
	t.Parent = part
	return t
end

-- One house at (ox, oz). Returns its parts by name.
function Sample.house(R: any, parent: any, name: string, ox: number, oz: number, withSpawn: boolean): ({ [string]: any }, any, any)
	local m = R.Instance.new("Model")
	m.Name = name
	m.Parent = parent
	local parts: { [string]: any } = {}
	local wall, floorC, wood, glass = rgb(R, 214, 205, 188), rgb(R, 120, 86, 58), rgb(R, 150, 105, 70), rgb(R, 170, 210, 235)
	local function b(n: string, x0: number, y0: number, z0: number, x1: number, y1: number, z1: number, color: any, mat: string?, into: any?): any
		local p = box(R, into or m, n, ox + x0, y0, oz + z0, ox + x1, y1, oz + z1, color, mat)
		parts[n] = p
		return p
	end
	-- ground floor shell
	b("Floor", 0, 0, 0, 24, 1, 20, floorC, "WoodPlanks")
	b("WallS_L", 0, 1, 0, 10, 11, 1, wall)
	b("WallS_R", 15, 1, 0, 24, 11, 1, wall)
	b("WallS_Header", 10, 9, 0, 15, 11, 1, wall)
	b("WallN_L", 0, 1, 19, 9, 11, 20, wall)
	b("WallN_R", 15, 1, 19, 24, 11, 20, wall)
	b("WallN_Below", 9, 1, 19, 15, 4, 20, wall)
	b("WallN_Above", 9, 8, 19, 15, 11, 20, wall)
	local g = b("WindowGlass", 9, 4, 19, 15, 8, 20, glass, "Glass")
	g.Transparency = 0.6
	b("WallW", 0, 1, 1, 1, 11, 19, wall)
	b("WallE", 23, 1, 1, 24, 11, 19, wall)
	-- door with a welded knob
	local doorModel = R.Instance.new("Model")
	doorModel.Name = "Door"
	doorModel.Parent = m
	local door = b("Door", 10, 1, 0, 15, 9, 1, rgb(R, 110, 70, 45), "Wood", doorModel)
	local knob = b("DoorKnob", 13, 4.85, -0.3, 13.3, 5.15, 0, rgb(R, 200, 170, 60), "Metal", doorModel)
	local weld = R.Instance.new("WeldConstraint")
	weld.Part0 = knob
	weld.Part1 = door
	weld.Parent = knob
	parts.DoorModel = doorModel
	-- upper floor = roof terrace
	b("Floor2", 0, 11, 0, 24, 12, 20, floorC, "WoodPlanks")
	local rail = rgb(R, 60, 60, 66)
	b("RailingN", 0, 12, 19.7, 24, 15.5, 20, rail, "Metal")
	b("RailingS", 0, 12, 0, 24, 15.5, 0.3, rail, "Metal")
	b("RailingW", 0, 12, 0.3, 0.3, 15.5, 19.7, rail, "Metal")
	b("RailingE1", 23.7, 12, 0.3, 24, 15.5, 2, rail, "Metal")
	b("RailingE2", 23.7, 12, 4, 24, 15.5, 19.7, rail, "Metal")
	-- outside stairs, 12 risers of 1 stud, 1.5-stud treads, arriving at the gap in the east railing
	local stairs = R.Instance.new("Model")
	stairs.Name = "Stairs"
	stairs.Parent = m
	parts.Stairs = stairs
	for k = 1, 12 do
		local z0 = 2 + 1.5 * (12 - k)
		b("Step" .. k, 24, 0, z0, 28, k, z0 + 1.5, rgb(R, 150, 150, 150), "Concrete", stairs)
	end
	-- furniture
	b("TableTop", 4, 3.5, 5, 10, 4, 8, wood, "Wood")
	b("TableLeg1", 4, 1, 5, 4.5, 3.5, 5.5, wood, "Wood")
	b("TableLeg2", 9.5, 1, 5, 10, 3.5, 5.5, wood, "Wood")
	b("TableLeg3", 4, 1, 7.5, 4.5, 3.5, 8, wood, "Wood")
	b("TableLeg4", 9.5, 1, 7.5, 10, 3.5, 8, wood, "Wood")
	b("Book", 5, 4, 6, 6, 4.25, 7.5, rgb(R, 160, 40, 40))
	b("Mug", 8, 4, 6, 8.5, 4.5, 6.5, rgb(R, 240, 240, 240))
	b("Lamp", 6.5, 4, 5.5, 7.5, 5, 6.5, rgb(R, 250, 220, 120), "Neon")
	b("Crate1", 14, 1, 4, 16, 3, 6, rgb(R, 170, 130, 80), "Wood")
	b("Crate3", 14.5, 3, 4.5, 15.5, 4, 5.5, rgb(R, 150, 120, 80), "Wood")
	b("Crate2", 18, 1, 14, 20, 3, 16, rgb(R, 170, 130, 80), "Wood")
	b("Shelf", 1, 5.5, 8, 2, 6, 12, wood, "Wood")
	b("Vase", 1, 6, 9.5, 1.6, 7, 10.5, rgb(R, 70, 110, 160))
	local poster = b("Poster", 22.8, 4, 8, 23, 8, 12, rgb(R, 245, 245, 245))
	local decal = R.Instance.new("Decal")
	decal.Name = "PosterArt"
	decal.Face = R.Enum.NormalId.Left
	decal.Texture = "rbxassetid://6372755229"
	decal.Parent = poster
	parts.PosterArt = decal
	b("Rug", 12, 1, 10, 18, 1.1, 14, rgb(R, 140, 50, 60), "Fabric")
	b("Bench", 4, 12, 8, 8, 13, 9.5, wood, "Wood")
	b("PlantPot", 18, 12, 15, 19, 13.5, 16, rgb(R, 90, 140, 70))
	b("Chimney", 2, 12, 2, 4, 16, 4, rgb(R, 120, 70, 60), "Brick")
	local goal = b("Goal", 20, 12, 10, 21, 13, 11, rgb(R, 255, 200, 0), "Neon")
	goal:SetAttribute("XrayKeyPoint", true)
	parts.FloorTex = texture(R, parts.Floor, "FloorTex", "Top", 4)
	parts.Floor2Tex = texture(R, parts.Floor2, "Floor2Tex", "Top", 4)
	parts.WallWTex = texture(R, parts.WallW, "WallWTex", "Right", 5)
	-- annex: a closed room with its own floor and roof (ceiling clearance 9)
	local annex = R.Instance.new("Model")
	annex.Name = "Annex"
	annex.Parent = m
	parts.Annex = annex
	parts.AnnexFloor = box(R, annex, "Floor", ox - 14, 0, oz, ox - 2, 1, oz + 12, floorC, "WoodPlanks")
	b("AnnexWallS", -14, 1, 0, -2, 10, 1, wall, nil, annex)
	b("AnnexWallN", -14, 1, 11, -2, 10, 12, wall, nil, annex)
	b("AnnexWallW", -14, 1, 1, -13, 10, 11, wall, nil, annex)
	b("AnnexWallE", -3, 1, 1, -2, 10, 11, wall, nil, annex)
	b("Roof", -14, 10, 0, -2, 11, 12, rgb(R, 90, 60, 50), "Slate", annex)
	if withSpawn then
		local s = R.Instance.new("SpawnLocation")
		s.Name = "SpawnLocation"
		s.Anchored = true
		s.Size = R.Vector3.new(6, 1, 6)
		s.CFrame = R.CFrame.new(ox + 12, 0.5, oz - 6)
		s.Parent = m
		parts.SpawnLocation = s
	end
	return parts, m, annex
end

local function label(R: any, class: string, parent: any, name: string, props: { [string]: any }): any
	local t = R.Instance.new(class)
	t.Name = name
	for k, v in props do
		t[k] = v
	end
	t.Parent = parent
	return t
end

-- HUD: every element fits on a 844x390 phone, text contrast >= 4.5:1, touch targets >= 48 px.
function Sample.hud(R: any, starterGui: any): ({ [string]: any }, any)
	local ui: { [string]: any } = {}
	local white = rgb(R, 255, 255, 255)
	local sg = R.Instance.new("ScreenGui")
	sg.Name = "HUD"
	sg.Parent = starterGui
	local function u2(a: number, b: number, c: number, d: number): any
		return R.UDim2.new(a, b, c, d)
	end
	local top = label(R, "Frame", sg, "TopBar", {
		AnchorPoint = R.Vector2.new(0.5, 0),
		Position = u2(0.5, 0, 0, 8),
		Size = u2(0.6, 0, 0, 48),
		BackgroundColor3 = rgb(R, 25, 27, 36),
		BackgroundTransparency = 0,
	})
	ui.TopBar = top
	ui.Title = label(R, "TextLabel", top, "Title", {
		Position = u2(0, 12, 0, 0),
		Size = u2(0.5, -12, 1, 0),
		Text = "STAR Village",
		TextSize = 24,
		TextColor3 = white,
		BackgroundTransparency = 1,
	})
	ui.Coins = label(R, "TextLabel", top, "Coins", {
		Position = u2(0.5, 0, 0, 0),
		Size = u2(0.5, -12, 1, 0),
		Text = "Coins: 120",
		TextSize = 20,
		TextColor3 = rgb(R, 255, 215, 90),
		BackgroundTransparency = 1,
	})
	local shop = label(R, "Frame", sg, "ShopPanel", {
		AnchorPoint = R.Vector2.new(1, 0.5),
		Position = u2(1, -16, 0.5, 0),
		Size = u2(0, 240, 0, 232),
		BackgroundColor3 = rgb(R, 35, 38, 50),
		BackgroundTransparency = 0,
	})
	ui.ShopPanel = shop
	local pad = R.Instance.new("UIPadding")
	for _, side in { "PaddingLeft", "PaddingRight", "PaddingTop", "PaddingBottom" } do
		pad[side] = R.UDim.new(0, 8)
	end
	pad.Parent = shop
	local list = R.Instance.new("UIListLayout")
	list.FillDirection = R.Enum.FillDirection.Vertical
	list.SortOrder = R.Enum.SortOrder.LayoutOrder
	list.Padding = R.UDim.new(0, 8)
	list.Parent = shop
	ui.ShopTitle = label(R, "TextLabel", shop, "ShopTitle", {
		LayoutOrder = 0,
		Size = u2(1, 0, 0, 32),
		Text = "Shop",
		TextSize = 22,
		TextColor3 = white,
		BackgroundTransparency = 1,
	})
	for i, spec in { { "BuySword", "Sword - 50", { 40, 110, 200 } }, { "BuyShield", "Shield - 80", { 30, 110, 70 } }, { "BuyPotion", "Potion - 20", { 130, 60, 170 } } } do
		ui[spec[1]] = label(R, "TextButton", shop, spec[1], {
			LayoutOrder = i,
			Size = u2(1, 0, 0, 52),
			Text = spec[2],
			TextSize = 20,
			TextColor3 = white,
			BackgroundColor3 = rgb(R, spec[3][1], spec[3][2], spec[3][3]),
			BackgroundTransparency = 0,
		})
	end
	ui.ActionButton = label(R, "TextButton", sg, "ActionButton", {
		AnchorPoint = R.Vector2.new(0.5, 1),
		Position = u2(0.5, 0, 1, -16),
		Size = u2(0, 180, 0, 56),
		Text = "Jump",
		TextSize = 24,
		TextColor3 = white,
		BackgroundColor3 = rgb(R, 200, 60, 60),
		BackgroundTransparency = 0,
	})
	ui.Toast = label(R, "TextLabel", sg, "Toast", {
		AnchorPoint = R.Vector2.new(0, 1),
		Position = u2(0, 16, 1, -16),
		Size = u2(0, 300, 0, 64),
		Text = "Welcome to STAR Village! Visit the shop to buy gear.",
		TextWrapped = true,
		TextSize = 18,
		TextColor3 = white,
		BackgroundColor3 = rgb(R, 20, 20, 28),
		BackgroundTransparency = 0.1,
	})
	ui.SettingsButton = label(R, "TextButton", sg, "SettingsButton", {
		Position = u2(0, 16, 0, 8),
		Size = u2(0, 48, 0, 48),
		Text = "S",
		TextSize = 24,
		TextColor3 = white,
		BackgroundColor3 = rgb(R, 60, 64, 80),
		BackgroundTransparency = 0,
	})
	return ui, sg
end

-- A whole place: baseplate, `houses` houses on a square grid (48-stud spacing), the HUD.
function Sample.build(game: any, R: any, houses: number?): Meta
	local n = houses or 1
	local ws = game:GetService("Workspace")
	local side = math.ceil(math.sqrt(n))
	local extent = math.max(256, side * 48 + 64)
	local base = box(R, ws, "Baseplate", -extent / 2, -2, -extent / 2, extent / 2, 0, extent / 2, rgb(R, 91, 154, 76), "Grass")
	local first: { [string]: any } = {}
	local firstModel, firstAnnex = nil, nil
	for i = 1, n do
		local col, row = (i - 1) % side, (i - 1) // side
		local ox, oz = -side * 24 + col * 48 + 16, -side * 24 + row * 48 + 12
		local parts, model, annex = Sample.house(R, ws, "House_" .. i, ox, oz, i == 1)
		if i == 1 then
			first, firstModel, firstAnnex = parts, model, annex
		end
	end
	first.Baseplate = base
	local ui, gui = Sample.hud(R, game:GetService("StarterGui"))
	return { parts = first, ui = ui, house = firstModel, annex = firstAnnex, gui = gui }
end

return Sample
