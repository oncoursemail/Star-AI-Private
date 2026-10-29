--!strict
-- VfxStyles: style profiles for the STAR VFX composer. A profile is the whole art direction of an effect:
-- palette, shape language, texture set, timing curves, intensity and how much screen effect it may use.
-- The same ability (a list of cues) looks completely different under another profile.
-- Textures default to Roblox's built-in rbxasset:// particle textures; a project can swap in its own
-- uploaded rbxassetid:// images per profile (see Styles.withTextures).

export type Shape = "jagged" | "round" | "wispy" | "crisp" | "blocky"

export type Palette = {
	core: Color3, -- hottest centre
	glow: Color3, -- main body colour
	dark: Color3, -- shadow / contrast colour (cracks, smoke cores)
	accent: Color3, -- secondary sparks and rim
	flash: Color3, -- screen flash colour
}

export type Textures = {
	glow: string,
	spark: string,
	smoke: string,
	ring: string,
	crack: string,
	streak: string,
	swirl: string,
	flipbook: string?, -- optional 4x4 flipbook (Grid4x4, OneShot) used by smoke when set
}

export type Timing = {
	charge: number, -- seconds of anticipation
	impact: number, -- the hit frame window
	shockwave: number, -- expansion
	linger: number, -- held energy (vortex, pillar)
	dissipate: number, -- fade-out tail
	easeOut: Enum.EasingStyle, -- expansions
	easeIn: Enum.EasingStyle, -- fades
	stepped: boolean, -- pixel styles move in hard steps
}

export type Screen = {
	flash: number, -- 0..1 strength of the white/colour flash
	invert: boolean, -- one inverted frame on impact (anime style)
	tint: number, -- 0..1 colour-correction tint toward palette.glow during the effect
	bloom: number, -- extra bloom intensity during impact (0 = none)
	shake: number, -- camera shake amplitude in studs
	fovPunch: number, -- degrees of field-of-view punch on impact
}

export type Style = {
	name: string,
	label: string,
	palette: Palette,
	shape: Shape,
	textures: Textures,
	timing: Timing,
	intensity: number, -- 0.25..1.5, scales particle counts and sizes
	lightEmission: number, -- 0..1 for glowing layers
	material: Enum.Material, -- material of mesh layers (domes, pillars, debris glow)
	debrisMaterial: Enum.Material?,
	screen: Screen,
	sizeScale: number, -- overall size multiplier
}

local Styles = {}

local P = "rbxasset://textures/particles/"
local BUILTIN: Textures = {
	glow = "rbxasset://textures/glow.png",
	spark = P .. "sparkles_main.dds",
	smoke = P .. "smoke_main.dds",
	ring = P .. "explosion01_shockwave_main.dds",
	crack = P .. "explosion01_implosion_main.dds",
	streak = P .. "fire_sparks_main.dds",
	swirl = P .. "forcefield_vortex_main.dds",
}
Styles.BUILTIN_TEXTURES = BUILTIN

local function rgb(r: number, g: number, b: number): Color3
	return Color3.fromRGB(r, g, b)
end

local function textures(overrides: { [string]: string }?): Textures
	local t: Textures = table.clone(BUILTIN)
	if overrides then
		for key, value in overrides do
			(t :: any)[key] = value
		end
	end
	return t
end

-- Anime energy: saturated single hue, jagged shapes, one inverted flash frame, hard shake, fast impact, long linger.
Styles.anime_energy = {
	name = "anime_energy",
	label = "Anime energy",
	palette = {
		core = rgb(235, 255, 235),
		glow = rgb(40, 255, 90),
		dark = rgb(4, 30, 10),
		accent = rgb(170, 255, 120),
		flash = rgb(225, 255, 225),
	},
	shape = "jagged",
	textures = textures(nil),
	timing = {
		charge = 0.9,
		impact = 0.18,
		shockwave = 0.6,
		linger = 1.1,
		dissipate = 0.9,
		easeOut = Enum.EasingStyle.Quint,
		easeIn = Enum.EasingStyle.Quad,
		stepped = false,
	},
	intensity = 1.2,
	lightEmission = 1,
	material = Enum.Material.Neon,
	debrisMaterial = nil,
	screen = { flash = 0.85, invert = true, tint = 0.45, bloom = 1.4, shake = 1.1, fovPunch = 9 },
	sizeScale = 1.15,
} :: Style

-- Cartoon soft: pastel, round puffs, bouncy Back easing, no inversion, gentle shake, short linger.
Styles.cartoon_soft = {
	name = "cartoon_soft",
	label = "Stylized cartoon / soft",
	palette = {
		core = rgb(255, 255, 255),
		glow = rgb(255, 170, 215),
		dark = rgb(120, 90, 170),
		accent = rgb(140, 220, 255),
		flash = rgb(255, 245, 250),
	},
	shape = "round",
	textures = textures({ spark = "rbxasset://textures/whiteCircle.png", crack = "rbxasset://textures/whiteCircle.png",
		streak = "rbxasset://textures/whiteCircle.png" }),
	timing = {
		charge = 0.6,
		impact = 0.22,
		shockwave = 0.55,
		linger = 0.5,
		dissipate = 0.7,
		easeOut = Enum.EasingStyle.Back,
		easeIn = Enum.EasingStyle.Sine,
		stepped = false,
	},
	intensity = 0.8,
	lightEmission = 0.25,
	material = Enum.Material.SmoothPlastic,
	debrisMaterial = Enum.Material.SmoothPlastic,
	screen = { flash = 0.25, invert = false, tint = 0.15, bloom = 0, shake = 0.25, fovPunch = 3 },
	sizeScale = 1,
} :: Style

-- Realistic fire / smoke / magic: warm gradient, wispy smoke that stays dark, little screen effect, long dissipate.
Styles.realistic_fire = {
	name = "realistic_fire",
	label = "Realistic fire, smoke and magic",
	palette = {
		core = rgb(255, 236, 180),
		glow = rgb(255, 120, 30),
		dark = rgb(40, 34, 32),
		accent = rgb(255, 70, 20),
		flash = rgb(255, 210, 160),
	},
	shape = "wispy",
	textures = textures({ glow = P .. "fire_main.dds", crack = P .. "explosion01_core_main.dds",
		smoke = P .. "explosion01_smoke_main.dds" }),
	timing = {
		charge = 0.5,
		impact = 0.15,
		shockwave = 0.7,
		linger = 0.9,
		dissipate = 1.6,
		easeOut = Enum.EasingStyle.Quart,
		easeIn = Enum.EasingStyle.Sine,
		stepped = false,
	},
	intensity = 1,
	lightEmission = 0.7,
	material = Enum.Material.Neon,
	debrisMaterial = Enum.Material.Slate,
	screen = { flash = 0.35, invert = false, tint = 0.12, bloom = 0.4, shake = 0.7, fovPunch = 4 },
	sizeScale = 1,
} :: Style

-- Sci-fi neon tech: two-tone cyan/magenta, crisp thin geometry, ForceField shells, linear snappy timing.
Styles.scifi_neon = {
	name = "scifi_neon",
	label = "Sci-fi / neon tech",
	palette = {
		core = rgb(230, 255, 255),
		glow = rgb(0, 220, 255),
		dark = rgb(10, 10, 40),
		accent = rgb(255, 40, 200),
		flash = rgb(200, 250, 255),
	},
	shape = "crisp",
	textures = textures({ spark = "rbxasset://textures/particles/SquareParticle.png", glow = P .. "forcefield_glow_main.dds" }),
	timing = {
		charge = 0.7,
		impact = 0.12,
		shockwave = 0.45,
		linger = 0.9,
		dissipate = 0.5,
		easeOut = Enum.EasingStyle.Exponential,
		easeIn = Enum.EasingStyle.Linear,
		stepped = false,
	},
	intensity = 1,
	lightEmission = 1,
	material = Enum.Material.ForceField,
	debrisMaterial = Enum.Material.Metal,
	screen = { flash = 0.5, invert = false, tint = 0.3, bloom = 0.9, shake = 0.5, fovPunch = 5 },
	sizeScale = 1,
} :: Style

-- Pixel / retro: small fixed palette, square particles, no bloom, stepped motion, blocky debris.
Styles.pixel_retro = {
	name = "pixel_retro",
	label = "Pixel / retro",
	palette = {
		core = rgb(255, 255, 255),
		glow = rgb(255, 204, 0),
		dark = rgb(60, 30, 90),
		accent = rgb(255, 80, 80),
		flash = rgb(255, 255, 255),
	},
	shape = "blocky",
	textures = textures({ glow = "rbxasset://textures/particles/SquareParticle.png",
		spark = "rbxasset://textures/particles/SquareParticle.png", smoke = "rbxasset://textures/particles/SquareParticle.png",
		streak = "rbxasset://textures/particles/SquareParticle.png" }),
	timing = {
		charge = 0.6,
		impact = 0.2,
		shockwave = 0.6,
		linger = 0.6,
		dissipate = 0.6,
		easeOut = Enum.EasingStyle.Linear,
		easeIn = Enum.EasingStyle.Linear,
		stepped = true,
	},
	intensity = 0.9,
	lightEmission = 0,
	material = Enum.Material.SmoothPlastic,
	debrisMaterial = Enum.Material.SmoothPlastic,
	screen = { flash = 0.6, invert = false, tint = 0, bloom = 0, shake = 0.6, fovPunch = 0 },
	sizeScale = 1,
} :: Style

Styles.ORDER = { "anime_energy", "cartoon_soft", "realistic_fire", "scifi_neon", "pixel_retro" }

function Styles.get(name: string): Style
	local found = (Styles :: any)[name]
	if type(found) == "table" and type(found.palette) == "table" then
		return found :: Style
	end
	return Styles.anime_energy
end

-- A copy of a profile with another hue family: keeps shape, timing and screen rules, swaps the palette.
function Styles.recolor(style: Style, palette: Palette): Style
	local copy = table.clone(style)
	copy.palette = palette
	return copy
end

-- A copy of a profile with the project's own uploaded textures (rbxassetid://...).
function Styles.withTextures(style: Style, overrides: { [string]: string }): Style
	local copy = table.clone(style)
	local t: Textures = table.clone(style.textures)
	for key, value in overrides do
		if type(value) == "string" and (string.match(value, "^rbxassetid://%d+$") or string.match(value, "^rbxasset://")) then
			(t :: any)[key] = value
		end
	end
	copy.textures = t
	return copy
end

-- A profile adapted from a base: `fields` may carry a palette (Color3 values), intensity, sizeScale and screen
-- numbers. Anything missing or of the wrong type keeps the base value. Used by generated code.
function Styles.custom(baseName: string, name: string, fields: { [string]: any }): Style
	local base = Styles.get(baseName)
	local copy = table.clone(base)
	copy.name = name
	copy.label = name
	local palette = fields.palette
	if type(palette) == "table" then
		local merged: Palette = table.clone(base.palette)
		for _, key in { "core", "glow", "dark", "accent", "flash" } do
			if typeof(palette[key]) == "Color3" then
				(merged :: any)[key] = palette[key]
			end
		end
		copy.palette = merged
	end
	if type(fields.intensity) == "number" then
		copy.intensity = math.clamp(fields.intensity, 0.25, 1.5)
	end
	if type(fields.sizeScale) == "number" then
		copy.sizeScale = math.clamp(fields.sizeScale, 0.25, 3)
	end
	local timing = fields.timing
	if type(timing) == "table" then -- stage lengths from a design plan (anticipation, hit, follow-through)
		local t: Timing = table.clone(base.timing)
		for _, key in { "charge", "impact", "shockwave", "linger", "dissipate" } do
			if type(timing[key]) == "number" then
				(t :: any)[key] = math.clamp(timing[key], 0.02, 10)
			end
		end
		copy.timing = t
	end
	local screen = fields.screen
	if type(screen) == "table" then
		local s: Screen = table.clone(base.screen)
		if type(screen.flash) == "number" then s.flash = math.clamp(screen.flash, 0, 1) end
		if type(screen.tint) == "number" then s.tint = math.clamp(screen.tint, 0, 1) end
		if type(screen.bloom) == "number" then s.bloom = math.clamp(screen.bloom, 0, 3) end
		if type(screen.shake) == "number" then s.shake = math.clamp(screen.shake, 0, 3) end
		if type(screen.fovPunch) == "number" then s.fovPunch = math.clamp(screen.fovPunch, 0, 20) end
		if type(screen.invert) == "boolean" then s.invert = screen.invert end
		copy.screen = s
	end
	return copy
end

-- Stage start times (seconds from the start of the effect) for a profile.
function Styles.stageTimes(style: Style): { [string]: number }
	local t = style.timing
	local charge = 0
	local impact = charge + t.charge
	local shockwave = impact + t.impact
	local linger = shockwave + t.shockwave * 0.5
	local dissipate = linger + t.linger
	return { charge = charge, impact = impact, shockwave = shockwave, linger = linger, dissipate = dissipate,
		finish = dissipate + t.dissipate }
end

return Styles
