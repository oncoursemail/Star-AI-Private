--!strict
-- VfxComposer: plays an ability (a list of cues) in a style profile. A cue names a stage of the timeline
-- (charge -> impact -> shockwave -> linger -> dissipate), when inside that stage it fires (0..1 of the stage's
-- length in the style), which primitive it uses and its params. Stage lengths come from the style, so one
-- ability gets the style's rhythm: snappy anime, bouncy cartoon, slow realistic smoke, stepped pixel.
-- Budgets: at most MAX_ACTIVE effects per client, a particle budget per effect scaled by device quality,
-- distance culling, screen effects only near the effect. Everything an effect makes is under one Folder that is
-- destroyed at the end (Debris also removes each piece on its own timer).

local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local UserInputService = game:GetService("UserInputService")

local Styles = require(script.Parent:WaitForChild("VfxStyles"))
local Prim = require(script.Parent:WaitForChild("VfxPrimitives"))

export type Cue = { stage: string, at: number, fx: string, params: Prim.Params? }
export type Ability = { name: string, cues: { Cue } }
export type PlayOptions = {
	speed: number?, -- 1 = real time; 0.05..1 slow motion (lab capture)
	quality: number?, -- override device quality (0.25..1)
	caster: Model?,
	screen: boolean?, -- allow screen flash / tint / shake (default: when the camera is near)
	seed: number?,
	onStage: ((stage: string, effectTime: number) -> ())?,
}
export type Handle = { folder: Folder, length: number, cancel: () -> () }

local Composer = {}

Composer.STAGES = { "charge", "impact", "shockwave", "linger", "dissipate" }
Composer.MAX_ACTIVE = 4
Composer.PARTICLE_BUDGET = 700 -- per effect at quality 1
Composer.CULL_DISTANCE = 350 -- studs from the camera; farther effects are skipped
Composer.SCREEN_DISTANCE = 120 -- studs; screen effects only for players this close

local FX: { [string]: (Prim.Ctx, Prim.Params?) -> () } = {
	burst = Prim.burst,
	sparks = Prim.sparks,
	smoke = Prim.smoke,
	ring = Prim.ring,
	ringSegments = Prim.ringSegments,
	dome = Prim.dome,
	pillar = Prim.pillar,
	slashes = Prim.slashes,
	vortex = Prim.vortex,
	crack = Prim.crack,
	debris = Prim.debris,
	spikes = Prim.spikes,
	aura = Prim.aura,
	light = Prim.light,
	flash = Prim.flash,
	tint = Prim.tint,
	shake = Prim.shake,
	particles = Prim.particles,
	beam = Prim.beam,
	projectile = Prim.projectile,
	sweep = Prim.sweep,
}
Composer.FX = FX

local function cue(stage: string, at: number, fx: string, params: Prim.Params?): Cue
	return { stage = stage, at = at, fx = fx, params = params }
end

-- The built-in abilities. They name no colours or textures: the style decides the look.
Composer.ABILITIES = {
	energy_burst = {
		name = "energy_burst",
		cues = {
			cue("charge", 0, "aura", nil),
			cue("charge", 0.05, "tint", { dur = 4 }),
			cue("charge", 0.1, "ring", { radius = 7, dur = 0.9, y = 0.2, color = "core" }),
			cue("charge", 0.3, "burst", { count = 40, speed = 30, life = 0.5, size = 0.9, texture = "streak", color = "glow",
				orient = "velocity", y = 0.3, spread = 15, drag = 1 }),
			cue("charge", 0.2, "shake", { amplitude = 0.12, dur = 0.8, frequency = 30, fov = 0 }),
			cue("charge", 0.45, "burst", { count = 30, speed = 12, life = 0.6, size = 0.7, texture = "spark", color = "accent",
				gravity = -20, y = 0.5, spread = 40 }),
			cue("impact", 0, "flash", nil),
			cue("impact", 0, "light", { dur = 0.6, range = 50 }),
			cue("impact", 0, "crack", { radius = 16 }),
			cue("impact", 0, "debris", { count = 18 }),
			cue("impact", 0, "spikes", { count = 10 }),
			cue("impact", 0, "sparks", { count = 70 }),
			cue("impact", 0, "slashes", { count = 6 }),
			cue("impact", 0, "dome", { radius = 11 }),
			cue("impact", 0.1, "shake", { amplitude = 1, dur = 0.55 }),
			cue("shockwave", 0, "ring", { radius = 26 }),
			cue("shockwave", 0, "ringSegments", { radius = 22 }),
			cue("shockwave", 0.2, "smoke", { count = 16 }),
			cue("shockwave", 0.45, "ring", { radius = 38, color = "accent" }),
			cue("linger", 0, "vortex", { radius = 8 }),
			cue("linger", 0.15, "pillar", { height = 80, width = 8 }),
			cue("linger", 0.5, "sparks", { count = 30, speed = 40 }),
			cue("dissipate", 0, "burst", { count = 40, speed = 6, life = 1.4, size = 0.5, texture = "spark", color = "accent",
				gravity = -12, y = 2, spread = 180, drag = 1 }),
			cue("dissipate", 0.1, "smoke", { count = 10, life = 1.4 }),
		},
	} :: Ability,
	-- A small hit for weapons and projectiles: flash, sparks, one ring, a puff.
	impact_hit = {
		name = "impact_hit",
		cues = {
			cue("impact", 0, "flash", { strength = 0.4, invert = false }),
			cue("impact", 0, "sparks", { count = 25, speed = 50 }),
			cue("impact", 0, "light", { dur = 0.25, range = 20 }),
			cue("impact", 0, "shake", { amplitude = 0.35, dur = 0.25, fov = 0.3 }),
			cue("shockwave", 0, "ring", { radius = 7, y = 1.5 }),
			cue("shockwave", 0.2, "smoke", { count = 6, size = 2.5, life = 0.9 }),
		},
	} :: Ability,
}

local active = 0

-- Device budget: phones and low graphics settings get fewer particles, segments and chunks.
function Composer.deviceQuality(): number
	local quality = 1
	if UserInputService.TouchEnabled and not UserInputService.KeyboardEnabled then
		quality = 0.5
	end
	local ok, level = pcall(function(): number
		local settingsObject = UserSettings():GetService("UserGameSettings")
		return (settingsObject :: any).SavedQualityLevel.Value
	end)
	if ok and type(level) == "number" and level > 0 then -- 0 = automatic
		quality = math.min(quality, math.clamp(level / 10, 0.3, 1))
	end
	return quality
end

-- Is this ability well-formed? (Generated abilities are checked again here, at run time.)
function Composer.validate(ability: any): (boolean, string?)
	if type(ability) ~= "table" or type(ability.name) ~= "string" or type(ability.cues) ~= "table" then
		return false, "ability needs a name and a cues list"
	end
	if #ability.cues == 0 or #ability.cues > 64 then
		return false, "ability needs 1..64 cues"
	end
	for index, c in ability.cues do
		if type(c) ~= "table" or not table.find(Composer.STAGES, c.stage) then
			return false, "cue " .. tostring(index) .. ": unknown stage"
		end
		if type(c.at) ~= "number" or c.at < 0 or c.at > 1 then
			return false, "cue " .. tostring(index) .. ": 'at' must be 0..1 of the stage"
		end
		if type(c.fx) ~= "string" or FX[c.fx] == nil then
			return false, "cue " .. tostring(index) .. ": unknown effect " .. tostring(c.fx)
		end
		if c.params ~= nil and type(c.params) ~= "table" then
			return false, "cue " .. tostring(index) .. ": params must be a table"
		end
	end
	return true, nil
end

function Composer.length(style: Styles.Style): number
	return Styles.stageTimes(style).finish
end

local function stageLength(style: Styles.Style, stage: string): number
	local t = style.timing
	if stage == "charge" then
		return t.charge
	elseif stage == "impact" then
		return t.impact
	elseif stage == "shockwave" then
		return t.shockwave
	elseif stage == "linger" then
		return t.linger
	end
	return t.dissipate
end

function Composer.play(ability: Ability, style: Styles.Style, origin: CFrame, options: PlayOptions?): Handle?
	local ok, problem = Composer.validate(ability)
	if not ok then
		warn("[StarVfx] refused ability: " .. tostring(problem))
		return nil
	end
	local opts: PlayOptions = options or {}
	local camera = workspace.CurrentCamera
	local distance = if camera then (camera.CFrame.Position - origin.Position).Magnitude else 0
	if distance > Composer.CULL_DISTANCE or active >= Composer.MAX_ACTIVE then
		return nil
	end
	local quality = math.clamp(opts.quality or Composer.deviceQuality(), 0.25, 1)
	if active >= 2 then
		quality *= 0.6 -- several effects at once: each gets a smaller share
	end
	local speed = math.clamp(opts.speed or 1, 0.05, 1)
	local folder = Instance.new("Folder")
	folder.Name = "StarVfx_" .. ability.name
	local anchor = Instance.new("Part")
	anchor.Name = "Anchor"
	anchor.Anchored = true
	anchor.CanCollide = false
	anchor.CanQuery = false
	anchor.CanTouch = false
	anchor.Transparency = 1
	anchor.Size = Vector3.one * 0.2
	anchor.CFrame = origin
	anchor.Parent = folder
	folder.Parent = workspace

	local ctx: Prim.Ctx = {
		style = style,
		origin = origin,
		folder = folder,
		anchor = anchor,
		speed = speed,
		quality = quality,
		caster = opts.caster,
		screen = if opts.screen ~= nil then opts.screen else (RunService:IsClient() and distance <= Composer.SCREEN_DISTANCE),
		budget = { particles = math.floor(Composer.PARTICLE_BUDGET * quality) },
		random = Random.new(opts.seed or os.clock() * 1000),
		alive = true,
		connections = {},
		bound = {},
	}
	active += 1
	local times = Styles.stageTimes(style)
	local length = times.finish
	local onStage = opts.onStage
	if onStage then
		for _, stage in Composer.STAGES do
			task.delay(Prim.dur(ctx, times[stage]), function()
				if ctx.alive then
					onStage(stage, times[stage])
				end
			end)
		end
	end
	for _, c in ability.cues do
		local start = times[c.stage] + c.at * stageLength(style, c.stage)
		local run = FX[c.fx]
		task.delay(Prim.dur(ctx, start), function()
			if not ctx.alive then
				return
			end
			local fine, err = pcall(run, ctx, c.params)
			if not fine then
				warn("[StarVfx] " .. c.fx .. " failed: " .. tostring(err))
			end
		end)
	end

	local finished = false
	local function finish()
		if finished then
			return
		end
		finished = true
		ctx.alive = false
		active -= 1
		for _, connection in ctx.connections do
			connection:Disconnect()
		end
		for _, name in ctx.bound do
			RunService:UnbindFromRenderStep(name)
		end
		folder:Destroy()
		if onStage then
			onStage("done", length)
		end
	end
	task.delay(Prim.dur(ctx, length + 0.6), finish)
	return { folder = folder, length = length, cancel = finish }
end

-- The caster's character for a user id (or nil).
function Composer.characterOf(userId: number): Model?
	local player = Players:GetPlayerByUserId(userId)
	return if player then player.Character else nil
end

return Composer
