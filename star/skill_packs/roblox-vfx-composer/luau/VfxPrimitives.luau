--!strict
-- VfxPrimitives: the building blocks the composer schedules. Client-side only (they make local parts,
-- emitters, beams, trails, highlights, screen effects and camera motion). Every primitive:
--   * reads its look from ctx.style (palette, shape language, textures, timing, intensity),
--   * scales counts by ctx.quality and the effect's particle budget,
--   * plays at ctx.speed (1 = real time; lower = slow motion for frame capture: tweens, waits and
--     ParticleEmitter.TimeScale all follow it),
--   * cleans up after itself with Debris (and the composer destroys ctx.folder at the end as a backstop).
-- Params are plain tables so the composer can be data-driven; unknown or wrong-typed values fall back to defaults.

local Debris = game:GetService("Debris")
local Lighting = game:GetService("Lighting")
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local TweenService = game:GetService("TweenService")

local Styles = require(script.Parent:WaitForChild("VfxStyles"))

export type Params = { [string]: any }

export type Ctx = {
	style: Styles.Style,
	origin: CFrame, -- ground point of the effect, Y axis up
	folder: Folder, -- every instance of this effect lives under it
	anchor: BasePart, -- invisible anchored part at origin (hosts attachments)
	speed: number, -- playback speed (0.05..1)
	quality: number, -- device budget 0.25..1
	caster: Model?,
	screen: boolean, -- may this client get screen effects (near enough, local)?
	budget: { particles: number },
	random: Random,
	alive: boolean,
	connections: { RBXScriptConnection },
	bound: { string },
}

local Prim = {}

-- ------------------------------------------------------------------ helpers

local function num(p: Params?, key: string, default: number): number
	local v = p and p[key]
	if type(v) == "number" and v == v then
		return v
	end
	return default
end

local function bool(p: Params?, key: string, default: boolean): boolean
	local v = p and p[key]
	if type(v) == "boolean" then
		return v
	end
	return default
end

local function color(ctx: Ctx, p: Params?, key: string, default: string): Color3
	local v = p and p[key]
	if typeof(v) == "Color3" then
		return v
	end
	local name = if type(v) == "string" then v else default
	local found = (ctx.style.palette :: any)[name]
	if typeof(found) == "Color3" then
		return found
	end
	return ctx.style.palette.glow
end

local function texture(ctx: Ctx, p: Params?, default: string): string
	local v = p and p.texture
	local name = if type(v) == "string" then v else default
	local found = (ctx.style.textures :: any)[name]
	if type(found) == "string" then
		return found
	end
	return ctx.style.textures.glow
end

-- Seconds of effect time -> seconds of wall time at this playback speed.
function Prim.dur(ctx: Ctx, seconds: number): number
	return math.max(seconds, 0) / ctx.speed
end

-- Take up to `wanted` particles from the effect's budget, scaled by intensity and device quality.
function Prim.take(ctx: Ctx, wanted: number): number
	local n = math.floor(wanted * ctx.style.intensity * ctx.quality + 0.5)
	n = math.clamp(n, 0, ctx.budget.particles)
	ctx.budget.particles -= n
	return n
end

function Prim.cleanup(ctx: Ctx, instance: Instance, seconds: number)
	Debris:AddItem(instance, Prim.dur(ctx, seconds) + 0.25)
end

local function lerpValue(a: any, b: any, t: number): any
	local kind = typeof(a)
	if kind == "number" then
		return a + (b - a) * t
	elseif kind == "Vector3" or kind == "CFrame" or kind == "Color3" then
		return a:Lerp(b, t)
	end
	return if t >= 1 then b else a
end

-- Tween with the style's easing; pixel styles move in hard steps instead of smooth curves.
function Prim.tween(ctx: Ctx, instance: Instance, seconds: number, goal: { [string]: any }, easing: Enum.EasingStyle?,
	direction: Enum.EasingDirection?)
	local wall = Prim.dur(ctx, seconds)
	if ctx.style.timing.stepped then
		local steps = math.max(2, math.floor(seconds / 0.08))
		local start: { [string]: any } = {}
		for key in goal do
			start[key] = (instance :: any)[key]
		end
		for i = 1, steps do
			task.delay(wall * i / steps, function()
				if instance.Parent == nil then
					return
				end
				for key, target in goal do
					(instance :: any)[key] = lerpValue(start[key], target, i / steps)
				end
			end)
		end
		return
	end
	local info = TweenInfo.new(wall, easing or ctx.style.timing.easeOut, direction or Enum.EasingDirection.Out)
	TweenService:Create(instance, info, goal):Play()
end

local function part(ctx: Ctx, shape: Enum.PartType?, size: Vector3, cf: CFrame, col: Color3, material: Enum.Material?): Part
	local p = Instance.new("Part")
	p.Anchored = true
	p.CanCollide = false
	p.CanQuery = false
	p.CanTouch = false
	p.CastShadow = false
	p.Shape = shape or Enum.PartType.Block
	p.Size = size
	p.CFrame = cf
	p.Color = col
	p.Material = material or ctx.style.material
	p.TopSurface = Enum.SurfaceType.Smooth
	p.BottomSurface = Enum.SurfaceType.Smooth
	p.Parent = ctx.folder
	return p
end

local function attachment(ctx: Ctx, offset: Vector3): Attachment
	local a = Instance.new("Attachment")
	a.Position = offset
	a.Parent = ctx.anchor
	return a
end

local function seq(...: number): NumberSequence
	local values = { ... }
	local points = {}
	for i = 1, #values, 2 do
		table.insert(points, NumberSequenceKeypoint.new(values[i], values[i + 1]))
	end
	return NumberSequence.new(points)
end
Prim.seq = seq

local function emitter(ctx: Ctx, parent: Instance, tex: string, col: Color3): ParticleEmitter
	local e = Instance.new("ParticleEmitter")
	e.Enabled = false
	e.Rate = 0
	e.Texture = tex
	e.Color = ColorSequence.new(col)
	e.LightEmission = ctx.style.lightEmission
	e.LightInfluence = 0
	e.TimeScale = math.clamp(ctx.speed, 0, 1)
	e.Parent = parent
	return e
end

-- ------------------------------------------------------------------ particles

-- One-shot particle burst. Params: count, speed, spread, size, life, texture, color (palette key or Color3),
-- y (height), drag, gravity, orient ("camera" | "velocity" | "flat"), inward (sphere shell moving in), radius.
function Prim.burst(ctx: Ctx, p: Params?)
	local n = Prim.take(ctx, num(p, "count", 30))
	if n <= 0 then
		return
	end
	local scale = ctx.style.sizeScale
	local col = color(ctx, p, "color", "glow")
	local tex = texture(ctx, p, "spark")
	local life = num(p, "life", 0.6)
	local host: Instance
	local inward = bool(p, "inward", false)
	if inward then
		local radius = num(p, "radius", 8) * scale
		local shell = part(ctx, Enum.PartType.Ball, Vector3.one * radius * 2, ctx.origin * CFrame.new(0, num(p, "y", 3), 0),
			col, Enum.Material.SmoothPlastic)
		shell.Transparency = 1
		host = shell
		Prim.cleanup(ctx, shell, life + 0.5)
	else
		local a = attachment(ctx, Vector3.new(0, num(p, "y", 1), 0))
		host = a
		Prim.cleanup(ctx, a, life + 0.5)
	end
	local e = emitter(ctx, host, tex, col)
	if inward then
		e.Shape = Enum.ParticleEmitterShape.Sphere
		e.ShapeStyle = Enum.ParticleEmitterShapeStyle.Surface
		e.ShapeInOut = Enum.ParticleEmitterShapeInOut.Inward
	end
	local size = num(p, "size", 1) * scale
	local speed = num(p, "speed", 25) * scale
	e.Speed = NumberRange.new(speed * 0.5, speed)
	e.Lifetime = NumberRange.new(life * 0.6, life)
	local spread = num(p, "spread", 180)
	e.SpreadAngle = Vector2.new(spread, spread)
	e.Drag = num(p, "drag", 3)
	e.Acceleration = Vector3.new(0, -num(p, "gravity", 0), 0)
	e.Rotation = NumberRange.new(0, 360)
	e.RotSpeed = NumberRange.new(-num(p, "spin", 90), num(p, "spin", 90))
	local shape = ctx.style.shape
	local orient = if type(p) == "table" and type(p.orient) == "string" then p.orient else
		(if shape == "jagged" or shape == "crisp" then "velocity" else "camera")
	if orient == "velocity" and shape ~= "blocky" and shape ~= "round" then
		e.Orientation = Enum.ParticleOrientation.VelocityParallel
		e.Size = seq(0, size * 0.6, 0.3, size, 1, 0)
		e.Squash = seq(0, -1.5, 1, -0.5) -- stretched streaks
	elseif orient == "flat" then
		e.Orientation = Enum.ParticleOrientation.VelocityPerpendicular
		e.Size = seq(0, size * 0.3, 1, size)
	else
		if shape == "round" then
			e.Size = seq(0, size * 0.4, 0.25, size, 1, size * 0.2)
		elseif shape == "wispy" then
			e.Size = seq(0, size * 0.3, 1, size * 2.2)
		else
			e.Size = seq(0, size, 1, 0)
		end
	end
	e.Transparency = if shape == "wispy" then seq(0, 0.35, 0.6, 0.6, 1, 1) else seq(0, 0, 0.7, 0.2, 1, 1)
	if shape == "blocky" then
		e.Rotation = NumberRange.new(0, 0)
		e.RotSpeed = NumberRange.new(0, 0)
	end
	if type(p) == "table" and p.lightEmission ~= nil then
		e.LightEmission = num(p, "lightEmission", ctx.style.lightEmission)
	end
	if type(p) == "table" and p.lit == true then
		e.LightInfluence = 1
	end
	local book = ctx.style.textures.flipbook
	if type(p) == "table" and p.flipbook == true and book then
		e.Texture = book -- 4x4 frames that play once over each particle's life
		e.FlipbookLayout = Enum.ParticleFlipbookLayout.Grid4x4
		e.FlipbookMode = Enum.ParticleFlipbookMode.OneShot
	end
	e:Emit(n)
end

-- Sparks: fast thin streaks that fall (palette accent). Params: count, speed, life.
function Prim.sparks(ctx: Ctx, p: Params?)
	Prim.burst(ctx, {
		count = num(p, "count", 40),
		speed = num(p, "speed", 70),
		life = num(p, "life", 0.5),
		size = num(p, "size", 0.6),
		drag = 4,
		gravity = 60,
		texture = "streak",
		color = if type(p) == "table" and p.color ~= nil then p.color else "accent",
		orient = if ctx.style.shape == "blocky" then "camera" else "velocity",
		y = num(p, "y", 1.5),
		spread = 80,
	})
end

-- Smoke / dust: slow, growing, low-glow puffs along the ground. Params: count, radius, life.
function Prim.smoke(ctx: Ctx, p: Params?)
	local blocky = ctx.style.shape == "blocky"
	Prim.burst(ctx, {
		count = num(p, "count", 18) * (if blocky then 0.6 else 1),
		speed = num(p, "speed", 18) * (if blocky then 1.6 else 1),
		life = num(p, "life", 1.6) * (if blocky then 0.6 else 1),
		size = num(p, "size", 5) * (if blocky then 0.35 else 1),
		drag = 2.5,
		gravity = -2,
		texture = "smoke",
		-- realistic smoke is a lit grey-brown, not the palette's near-black shadow colour
		color = if type(p) == "table" and p.color ~= nil then p.color
			elseif ctx.style.shape == "wispy" then ctx.style.palette.dark:Lerp(Color3.fromRGB(125, 118, 110), 0.55)
			else "dark",
		orient = "camera",
		y = 1,
		spread = 100,
		lightEmission = 0,
		lit = ctx.style.shape == "wispy",
		spin = 30,
		flipbook = not blocky,
	})
end

-- ------------------------------------------------------------------ shockwaves

-- Flat expanding ring on the ground: one particle laid flat (VelocityPerpendicular) growing from 0 to the radius.
function Prim.ring(ctx: Ctx, p: Params?)
	if Prim.take(ctx, 1) <= 0 then
		return
	end
	local radius = num(p, "radius", 22) * ctx.style.sizeScale
	local life = num(p, "dur", ctx.style.timing.shockwave)
	local a = attachment(ctx, Vector3.new(0, num(p, "y", 0.3), 0))
	local e = emitter(ctx, a, texture(ctx, p, "ring"), color(ctx, p, "color", "glow"))
	e.Orientation = Enum.ParticleOrientation.VelocityPerpendicular
	e.EmissionDirection = Enum.NormalId.Top
	e.Speed = NumberRange.new(0.01)
	e.Lifetime = NumberRange.new(life)
	e.Rotation = NumberRange.new(0, 360)
	e.Size = if ctx.style.timing.stepped then seq(0, 2, 0.33, 2, 0.34, radius * 0.6, 0.66, radius * 0.6, 0.67, radius * 2, 1, radius * 2)
		else seq(0, 1, 0.25, radius * 1.3, 1, radius * 2)
	e.Transparency = seq(0, 0, 0.5, 0.25, 1, 1)
	e:Emit(1)
	Prim.cleanup(ctx, a, life + 0.3)
end

-- Ring of solid segments flying outward (reads as a mesh shockwave; jagged styles tilt them into shards).
-- Params: radius, segments, thickness, height, dur, tilt.
function Prim.ringSegments(ctx: Ctx, p: Params?)
	local segments = math.clamp(math.floor(num(p, "segments", 16) * (0.5 + 0.5 * ctx.quality)), 6, 32)
	local radius = num(p, "radius", 18) * ctx.style.sizeScale
	local life = num(p, "dur", ctx.style.timing.shockwave)
	local height = num(p, "height", 1.2) * ctx.style.sizeScale
	local thick = num(p, "thickness", 0.6)
	local tilt = math.rad(num(p, "tilt", if ctx.style.shape == "jagged" then 35 else 0))
	local col = color(ctx, p, "color", "glow")
	local start = 1.5
	for i = 1, segments do
		local angle = (i / segments) * math.pi * 2
		local r = ctx.random:NextNumber(-1, 1)
		local function at(rad: number): CFrame
			return ctx.origin * CFrame.Angles(0, angle, 0) * CFrame.new(0, height * 0.5, -rad) * CFrame.Angles(tilt * r, 0, tilt * 0.5 * r)
		end
		local arc = 2 * math.pi * start / segments
		local seg = part(ctx, Enum.PartType.Block, Vector3.new(arc, height, thick), at(start), col)
		seg.Transparency = 0.05
		local arcEnd = 2 * math.pi * radius / segments * 1.05
		Prim.tween(ctx, seg, life, { CFrame = at(radius), Size = Vector3.new(arcEnd, height * 0.25, thick * 0.4) })
		Prim.tween(ctx, seg, life, { Transparency = 1 }, ctx.style.timing.easeIn, Enum.EasingDirection.In)
		Prim.cleanup(ctx, seg, life + 0.1)
	end
end

-- Expanding shell (Ball part in the style's material: Neon, ForceField, SmoothPlastic). Params: radius, dur, from.
function Prim.dome(ctx: Ctx, p: Params?)
	local radius = num(p, "radius", 12) * ctx.style.sizeScale
	local life = num(p, "dur", ctx.style.timing.shockwave)
	local col = color(ctx, p, "color", "glow")
	local ball = part(ctx, Enum.PartType.Ball, Vector3.one * num(p, "from", 2), ctx.origin * CFrame.new(0, num(p, "y", 2), 0), col)
	-- An opaque Neon ball hides every other layer at the impact; a ForceField shell glows at its rim and lets the
	-- crack, debris and sparks read through it. Soft (SmoothPlastic) styles keep their solid, half-transparent puff.
	if ball.Material == Enum.Material.Neon then
		ball.Material = Enum.Material.ForceField
	end
	ball.Transparency = num(p, "alpha", if ball.Material == Enum.Material.ForceField then 0 else 0.35)
	Prim.tween(ctx, ball, life, { Size = Vector3.one * radius * 2 })
	Prim.tween(ctx, ball, life, { Transparency = 1 }, ctx.style.timing.easeIn, Enum.EasingDirection.In)
	Prim.cleanup(ctx, ball, life + 0.1)
end

-- ------------------------------------------------------------------ beams, slashes, vortex

-- Vertical pillar: two scrolling beams (core + glow) between ground and sky plus a solid core that thins out.
-- Params: height, width, dur.
function Prim.pillar(ctx: Ctx, p: Params?)
	local height = num(p, "height", 60) * ctx.style.sizeScale
	local width = num(p, "width", 6) * ctx.style.sizeScale
	local life = num(p, "dur", ctx.style.timing.linger)
	local bottom = attachment(ctx, Vector3.new(0, 0, 0))
	local top = attachment(ctx, Vector3.new(0, height, 0))
	local beams: { Beam } = {}
	for layer = 1, 2 do
		local b = Instance.new("Beam")
		b.Attachment0 = bottom
		b.Attachment1 = top
		b.FaceCamera = true
		b.Segments = 1
		b.Texture = texture(ctx, nil, if layer == 1 then "streak" else "glow")
		b.TextureMode = Enum.TextureMode.Wrap
		b.TextureLength = height / 3
		b.TextureSpeed = (if layer == 1 then 2.5 else -1.2) * ctx.speed
		b.LightEmission = ctx.style.lightEmission
		b.LightInfluence = 0
		b.Color = ColorSequence.new(if layer == 1 then ctx.style.palette.core else ctx.style.palette.glow)
		b.Transparency = NumberSequence.new(if layer == 1 then 0 else 0.3)
		b.Width0 = 0.2
		b.Width1 = 0.2
		b.Parent = ctx.anchor
		table.insert(beams, b)
	end
	local grow = math.min(0.15, life * 0.2)
	Prim.tween(ctx, beams[1], grow, { Width0 = width * 0.8, Width1 = width * 0.6 })
	Prim.tween(ctx, beams[2], grow, { Width0 = width * 2.2, Width1 = width * 1.6 })
	local sleeve = part(ctx, Enum.PartType.Cylinder, Vector3.new(height, 0.5, 0.5),
		ctx.origin * CFrame.new(0, height * 0.5, 0) * CFrame.Angles(0, 0, math.rad(90)), ctx.style.palette.glow)
	sleeve.Transparency = 0.55
	Prim.tween(ctx, sleeve, grow * 1.5, { Size = Vector3.new(height, width * 1.3, width * 1.3) })
	task.delay(Prim.dur(ctx, life * 0.5), function()
		if sleeve.Parent then
			Prim.tween(ctx, sleeve, life * 0.5, { Size = Vector3.new(height, 0.1, 0.1), Transparency = 1 }, ctx.style.timing.easeIn,
				Enum.EasingDirection.In)
		end
	end)
	Prim.cleanup(ctx, sleeve, life + 0.2)
	local core = part(ctx, Enum.PartType.Cylinder, Vector3.new(height, 0.5, 0.5),
		ctx.origin * CFrame.new(0, height * 0.5, 0) * CFrame.Angles(0, 0, math.rad(90)), ctx.style.palette.core)
	core.Transparency = 0.1
	Prim.tween(ctx, core, grow, { Size = Vector3.new(height, width * 0.5, width * 0.5) })
	task.delay(Prim.dur(ctx, life * 0.6), function()
		if not ctx.alive then
			return
		end
		for _, b in beams do
			Prim.tween(ctx, b, life * 0.4, { Width0 = 0, Width1 = 0 }, ctx.style.timing.easeIn, Enum.EasingDirection.In)
		end
		Prim.tween(ctx, core, life * 0.4, { Size = Vector3.new(height, 0.05, 0.05), Transparency = 1 },
			ctx.style.timing.easeIn, Enum.EasingDirection.In)
	end)
	for _, inst: Instance in { bottom :: Instance, top, beams[1], beams[2], core } do
		Prim.cleanup(ctx, inst, life + 0.2)
	end
end

-- Slash streaks: thin wedges flashing across the centre at random angles. Params: count, length, dur, y.
function Prim.slashes(ctx: Ctx, p: Params?)
	local count = math.max(1, math.floor(num(p, "count", 5) * ctx.quality + 0.5))
	local length = num(p, "length", 26) * ctx.style.sizeScale
	local life = num(p, "dur", 0.25)
	for i = 1, count do
		local delay = (i - 1) * num(p, "gap", 0.03)
		task.delay(Prim.dur(ctx, delay), function()
			if not ctx.alive then
				return
			end
			local yaw = ctx.random:NextNumber(0, math.pi * 2)
			local roll = ctx.random:NextNumber(-0.5, 0.5)
			local cf = ctx.origin * CFrame.new(0, num(p, "y", 3), 0) * CFrame.Angles(0, yaw, roll)
			local s = part(ctx, Enum.PartType.Block, Vector3.new(0.35, 0.35, length * 0.2), cf, if i % 2 == 0 then ctx.style.palette.core
				else ctx.style.palette.glow)
			if ctx.style.shape == "round" then
				s.Shape = Enum.PartType.Cylinder
				s.Size = Vector3.new(length * 0.2, 0.6, 0.6)
				s.CFrame = cf * CFrame.Angles(0, math.rad(90), 0)
				Prim.tween(ctx, s, life, { Size = Vector3.new(length, 0.2, 0.2) })
			else
				Prim.tween(ctx, s, life, { Size = Vector3.new(0.35, if ctx.style.shape == "jagged" then 1.6 else 0.5, length) })
			end
			Prim.tween(ctx, s, life, { Transparency = 1 }, ctx.style.timing.easeIn, Enum.EasingDirection.In)
			Prim.cleanup(ctx, s, life + 0.1)
		end)
	end
end

-- Swirling vortex sphere: a held shell plus trail arms spinning and spiralling in. Params: radius, arms, dur, spin.
function Prim.vortex(ctx: Ctx, p: Params?)
	local radius = num(p, "radius", 9) * ctx.style.sizeScale
	local life = num(p, "dur", ctx.style.timing.linger)
	local arms = math.clamp(math.floor(num(p, "arms", 6) * (0.5 + 0.5 * ctx.quality)), 2, 10)
	local centre = ctx.origin * CFrame.new(0, num(p, "y", radius * 0.8), 0)
	local shell = part(ctx, Enum.PartType.Ball, Vector3.one * radius * 1.2, centre, ctx.style.palette.glow)
	shell.Transparency = if ctx.style.material == Enum.Material.ForceField then 0 else 0.55
	if ctx.style.material ~= Enum.Material.ForceField and ctx.style.shape ~= "blocky" then
		shell.Material = Enum.Material.ForceField
		shell.Transparency = 0
	end
	Prim.tween(ctx, shell, life * 0.3, { Size = Vector3.one * radius * 2 })
	local spinner = part(ctx, Enum.PartType.Block, Vector3.one * 0.2, centre, ctx.style.palette.glow)
	spinner.Transparency = 1
	local trails: { Trail } = {}
	for i = 1, arms do
		local tiltX = ctx.random:NextNumber(-1.2, 1.2)
		local tiltZ = ctx.random:NextNumber(-1.2, 1.2)
		local base = CFrame.Angles(tiltX, (i / arms) * math.pi * 2, tiltZ)
		local a0 = Instance.new("Attachment")
		a0.CFrame = base * CFrame.new(radius, 0, 0)
		a0.Parent = spinner
		local a1 = Instance.new("Attachment")
		a1.Name = "Inner"
		a1.CFrame = base * CFrame.new(radius * 0.55, 0, 0)
		a1.Parent = spinner
		local t = Instance.new("Trail")
		t.Attachment0 = a0
		t.Attachment1 = a1
		t.Lifetime = 0.3 / ctx.speed
		t.MinLength = 0
		t.FaceCamera = true
		t.LightEmission = ctx.style.lightEmission
		t.LightInfluence = 0
		t.Texture = ctx.style.textures.streak
		t.Color = ColorSequence.new(ctx.style.palette.core, ctx.style.palette.glow)
		t.Transparency = seq(0, 0, 1, 1)
		t.WidthScale = seq(0, 1, 1, 0.2)
		t.Parent = spinner
		table.insert(trails, t)
	end
	local spin = num(p, "spin", 9)
	local started = os.clock()
	local connection: RBXScriptConnection
	connection = RunService.Heartbeat:Connect(function()
		local elapsed = (os.clock() - started) * ctx.speed
		if not ctx.alive or elapsed > life or spinner.Parent == nil then
			connection:Disconnect()
			return
		end
		local k = elapsed / life
		local step = if ctx.style.timing.stepped then math.floor(elapsed * 12) / 12 else elapsed
		spinner.CFrame = centre * CFrame.Angles(step * spin * 0.35, step * spin, 0) * CFrame.new()
		spinner.Size = Vector3.one * 0.2
		for _, child in spinner:GetChildren() do
			if child:IsA("Attachment") then
				local unit = child.Position.Unit
				local inner = child.Name == "Inner"
				child.Position = unit * (if inner then radius * 0.55 else radius) * (1 - 0.6 * k)
			end
		end
	end)
	table.insert(ctx.connections, connection)
	task.delay(Prim.dur(ctx, life * 0.7), function()
		if ctx.alive then
			Prim.tween(ctx, shell, life * 0.3, { Size = Vector3.one * 0.5, Transparency = 1 }, ctx.style.timing.easeIn,
				Enum.EasingDirection.In)
		end
	end)
	Prim.cleanup(ctx, shell, life + 0.2)
	Prim.cleanup(ctx, spinner, life + 0.5)
	Prim.burst(ctx, { count = 24, texture = "swirl", size = radius * 0.9, speed = 0.5, life = life * 0.8, spin = 400,
		y = radius * 0.8, orient = "camera", spread = 180, color = "glow" })
end

-- ------------------------------------------------------------------ ground

local function groundHit(ctx: Ctx): RaycastResult?
	local params = RaycastParams.new()
	local exclude: { Instance } = { ctx.folder }
	if ctx.caster then
		table.insert(exclude, ctx.caster)
	end
	params.FilterDescendantsInstances = exclude
	params.FilterType = Enum.RaycastFilterType.Exclude
	return workspace:Raycast(ctx.origin.Position + Vector3.new(0, 4, 0), Vector3.new(0, -12, 0), params)
end

-- Ground crack: a dark flat decal particle, glowing radial crack lines and rock spikes.
-- Params: radius, cracks, dur.
function Prim.crack(ctx: Ctx, p: Params?)
	local radius = num(p, "radius", 16) * ctx.style.sizeScale
	local life = num(p, "dur", ctx.style.timing.linger + ctx.style.timing.dissipate)
	local hit = groundHit(ctx)
	local groundY = if hit then hit.Position.Y - ctx.origin.Position.Y else 0
	-- dark scorch / crack decal laid flat
	if Prim.take(ctx, 1) > 0 then
		local a = attachment(ctx, Vector3.new(0, groundY + 0.08, 0))
		local soft = ctx.style.shape == "round"
		local e = emitter(ctx, a, texture(ctx, p, "crack"), if soft then ctx.style.palette.accent else ctx.style.palette.dark)
		e.LightEmission = 0
		e.Orientation = Enum.ParticleOrientation.VelocityPerpendicular
		e.EmissionDirection = Enum.NormalId.Top
		e.Speed = NumberRange.new(0.01)
		e.Lifetime = NumberRange.new(life)
		e.Rotation = NumberRange.new(0, 360)
		local k = if soft then 0.45 else 1
		e.Size = seq(0, radius * 0.6 * k, 0.08, radius * 1.6 * k, 1, radius * 1.7 * k)
		e.Transparency = if soft then seq(0, 0.5, 0.8, 0.6, 1, 1) else seq(0, 0.1, 0.8, 0.2, 1, 1)
		e:Emit(1)
		Prim.cleanup(ctx, a, life + 0.3)
	end
	-- glowing crack lines: jagged polylines radiating out
	local lines = math.clamp(math.floor(num(p, "cracks", 9) * (0.5 + 0.5 * ctx.quality)), 3, 16)
	local blocky = ctx.style.shape == "blocky"
	for i = 1, lines do
		local angle = (i / lines) * math.pi * 2 + ctx.random:NextNumber(-0.25, 0.25)
		local pos = Vector3.zero
		local pieces = if blocky then 2 else 3
		for piece = 1, pieces do
			local bend = if blocky then 0 else ctx.random:NextNumber(-0.5, 0.5)
			local len = radius / pieces * ctx.random:NextNumber(0.7, 1.15)
			local dir = Vector3.new(math.sin(angle + bend), 0, math.cos(angle + bend))
			local mid = pos + dir * len * 0.5
			local cf = ctx.origin * CFrame.new(mid + Vector3.new(0, groundY + 0.1, 0)) * CFrame.lookAt(Vector3.zero, dir).Rotation
			local w = (if blocky then 0.8 else 0.35) * (1 - (piece - 1) / pieces * 0.6)
			local seg = part(ctx, Enum.PartType.Block, Vector3.new(w, 0.12, 0.05), cf,
				if ctx.style.shape == "round" then ctx.style.palette.core else ctx.style.palette.glow,
				if ctx.style.lightEmission > 0.5 then Enum.Material.Neon else ctx.style.material)
			local delay = (piece - 1) * 0.04
			task.delay(Prim.dur(ctx, delay), function()
				if seg.Parent then
					Prim.tween(ctx, seg, 0.12, { Size = Vector3.new(w, 0.12, len) })
				end
			end)
			task.delay(Prim.dur(ctx, life * 0.6), function()
				if seg.Parent then
					Prim.tween(ctx, seg, life * 0.4, { Transparency = 1, Color = ctx.style.palette.dark }, ctx.style.timing.easeIn,
						Enum.EasingDirection.In)
				end
			end)
			Prim.cleanup(ctx, seg, life + 0.1)
			pos += dir * len
		end
	end
end

-- Debris: chunks thrown out of the ground. They take the floor's own material and colour (raycast), fly on a
-- simple ballistic path with ground bounces checked by short raycasts (no physics ownership, no pushing players),
-- then sink and fade. Params: count, speed, radius, dur.
function Prim.debris(ctx: Ctx, p: Params?)
	local count = math.clamp(math.floor(num(p, "count", 16) * ctx.style.intensity * ctx.quality + 0.5), 0, 40)
	if count == 0 then
		return
	end
	local hit = groundHit(ctx)
	local floorColor = if hit and hit.Instance:IsA("BasePart") then hit.Instance.Color else ctx.style.palette.dark
	local floorMaterial = if hit then hit.Material else Enum.Material.Slate
	if floorMaterial == Enum.Material.Air or floorMaterial == Enum.Material.Water then
		floorMaterial = Enum.Material.Slate
	end
	local groundY = if hit then hit.Position.Y else ctx.origin.Position.Y
	local life = num(p, "dur", 1.6)
	local speed = num(p, "speed", 45) * ctx.style.sizeScale
	local radius = num(p, "radius", 4)
	local chunks: { BasePart } = {}
	local velocity: { Vector3 } = {}
	local spinAxis: { Vector3 } = {}
	for i = 1, count do
		local angle = ctx.random:NextNumber(0, math.pi * 2)
		local out = Vector3.new(math.sin(angle), 0, math.cos(angle))
		local s = ctx.random:NextNumber(0.6, 2.2) * ctx.style.sizeScale
		local size = if ctx.style.shape == "blocky" then Vector3.one * math.floor(s + 0.5)
			else Vector3.new(s, s * ctx.random:NextNumber(0.4, 0.9), s * ctx.random:NextNumber(0.6, 1.2))
		local cf = CFrame.new(ctx.origin.Position.X, groundY + size.Y * 0.5, ctx.origin.Position.Z) + out * radius
		local soft = ctx.style.shape == "round"
		local tint = if soft then ({ ctx.style.palette.glow, ctx.style.palette.accent, ctx.style.palette.core })[i % 3 + 1]
			elseif i % 4 == 0 then ctx.style.palette.glow else floorColor
		local chunk = part(ctx, if soft then Enum.PartType.Ball else Enum.PartType.Block, if soft then Vector3.one * s * 0.8 else size,
			cf * CFrame.Angles(ctx.random:NextNumber(0, 6), ctx.random:NextNumber(0, 6), 0), tint,
			if soft then Enum.Material.SmoothPlastic elseif i % 4 == 0 then Enum.Material.Neon
				else (ctx.style.debrisMaterial or floorMaterial))
		chunk.CastShadow = true
		table.insert(chunks, chunk)
		table.insert(velocity, out * speed * ctx.random:NextNumber(0.3, 1) + Vector3.new(0, speed * ctx.random:NextNumber(0.5, 1.1), 0))
		table.insert(spinAxis, ctx.random:NextUnitVector() * ctx.random:NextNumber(4, 12))
		Prim.cleanup(ctx, chunk, life + 0.3)
	end
	local params = RaycastParams.new()
	params.FilterDescendantsInstances = { ctx.folder }
	params.FilterType = Enum.RaycastFilterType.Exclude
	local gravity = workspace.Gravity * 0.6
	local started = os.clock()
	local last = started
	local resting: { boolean } = table.create(count, false)
	local connection: RBXScriptConnection
	connection = RunService.Heartbeat:Connect(function()
		local now = os.clock()
		local dt = math.min(now - last, 0.05) * ctx.speed
		last = now
		local elapsed = (now - started) * ctx.speed
		if not ctx.alive or elapsed > life then
			connection:Disconnect()
			return
		end
		local parts: { BasePart } = {}
		local frames: { CFrame } = {}
		for i, chunk in chunks do
			if chunk.Parent and not resting[i] then
				local v = velocity[i] - Vector3.new(0, gravity * dt, 0)
				local from = chunk.Position
				local step = v * dt
				local ground = workspace:Raycast(from, step + Vector3.new(0, -chunk.Size.Y * 0.5, 0), params)
				if ground and v.Y < 0 then
					v = Vector3.new(v.X * 0.5, -v.Y * 0.3, v.Z * 0.5)
					step = Vector3.new(step.X, 0, step.Z)
					if v.Magnitude < 4 then
						resting[i] = true
					end
				end
				velocity[i] = v
				local spin = spinAxis[i] * dt
				table.insert(parts, chunk)
				table.insert(frames, (chunk.CFrame + step) * CFrame.Angles(spin.X, spin.Y, spin.Z))
			end
		end
		if #parts > 0 then
			workspace:BulkMoveTo(parts, frames, Enum.BulkMoveMode.FireCFrameChanged)
		end
	end)
	table.insert(ctx.connections, connection)
	task.delay(Prim.dur(ctx, life * 0.7), function()
		for _, chunk in chunks do
			if chunk.Parent then
				Prim.tween(ctx, chunk, life * 0.3, { Transparency = 1, Size = chunk.Size * 0.4 }, ctx.style.timing.easeIn,
					Enum.EasingDirection.In)
			end
		end
	end)
end

-- Rock spikes jutting from the ground around the impact (jagged and blocky styles). Params: count, radius, height, dur.
function Prim.spikes(ctx: Ctx, p: Params?)
	if ctx.style.shape ~= "jagged" and ctx.style.shape ~= "blocky" and not bool(p, "force", false) then
		return -- round, wispy and crisp styles have no rock spikes
	end
	local count = math.clamp(math.floor(num(p, "count", 10) * ctx.quality + 0.5), 0, 24)
	local radius = num(p, "radius", 10) * ctx.style.sizeScale
	local height = num(p, "height", 7) * ctx.style.sizeScale
	local life = num(p, "dur", ctx.style.timing.linger)
	local hit = groundHit(ctx)
	local groundY = if hit then hit.Position.Y - ctx.origin.Position.Y else 0
	for _ = 1, count do
		local angle = ctx.random:NextNumber(0, math.pi * 2)
		local r = radius * ctx.random:NextNumber(0.5, 1)
		local h = height * ctx.random:NextNumber(0.5, 1)
		local lean = CFrame.Angles(ctx.random:NextNumber(0.3, 0.8), 0, 0)
		local base = ctx.origin * CFrame.Angles(0, angle, 0) * CFrame.new(0, groundY, -r) * lean
		local w = ctx.random:NextNumber(1, 2.5) * ctx.style.sizeScale
		local wedge = Instance.new("WedgePart")
		wedge.Anchored = true
		wedge.CanCollide = false
		wedge.CanQuery = false
		wedge.CanTouch = false
		wedge.Size = Vector3.new(w, h, w)
		wedge.Material = ctx.style.debrisMaterial or Enum.Material.Slate
		wedge.Color = ctx.style.palette.dark
		wedge.CFrame = base * CFrame.new(0, -h * 0.5, 0)
		wedge.Parent = ctx.folder
		Prim.tween(ctx, wedge, 0.12, { CFrame = base * CFrame.new(0, h * 0.35, 0) })
		task.delay(Prim.dur(ctx, life * 0.7), function()
			if wedge.Parent then
				Prim.tween(ctx, wedge, life * 0.3, { CFrame = base * CFrame.new(0, -h * 0.6, 0) }, ctx.style.timing.easeIn,
					Enum.EasingDirection.In)
			end
		end)
		Prim.cleanup(ctx, wedge, life + 0.1)
	end
end

-- ------------------------------------------------------------------ character aura

-- Aura on the caster: Highlight (fill + outline in the palette) that pulses in, plus rising and inward motes.
-- Params: dur. Highlights are limited (31 at once per client), so the aura is skipped when the caster has one.
function Prim.aura(ctx: Ctx, p: Params?)
	local life = num(p, "dur", ctx.style.timing.charge + ctx.style.timing.impact)
	local target: Instance = ctx.caster or ctx.anchor
	if target:FindFirstChildOfClass("Highlight") == nil then
		local h = Instance.new("Highlight")
		h.FillColor = ctx.style.palette.glow
		h.OutlineColor = ctx.style.palette.core
		h.FillTransparency = 1
		h.OutlineTransparency = 1
		h.DepthMode = Enum.HighlightDepthMode.Occluded
		h.Adornee = target
		h.Parent = ctx.folder
		Prim.tween(ctx, h, life * 0.5, { FillTransparency = 0.35, OutlineTransparency = 0 })
		task.delay(Prim.dur(ctx, life * 0.85), function()
			if h.Parent then
				Prim.tween(ctx, h, life * 0.4, { FillTransparency = 1, OutlineTransparency = 1 }, ctx.style.timing.easeIn,
					Enum.EasingDirection.In)
			end
		end)
		Prim.cleanup(ctx, h, life * 1.3)
	end
	-- rising energy around the body: a short continuous emitter
	local n = Prim.take(ctx, num(p, "count", 60))
	if n > 0 then
		local a = attachment(ctx, Vector3.new(0, 1, 0))
		local e = emitter(ctx, a, ctx.style.textures.glow, ctx.style.palette.glow)
		e.Speed = NumberRange.new(4, 10)
		e.Acceleration = Vector3.new(0, 14, 0)
		e.Lifetime = NumberRange.new(0.4, 0.8)
		e.SpreadAngle = Vector2.new(25, 25)
		e.Size = seq(0, 1.6 * ctx.style.sizeScale, 1, 0)
		e.Transparency = seq(0, 0.2, 1, 1)
		e.Rate = n / life
		e.Enabled = true
		task.delay(Prim.dur(ctx, life), function()
			e.Enabled = false
		end)
		Prim.cleanup(ctx, a, life + 1)
	end
	Prim.burst(ctx, { inward = true, radius = 9, count = 40, speed = 18, life = 0.5, size = 0.5, texture = "spark",
		color = "core", y = 3, drag = 0 })
end

-- ------------------------------------------------------------------ light, screen, camera

function Prim.light(ctx: Ctx, p: Params?)
	local life = num(p, "dur", 0.4)
	local a = attachment(ctx, Vector3.new(0, 4, 0))
	local l = Instance.new("PointLight")
	l.Color = color(ctx, p, "color", "glow")
	l.Range = num(p, "range", 40)
	l.Brightness = num(p, "brightness", 6) * ctx.style.lightEmission + 1
	l.Shadows = false
	l.Parent = a
	Prim.tween(ctx, l, life, { Brightness = 0 }, ctx.style.timing.easeIn, Enum.EasingDirection.In)
	Prim.cleanup(ctx, a, life + 0.1)
end

local function screenGui(ctx: Ctx): ScreenGui?
	local player = Players.LocalPlayer
	if not player then
		return nil
	end
	local playerGui = player:FindFirstChildOfClass("PlayerGui")
	if not playerGui then
		return nil
	end
	local gui = Instance.new("ScreenGui")
	gui.Name = "StarVfxFlash"
	gui.IgnoreGuiInset = true
	gui.DisplayOrder = 50
	gui.ResetOnSpawn = false
	gui.Parent = playerGui
	return gui
end

-- Screen flash (full-screen frame) and, for styles that allow it, one inverted frame plus a bloom kick.
-- Params: strength (0..1, times the style's flash), dur.
function Prim.flash(ctx: Ctx, p: Params?)
	if not ctx.screen then
		return
	end
	local strength = math.clamp(num(p, "strength", 1) * ctx.style.screen.flash, 0, 1)
	local life = num(p, "dur", 0.18)
	local invert = ctx.style.screen.invert and bool(p, "invert", true)
	local invertFor = num(p, "invertFor", 0.07)
	if invert then
		local cc = Instance.new("ColorCorrectionEffect")
		cc.Name = "StarVfxInvert"
		cc.Saturation = -1 -- grey ...
		cc.Contrast = -2 -- ... and inverted: contrast -2 maps a value c to 1 - c
		cc.Brightness = 0
		cc.Parent = Lighting
		Debris:AddItem(cc, Prim.dur(ctx, invertFor))
	end
	if strength > 0.02 then
		if invert then
			task.wait(Prim.dur(ctx, invertFor)) -- the colour flash follows the inverted frame
		end
		local gui = screenGui(ctx)
		if gui then
			local frame = Instance.new("Frame")
			frame.Size = UDim2.fromScale(1, 1)
			frame.BorderSizePixel = 0
			frame.BackgroundColor3 = ctx.style.palette.flash
			frame.BackgroundTransparency = 1 - strength
			frame.Parent = gui
			Prim.tween(ctx, frame, life, { BackgroundTransparency = 1 }, ctx.style.timing.easeIn, Enum.EasingDirection.Out)
			Prim.cleanup(ctx, gui, life + 0.1)
		end
	end
	if ctx.style.screen.bloom > 0 then
		local bloom = Instance.new("BloomEffect")
		bloom.Name = "StarVfxBloom"
		bloom.Intensity = ctx.style.screen.bloom
		bloom.Size = 40
		bloom.Threshold = 0.8
		bloom.Parent = Lighting
		Prim.tween(ctx, bloom, life * 3, { Intensity = 0 }, ctx.style.timing.easeIn, Enum.EasingDirection.Out)
		Prim.cleanup(ctx, bloom, life * 3 + 0.1)
	end
end

-- Colour tint toward the palette for the length of the effect (ColorCorrectionEffect on Lighting, local only).
-- Params: dur.
function Prim.tint(ctx: Ctx, p: Params?)
	if not ctx.screen or ctx.style.screen.tint <= 0 then
		return
	end
	local life = num(p, "dur", 2)
	local cc = Instance.new("ColorCorrectionEffect")
	cc.Name = "StarVfxTint"
	cc.TintColor = Color3.new(1, 1, 1)
	cc.Parent = Lighting
	local k = ctx.style.screen.tint
	local target = Color3.new(1, 1, 1):Lerp(ctx.style.palette.glow, k)
	Prim.tween(ctx, cc, life * 0.15, { TintColor = target, Contrast = 0.15 * k, Saturation = 0.2 * k })
	task.delay(Prim.dur(ctx, life * 0.7), function()
		if cc.Parent then
			Prim.tween(ctx, cc, life * 0.3, { TintColor = Color3.new(1, 1, 1), Contrast = 0, Saturation = 0 }, ctx.style.timing.easeIn,
				Enum.EasingDirection.Out)
		end
	end)
	Prim.cleanup(ctx, cc, life + 0.1)
end

-- Camera shake: decaying smooth noise applied after the camera scripts each frame (Camera + 2, so a game camera
-- bound at Camera + 1 is shaken too), plus an FOV punch. A Scriptable camera must be re-set every frame by its owner,
-- or the offsets accumulate.
-- Params: amplitude (times the style's shake), dur, frequency.
function Prim.shake(ctx: Ctx, p: Params?)
	if not ctx.screen then
		return
	end
	local camera = workspace.CurrentCamera
	if not camera then
		return
	end
	local amplitude = num(p, "amplitude", 1) * ctx.style.screen.shake
	local life = num(p, "dur", 0.45)
	local frequency = num(p, "frequency", 18)
	if amplitude > 0.01 then
		local name = "StarVfxShake" .. tostring(ctx.random:NextInteger(1, 1e9))
		local started = os.clock()
		local seed = ctx.random:NextNumber(0, 100)
		local stepped = ctx.style.timing.stepped
		RunService:BindToRenderStep(name, Enum.RenderPriority.Camera.Value + 2, function()
			local elapsed = (os.clock() - started) * ctx.speed
			if elapsed > life or not ctx.alive then
				RunService:UnbindFromRenderStep(name)
				return
			end
			local decay = (1 - elapsed / life) ^ 2
			local t = if stepped then math.floor(elapsed * 15) / 15 else elapsed
			local x = math.noise(seed, t * frequency) * amplitude * decay
			local y = math.noise(seed + 10, t * frequency) * amplitude * decay
			local r = math.noise(seed + 20, t * frequency) * amplitude * decay * 0.03
			camera.CFrame = camera.CFrame * CFrame.new(x, y, 0) * CFrame.Angles(0, 0, r)
		end)
		table.insert(ctx.bound, name)
	end
	local punch = num(p, "fov", 1) * ctx.style.screen.fovPunch
	if punch > 0.5 then
		-- overlapping effects punch from the same resting FOV instead of drifting wider each time
		local saved = camera:GetAttribute("StarVfxBaseFov")
		local base = if type(saved) == "number" then saved else camera.FieldOfView
		camera:SetAttribute("StarVfxBaseFov", base)
		camera.FieldOfView = math.clamp(base + punch, 1, 120)
		local info = TweenInfo.new(Prim.dur(ctx, life), Enum.EasingStyle.Quad, Enum.EasingDirection.Out)
		local tween = TweenService:Create(camera, info, { FieldOfView = base })
		tween.Completed:Once(function()
			if camera:GetAttribute("StarVfxBaseFov") == base and camera.FieldOfView == base then
				camera:SetAttribute("StarVfxBaseFov", nil)
			end
		end)
		tween:Play()
	end
end

-- ------------------------------------------------------------------ data-driven layers (STAR designer)
-- The design-plan generator (star/roblox_vfx_designer.py) writes these as plain data: curves are strings
-- "t v t v ..." (times 0..1, values relative to `size` or as transparency), colour ramps are "t key t key ..."
-- over palette keys. A malformed curve or ramp falls back to a safe default; nothing here runs generated code.

local function curve(p: Params?, key: string, scale: number, fallback: NumberSequence): NumberSequence
	local v = p and p[key]
	if type(v) ~= "string" then
		return fallback
	end
	local items = string.split(v, " ")
	local points: { NumberSequenceKeypoint } = {}
	for i = 1, #items - 1, 2 do
		local t = tonumber(items[i])
		local x = tonumber(items[i + 1])
		if t == nil or x == nil then
			return fallback
		end
		table.insert(points, NumberSequenceKeypoint.new(math.clamp(t, 0, 1), x * scale))
	end
	if #points < 2 then
		return fallback
	end
	local ok, made = pcall(NumberSequence.new, points)
	return if ok then made else fallback
end
Prim.curve = curve

local function ramp(ctx: Ctx, p: Params?, key: string, fallback: Color3): ColorSequence
	local v = p and p[key]
	if type(v) ~= "string" then
		return ColorSequence.new(fallback)
	end
	local items = string.split(v, " ")
	local points: { ColorSequenceKeypoint } = {}
	for i = 1, #items - 1, 2 do
		local t = tonumber(items[i])
		local c = (ctx.style.palette :: any)[items[i + 1]]
		if t == nil or typeof(c) ~= "Color3" then
			return ColorSequence.new(fallback)
		end
		table.insert(points, ColorSequenceKeypoint.new(math.clamp(t, 0, 1), c))
	end
	if #points < 2 then
		return ColorSequence.new(fallback)
	end
	local ok, made = pcall(ColorSequence.new, points)
	return if ok then made else ColorSequence.new(fallback)
end

local SHAPES: { [string]: Enum.ParticleEmitterShape } = {
	sphere = Enum.ParticleEmitterShape.Sphere,
	disc = Enum.ParticleEmitterShape.Disc,
	box = Enum.ParticleEmitterShape.Box,
	cylinder = Enum.ParticleEmitterShape.Cylinder,
}

local function offset(p: Params?, suffix: string, x: number, y: number, z: number): Vector3
	return Vector3.new(num(p, "x" .. suffix, x), num(p, "y" .. suffix, y), num(p, "z" .. suffix, z))
end

-- Emitter host: an Attachment for point emission, else a tiny invisible part sized to the shape (Sphere and
-- Cylinder shapes do not display correctly on an Attachment). pitch/yaw (degrees) turn the emission face.
local function host(ctx: Ctx, p: Params?): Instance
	local rotation = CFrame.Angles(0, math.rad(num(p, "yaw", 0)), 0) * CFrame.Angles(math.rad(num(p, "pitch", 0)), 0, 0)
	local shapeName = if type(p) == "table" and type(p.shape) == "string" then p.shape else "point"
	local shape = SHAPES[shapeName]
	if shape == nil then
		local a = attachment(ctx, offset(p, "", 0, 1, 0))
		a.CFrame = CFrame.new(a.Position) * rotation
		return a
	end
	local radius = num(p, "radius", 2) * ctx.style.sizeScale
	local height = num(p, "height", 0.2) * ctx.style.sizeScale
	local size = if shapeName == "sphere" then Vector3.one * radius * 2 else Vector3.new(radius * 2, height, radius * 2)
	local h = part(ctx, Enum.PartType.Block, size, ctx.origin * CFrame.new(offset(p, "", 0, 1, 0)) * rotation,
		ctx.style.palette.glow, Enum.Material.SmoothPlastic)
	h.Transparency = 1
	return h
end

-- A particle layer from data: a burst (count -> Emit) or a loop (rate for dur seconds), with size / transparency
-- curves, a colour ramp, emitter shape, orientation and an optional flipbook (the style's flipbook sheet).
-- Params: count | rate+dur, life, lifeMin, size, sizeCurve, alphaCurve, ramp, color, texture, speed, speedMin,
-- spread, gravity, drag, windX, spin, orient, shape, radius, height, surface, inward, x/y/z, pitch, yaw,
-- lightEmission, zOffset, flipbook ("oneshot" | "loop" | "random"), fps, locked.
function Prim.particles(ctx: Ctx, p: Params?)
	local rate = num(p, "rate", 0)
	local dur = num(p, "dur", 1)
	local n = Prim.take(ctx, if rate > 0 then rate * dur else num(p, "count", 20))
	if n <= 0 then
		return
	end
	local life = num(p, "life", 0.8)
	local h = host(ctx, p)
	local base = color(ctx, p, "color", "glow")
	local e = emitter(ctx, h, texture(ctx, p, "glow"), base)
	e.Color = ramp(ctx, p, "ramp", base)
	local size = num(p, "size", 1) * ctx.style.sizeScale
	e.Size = curve(p, "sizeCurve", size, seq(0, size, 1, 0))
	e.Transparency = curve(p, "alphaCurve", 1, seq(0, 0, 0.7, 0.2, 1, 1))
	e.Lifetime = NumberRange.new(math.min(num(p, "lifeMin", life * 0.7), life), life)
	local speed = num(p, "speed", 5) * ctx.style.sizeScale
	e.Speed = NumberRange.new(math.min(num(p, "speedMin", speed * 0.5), speed), speed)
	local spread = num(p, "spread", 180)
	e.SpreadAngle = Vector2.new(spread, spread)
	e.Drag = num(p, "drag", 0)
	e.Acceleration = Vector3.new(num(p, "windX", 0), -num(p, "gravity", 0), 0)
	local spin = num(p, "spin", 60)
	e.Rotation = NumberRange.new(0, 360)
	e.RotSpeed = NumberRange.new(-spin, spin)
	local orient = if type(p) == "table" and type(p.orient) == "string" then p.orient else "camera"
	if orient == "velocity" then
		e.Orientation = Enum.ParticleOrientation.VelocityParallel
	elseif orient == "flat" then
		e.Orientation = Enum.ParticleOrientation.VelocityPerpendicular
	elseif orient == "worldup" then
		e.Orientation = Enum.ParticleOrientation.FacingCameraWorldUp
	end
	local shape = SHAPES[if type(p) == "table" and type(p.shape) == "string" then p.shape else "point"]
	if shape then
		e.Shape = shape
		e.ShapeStyle = if bool(p, "surface", false) then Enum.ParticleEmitterShapeStyle.Surface else Enum.ParticleEmitterShapeStyle.Volume
		e.ShapeInOut = if bool(p, "inward", false) then Enum.ParticleEmitterShapeInOut.Inward else Enum.ParticleEmitterShapeInOut.Outward
	end
	e.LightEmission = math.clamp(num(p, "lightEmission", ctx.style.lightEmission), 0, 1)
	e.ZOffset = num(p, "zOffset", 0)
	e.LockedToPart = bool(p, "locked", false)
	local mode = if type(p) == "table" and type(p.flipbook) == "string" then p.flipbook else nil
	local book = ctx.style.textures.flipbook
	if mode and book then
		e.Texture = book
		e.FlipbookLayout = Enum.ParticleFlipbookLayout.Grid4x4
		e.FlipbookMode = if mode == "loop" then Enum.ParticleFlipbookMode.Loop
			elseif mode == "random" then Enum.ParticleFlipbookMode.Random
			else Enum.ParticleFlipbookMode.OneShot
		e.FlipbookFramerate = NumberRange.new(math.clamp(num(p, "fps", 16), 1, 30))
		e.FlipbookStartRandom = mode ~= "oneshot"
	end
	if rate > 0 then
		e.Rate = n / dur
		e.Enabled = true
		task.delay(Prim.dur(ctx, dur), function()
			e.Enabled = false
		end)
	else
		e:Emit(n)
	end
	Prim.cleanup(ctx, h, (if rate > 0 then dur else 0) + life + 0.3)
end

-- A beam from (x0,y0,z0) to (x1,y1,z1): a thin core over a wider glow, CurveSize bend, Segments, scrolling
-- texture (opt-in), grow-in and fade-out. zigzag > 0 cuts it into that many jagged joints that re-jitter every `flicker`
-- seconds (a lightning bolt). Params: width, taper, layers, segments, curve0, curve1, texture, textureSpeed,
-- textureLength, ramp, alphaCurve, dur, grow, zigzag, jitter, flicker.
function Prim.beam(ctx: Ctx, p: Params?)
	local life = num(p, "dur", 0.6)
	local from = offset(p, "0", 0, 0, 0)
	local to = offset(p, "1", 0, 20, 0)
	local joints = math.clamp(math.floor(num(p, "zigzag", 0)), 0, 12)
	local jitter = num(p, "jitter", 2) * ctx.style.sizeScale
	local width = num(p, "width", 1) * ctx.style.sizeScale
	local dir = (to - from).Unit
	local side = dir:Cross(if math.abs(dir.Y) > 0.9 then Vector3.xAxis else Vector3.yAxis).Unit
	local up = dir:Cross(side).Unit
	local points: { Attachment } = {}
	for i = 0, joints + 1 do
		local a = attachment(ctx, from:Lerp(to, i / (joints + 1)))
		table.insert(points, a)
		Prim.cleanup(ctx, a, life + 0.2)
	end
	local function jolt()
		for i = 2, #points - 1 do
			points[i].Position = from:Lerp(to, (i - 1) / (joints + 1)) + side * ctx.random:NextNumber(-jitter, jitter)
				+ up * ctx.random:NextNumber(-jitter, jitter) * 0.5
		end
	end
	if joints > 0 then
		jolt()
	end
	local grow = num(p, "grow", math.min(0.08, life * 0.2))
	local beams: { Beam } = {}
	for layer = 1, math.clamp(math.floor(num(p, "layers", 2)), 1, 3) do
		local w = if layer == 1 then width * 0.45 else width * (0.6 + 0.7 * layer)
		for i = 1, #points - 1 do
			local b = Instance.new("Beam")
			b.Attachment0 = points[i]
			b.Attachment1 = points[i + 1]
			b.FaceCamera = true
			b.Segments = math.clamp(math.floor(num(p, "segments", 10)), 1, 100)
			b.CurveSize0 = num(p, "curve0", 0)
			b.CurveSize1 = num(p, "curve1", 0)
			-- Solid layers unless a texture is asked for: the particle textures are radial or tapered, so wrapped
			-- along a beam they read as a row of dots.
			if type(p) == "table" and type(p.texture) == "string" then
				b.Texture = texture(ctx, p, "glow")
				b.TextureMode = Enum.TextureMode.Wrap
				b.TextureLength = num(p, "textureLength", 6)
				b.TextureSpeed = num(p, "textureSpeed", 2) * ctx.speed
			end
			b.LightEmission = ctx.style.lightEmission
			b.LightInfluence = 0
			b.Color = if layer == 1 then ColorSequence.new(ctx.style.palette.core) else ramp(ctx, p, "ramp", ctx.style.palette.glow)
			b.Transparency = if layer == 1 then curve(p, "alphaCurve", 1, NumberSequence.new(0)) else NumberSequence.new(0.3 + 0.15 * layer)
			b.ZOffset = if layer == 1 then 0.2 else 0
			b.Width0 = 0
			b.Width1 = 0
			b.Parent = ctx.anchor
			Prim.tween(ctx, b, grow, { Width0 = w, Width1 = w * num(p, "taper", 1) })
			table.insert(beams, b)
			Prim.cleanup(ctx, b, life + 0.2)
		end
	end
	if joints > 0 then
		local flicker = math.max(0.03, num(p, "flicker", 0.06))
		task.spawn(function()
			local started = os.clock()
			while ctx.alive and (os.clock() - started) * ctx.speed < life do
				task.wait(Prim.dur(ctx, flicker))
				jolt()
			end
		end)
	end
	task.delay(Prim.dur(ctx, life * 0.6), function()
		if not ctx.alive then
			return
		end
		for _, b in beams do
			Prim.tween(ctx, b, life * 0.4, { Width0 = 0, Width1 = 0 }, ctx.style.timing.easeIn, Enum.EasingDirection.In)
		end
	end)
end

-- A projectile: a glowing head flies from (x0,y0,z0) to (x1,y1,z1) in `dur` seconds on an arc of height `arc`,
-- leaving a Trail (trailLife, widthCurve, trailAlpha, minLength, ramp) and, with rate > 0, an emitter on the head
-- (embers / flame: emitLife, emitSize, emitCurve, emitTexture). Params also: size, headAlpha.
function Prim.projectile(ctx: Ctx, p: Params?)
	local life = num(p, "dur", 0.6)
	local from = offset(p, "0", 0, 4, -30)
	local to = offset(p, "1", 0, 2, 0)
	local size = num(p, "size", 1.5) * ctx.style.sizeScale
	local arc = num(p, "arc", 0)
	local head = part(ctx, Enum.PartType.Ball, Vector3.one * size, ctx.origin * CFrame.new(from), ctx.style.palette.core,
		if ctx.style.lightEmission > 0.5 then Enum.Material.Neon else ctx.style.material)
	head.Transparency = num(p, "headAlpha", 0)
	local top = Instance.new("Attachment")
	top.Position = Vector3.new(0, size * 0.5, 0)
	top.Parent = head
	local bottom = Instance.new("Attachment")
	bottom.Position = Vector3.new(0, -size * 0.5, 0)
	bottom.Parent = head
	local trailLife = num(p, "trailLife", 0.35)
	local t = Instance.new("Trail")
	t.Attachment0 = top
	t.Attachment1 = bottom
	t.FaceCamera = true
	t.Lifetime = trailLife / ctx.speed
	t.MinLength = num(p, "minLength", 0.1)
	t.WidthScale = curve(p, "widthCurve", 1, seq(0, 1, 1, 0))
	t.Transparency = curve(p, "trailAlpha", 1, seq(0, 0, 1, 1))
	t.Color = ramp(ctx, p, "ramp", ctx.style.palette.glow)
	-- A ribbon reads as a solid band shaped by WidthScale and Transparency; a texture (trailTexture) is opt-in,
	-- because the particle textures fade across their height and would show only a thin line along the ribbon.
	if type(p) == "table" and type(p.trailTexture) == "string" then
		t.Texture = texture(ctx, { texture = p.trailTexture }, "glow")
		t.TextureMode = Enum.TextureMode.Stretch
	end
	t.LightEmission = ctx.style.lightEmission
	t.LightInfluence = 0
	t.Parent = head
	local e: ParticleEmitter? = nil
	local emitLife = num(p, "emitLife", 0.5)
	local rate = num(p, "rate", 0)
	local n = if rate > 0 then Prim.take(ctx, rate * life) else 0
	if n > 0 then
		local emitSize = num(p, "emitSize", size) * ctx.style.sizeScale
		local made = emitter(ctx, top, texture(ctx, { texture = if type(p) == "table" then p.emitTexture else nil }, "glow"),
			ctx.style.palette.glow)
		made.Color = ramp(ctx, p, "ramp", ctx.style.palette.glow)
		made.Size = curve(p, "emitCurve", emitSize, seq(0, emitSize, 1, 0))
		made.Transparency = seq(0, 0.1, 0.6, 0.4, 1, 1)
		made.Lifetime = NumberRange.new(emitLife * 0.6, emitLife)
		made.Speed = NumberRange.new(1, 3)
		made.SpreadAngle = Vector2.new(180, 180)
		made.Acceleration = Vector3.new(0, num(p, "rise", 4), 0)
		made.Rotation = NumberRange.new(0, 360)
		made.RotSpeed = NumberRange.new(-120, 120)
		made.Rate = n / life
		made.Enabled = true
		e = made
	end
	local started = os.clock()
	local connection: RBXScriptConnection
	connection = RunService.Heartbeat:Connect(function()
		local k = math.min((os.clock() - started) * ctx.speed / life, 1)
		if not ctx.alive or head.Parent == nil then
			connection:Disconnect()
			return
		end
		head.CFrame = ctx.origin * CFrame.new(from:Lerp(to, k) + Vector3.yAxis * arc * 4 * k * (1 - k))
		if k >= 1 then
			head.Transparency = 1
			local made = e
			if made then
				made.Enabled = false
			end
			connection:Disconnect()
		end
	end)
	table.insert(ctx.connections, connection)
	Prim.cleanup(ctx, head, life + math.max(trailLife, emitLife) + 0.3)
end

-- A sweep (sword / claw slash): an invisible arm swings through `arc` degrees around the origin at height y; a flat
-- Trail between `inner` (fraction of radius) and `radius` draws the crescent with a fast-in, slow-out swing.
-- Params: radius, inner, arc, dur, y, yaw, roll, tilt, trailLife, widthCurve, trailAlpha, ramp, texture.
function Prim.sweep(ctx: Ctx, p: Params?)
	local radius = num(p, "radius", 8) * ctx.style.sizeScale
	local inner = math.clamp(num(p, "inner", 0.55), 0, 0.95) * radius
	local life = num(p, "dur", 0.18)
	local arc = math.rad(num(p, "arc", 160))
	-- yaw turns the swing toward the viewer, roll makes it diagonal, tilt (about the rolled X axis) stands the swing
	-- plane up: tilt 90 faces the viewer at yaw's +Z, tilt 0 is a flat horizontal sweep.
	local pivot = ctx.origin * CFrame.new(0, num(p, "y", 3), 0) * CFrame.Angles(0, math.rad(num(p, "yaw", 0)), 0)
		* CFrame.Angles(0, 0, math.rad(num(p, "roll", 0))) * CFrame.Angles(math.rad(num(p, "tilt", 0)), 0, 0)
	local arm = part(ctx, Enum.PartType.Block, Vector3.one * 0.2, pivot, ctx.style.palette.glow)
	arm.Transparency = 1
	local a0 = Instance.new("Attachment")
	a0.Position = Vector3.new(0, 0, -inner)
	a0.Parent = arm
	local a1 = Instance.new("Attachment")
	a1.Position = Vector3.new(0, 0, -radius)
	a1.Parent = arm
	local trailLife = num(p, "trailLife", 0.2)
	local t = Instance.new("Trail")
	t.Attachment0 = a0
	t.Attachment1 = a1
	t.FaceCamera = false
	t.Lifetime = trailLife / ctx.speed
	t.MinLength = 0
	t.WidthScale = curve(p, "widthCurve", 1, seq(0, 1, 1, 0.3))
	t.Transparency = curve(p, "trailAlpha", 1, seq(0, 0, 0.6, 0.3, 1, 1))
	t.Color = ramp(ctx, p, "ramp", ctx.style.palette.glow)
	if type(p) == "table" and type(p.texture) == "string" then -- solid ribbon unless a texture is asked for
		t.Texture = texture(ctx, p, "glow")
		t.TextureMode = Enum.TextureMode.Stretch
	end
	t.LightEmission = ctx.style.lightEmission
	t.LightInfluence = 0
	t.Parent = arm
	local start = -arc * 0.5
	arm.CFrame = pivot * CFrame.Angles(0, start, 0)
	local started = os.clock()
	local connection: RBXScriptConnection
	connection = RunService.Heartbeat:Connect(function()
		local k = math.min((os.clock() - started) * ctx.speed / life, 1)
		if not ctx.alive or arm.Parent == nil then
			connection:Disconnect()
			return
		end
		local eased = 1 - (1 - k) ^ 3
		arm.CFrame = pivot * CFrame.Angles(0, start + arc * eased, 0)
		if k >= 1 then
			connection:Disconnect()
		end
	end)
	table.insert(ctx.connections, connection)
	Prim.cleanup(ctx, arm, life + trailLife + 0.2)
end

return Prim
