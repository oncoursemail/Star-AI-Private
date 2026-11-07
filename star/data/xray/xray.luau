--!strict
--[[
X-ray Eyes v1: checks a Roblox build with the engine's exact data (CFrames, sizes, UDim2 layout, colours)
instead of pixels. Pure functions over an instance tree; the host passes an `env` with the few things that
differ between Roblox Studio (execute_luau) and Lune (@lune/roblox, headless on .rbxl/.rbxm files):

  env.mode        "studio" | "lune"
  env.yield       optional; called about every 30 ms of work (Studio: task.wait) so 10k+ parts never freeze Studio
  env.textSize    optional exact text bounds (Studio: TextService:GetTextBoundsAsync); otherwise a per-character estimate
  env.partsInBox  optional engine spatial query (Studio: workspace:GetPartBoundsInBox); otherwise a spatial hash
  env.pathfind    optional (Studio: PathfindingService); the unreachable detector is skipped without it
  env.onTerrain   optional (Studio: a short raycast against Terrain); headless never reads terrain voxels
  env.avatar      optional measured R15 extents (Studio: CreateHumanoidModelFromDescription)

Nothing here writes to the place. Fixes come back as a change list (`report.changes`) for review.
]]

export type Change = { op: string, path: string, dx: number, dy: number, dz: number, reason: string }
export type Finding = {
	detector: string,
	severity: string,
	path: string,
	value: number,
	unit: string,
	message: string,
	fix: string,
	partner: string?,
	members: { string }?,
	viewport: string?,
	estimated: boolean?,
	change: number?,
}
export type Avatar = { height: number, heightMax: number, heightClassic: number, width: number, source: string }
export type Env = {
	mode: string,
	yield: (() -> ())?,
	textSize: ((text: string, size: number, font: any, width: number) -> (number, number))?,
	partsInBox: ((part: any, margin: number) -> { any })?,
	pathfind: ((from: any, to: any) -> string)?,
	onTerrain: ((x: number, y: number, z: number) -> boolean)?,
	avatar: Avatar?,
}
export type Viewport = { name: string, w: number, h: number }
export type Options = { [string]: any }

type Rec = {
	i: number,
	inst: any,
	name: string,
	cx: number,
	cy: number,
	cz: number,
	ax: { number },
	h: { number },
	minx: number,
	miny: number,
	minz: number,
	maxx: number,
	maxy: number,
	maxz: number,
	block: boolean,
	visible: boolean,
	solid: boolean,
	collide: boolean,
	look: string,
	vol: number,
	aligned: boolean,
	queryable: boolean,
}

type Rect = { x: number, y: number, w: number, h: number }
type GuiBox = { x: number, y: number, w: number, h: number, visible: boolean, scroll: boolean, k: number }

local Xray = {}
Xray.version = "1.0.0"

-- Sources for the avatar numbers (cited in docs/agents/xray-eyes-20261021.md):
--  * create.roblox.com/docs/art/accessories/body-scale: Classic "roughly 4.75 studs tall", Normal "roughly
--    5.75-6.5 studs tall", Slender "roughly 5.25-6.25".
--  * create.roblox.com/docs/avatar/character-bodies/specifications: total bounding box max 8 x 10 x 4 studs.
--  * Default blocky R15 rig: UpperTorso 2 studs wide + two 1-stud arms = 4 studs shoulder width
--    (measured live in Studio mode through env.avatar when available).
Xray.AVATAR = { height = 5.75, heightMax = 6.5, heightClassic = 4.75, width = 4.0, source = "docs" } :: Avatar

Xray.DEFAULTS = {
	supportEps = 0.25, -- a part within this distance of another counts as supported
	gapMin = 0.001,
	gapMax = 0.2,
	coplanarTol = 0.005,
	minFaceOverlap = 0.05,
	zMinArea = 0.01,
	penDepth = 0.2,
	penFraction = 0.3,
	gridShare = 0.8, -- at least this share of axis-aligned parts on the grid
	gridGain = 0.03, -- ...and the next finer grid adds at most this share
	gridTol = 0.005,
	rotMinDeg = 0.05,
	rotMaxDeg = 5,
	stretchRatio = 1.5,
	textSlack = 1.1, -- headless estimate must overflow by 10 % before it is reported
	touchMin = 44,
	contrastNormal = 4.5,
	contrastLarge = 3.0,
	topInset = 58,
	riserMax = 1.5,
	riserHigh = 3.0,
	riserUneven = 0.25,
	treadMin = 1.0,
	railMin = 2.5,
	railHigh = 1.5,
	railMax = 5.5,
	maxFindings = 500,
	fixes = false,
	zNudge = 0.02,
	viewports = {
		{ name = "phone", w = 844, h = 390 },
		{ name = "tablet", w = 1024, h = 768 },
		{ name = "pc", w = 1920, h = 1080 },
	} :: { Viewport },
}

local ALL_DETECTORS = {
	"floating",
	"near_miss_gap",
	"z_fighting",
	"interpenetration",
	"off_grid",
	"scale",
	"stretched_texture",
	"text_overflow",
	"ui_off_screen",
	"contrast",
	"touch_target",
	"unreachable",
}
Xray.DETECTORS = ALL_DETECTORS

local SEVERITY_RANK = { high = 3, medium = 2, low = 1 }
local abs, sqrt, floor, min, max = math.abs, math.sqrt, math.floor, math.min, math.max

-- --------------------------------------------------------------------------- small helpers

local function get(inst: any, prop: string, default: any): any
	local ok, value = pcall(function()
		return inst[prop]
	end)
	if ok and value ~= nil then
		return value
	end
	return default
end

local function attr(inst: any, name: string): any
	local ok, value = pcall(function()
		return inst:GetAttribute(name)
	end)
	return if ok then value else nil
end

local function ignored(inst: any, stop: any): boolean
	local node = inst
	while node and node ~= stop do
		if attr(node, "XrayIgnore") == true then
			return true
		end
		node = node.Parent
	end
	return false
end

local function enumName(value: any): string
	if value == nil then
		return ""
	end
	local ok, name = pcall(function()
		return value.Name
	end)
	return if ok and type(name) == "string" then name else tostring(value)
end

local function round(x: number, places: number): number
	local m = 10 ^ places
	return floor(x * m + 0.5) / m
end

local function fmt(x: number): string
	local s = string.format("%.3f", x)
	s = string.gsub(s, "0+$", "")
	s = string.gsub(s, "%.$", "")
	return s
end

-- --------------------------------------------------------------------------- report

type Ctx = {
	opts: Options,
	env: Env,
	findings: { Finding },
	changes: { Change },
	targets: { any },
	changed: { [any]: boolean },
	skipped: { [string]: string },
	enabled: { [string]: boolean },
	paths: { [any]: string },
	lastYield: number,
	timings: { [string]: number },
	info: { [string]: any },
}

local function pathOf(ctx: Ctx, inst: any): string
	local cached = ctx.paths[inst]
	if cached then
		return cached
	end
	local ok, name = pcall(function()
		return inst:GetFullName()
	end)
	local path = if ok then name else tostring(inst)
	ctx.paths[inst] = path
	return path
end

local function tick(ctx: Ctx)
	local y = ctx.env.yield
	if y and os.clock() - ctx.lastYield > 0.03 then
		y()
		ctx.lastYield = os.clock()
	end
end

local function add(ctx: Ctx, f: Finding)
	table.insert(ctx.findings, f)
end

local function addChange(ctx: Ctx, f: Finding, inst: any, dx: number, dy: number, dz: number, reason: string)
	-- one change per instance: the first (geometry fixes run before grid snaps) wins
	if not ctx.opts.fixes or ctx.changed[inst] then
		return
	end
	ctx.changed[inst] = true
	table.insert(ctx.changes, {
		op = "translate",
		path = pathOf(ctx, inst),
		dx = round(dx, 6),
		dy = round(dy, 6),
		dz = round(dz, 6),
		reason = reason,
	})
	table.insert(ctx.targets, inst)
	f.change = #ctx.changes
end

-- --------------------------------------------------------------------------- parts -> plain records

local function collectParts(ctx: Ctx, root: any): { Rec }
	local recs: { Rec } = {}
	local descendants = root:GetDescendants()
	for _, inst in descendants do
		if inst:IsA("BasePart") and inst.ClassName ~= "Terrain" and not ignored(inst, root) then
			local cf = inst.CFrame
			local size = inst.Size
			local x, y, z, r00, r01, r02, r10, r11, r12, r20, r21, r22 = cf:GetComponents()
			local hx, hy, hz = size.X / 2, size.Y / 2, size.Z / 2
			local ex = abs(r00) * hx + abs(r01) * hy + abs(r02) * hz
			local ey = abs(r10) * hx + abs(r11) * hy + abs(r12) * hz
			local ez = abs(r20) * hx + abs(r21) * hy + abs(r22) * hz
			local ax = { r00, r10, r20, r01, r11, r21, r02, r12, r22 }
			local aligned = true
			for k = 1, 9 do
				local v = abs(ax[k])
				if v > 1e-4 and abs(v - 1) > 1e-4 then
					aligned = false
					break
				end
			end
			local block = inst.ClassName == "Part" and enumName(get(inst, "Shape", nil)) == "Block"
				or inst.ClassName == "SpawnLocation"
			local transparency = get(inst, "Transparency", 0)
			local color = get(inst, "Color", nil)
			local look = (if color then string.format("%.3f,%.3f,%.3f", color.R, color.G, color.B) else "?")
				.. "/"
				.. enumName(get(inst, "Material", nil))
			local canCollide = get(inst, "CanCollide", true)
			local rec: Rec = {
				i = #recs + 1,
				inst = inst,
				name = inst.Name,
				cx = x,
				cy = y,
				cz = z,
				ax = ax,
				h = { hx, hy, hz },
				minx = x - ex,
				miny = y - ey,
				minz = z - ez,
				maxx = x + ex,
				maxy = y + ey,
				maxz = z + ez,
				block = block,
				visible = transparency < 0.99,
				solid = canCollide or transparency < 0.99,
				collide = canCollide,
				look = look,
				vol = size.X * size.Y * size.Z,
				aligned = aligned,
				queryable = canCollide or get(inst, "CanQuery", true),
			}
			table.insert(recs, rec)
			if #recs % 500 == 0 then
				tick(ctx)
			end
		end
	end
	return recs
end

-- --------------------------------------------------------------------------- geometry

local R = table.create(9, 0)
local AR = table.create(9, 0)
local T = table.create(3, 0)

-- Separating-axis test for two oriented boxes. > 0: separation along the best axis (a lower bound of the
-- true distance); <= 0: minus the smallest penetration depth over the 15 axes.
local function obbSep(a: Rec, b: Rec): number
	local A, B, ha, hb = a.ax, b.ax, a.h, b.h
	local tx, ty, tz = b.cx - a.cx, b.cy - a.cy, b.cz - a.cz
	for i = 0, 2 do
		local a1, a2, a3 = A[i * 3 + 1], A[i * 3 + 2], A[i * 3 + 3]
		T[i + 1] = tx * a1 + ty * a2 + tz * a3
		for j = 0, 2 do
			local v = a1 * B[j * 3 + 1] + a2 * B[j * 3 + 2] + a3 * B[j * 3 + 3]
			R[i * 3 + j + 1] = v
			AR[i * 3 + j + 1] = abs(v) + 1e-9
		end
	end
	local best = -math.huge
	for i = 0, 2 do
		local rb = hb[1] * AR[i * 3 + 1] + hb[2] * AR[i * 3 + 2] + hb[3] * AR[i * 3 + 3]
		local s = abs(T[i + 1]) - (ha[i + 1] + rb)
		if s > best then
			best = s
		end
	end
	for j = 0, 2 do
		local ra = ha[1] * AR[j + 1] + ha[2] * AR[3 + j + 1] + ha[3] * AR[6 + j + 1]
		local tj = T[1] * R[j + 1] + T[2] * R[3 + j + 1] + T[3] * R[6 + j + 1]
		local s = abs(tj) - (ra + hb[j + 1])
		if s > best then
			best = s
		end
	end
	for i = 0, 2 do
		local i1, i2 = (i + 1) % 3, (i + 2) % 3
		for j = 0, 2 do
			local rij = R[i * 3 + j + 1]
			local len = 1 - rij * rij
			if len > 1e-10 then
				len = sqrt(len)
				local j1, j2 = (j + 1) % 3, (j + 2) % 3
				local ra = ha[i1 + 1] * AR[i2 * 3 + j + 1] + ha[i2 + 1] * AR[i1 * 3 + j + 1]
				local rb = hb[j1 + 1] * AR[i * 3 + j2 + 1] + hb[j2 + 1] * AR[i * 3 + j1 + 1]
				local tv = T[i2 + 1] * R[i1 * 3 + j + 1] - T[i1 + 1] * R[i2 * 3 + j + 1]
				local s = (abs(tv) - (ra + rb)) / len
				if s > best then
					best = s
				end
			end
		end
	end
	return best
end
Xray._obbSep = obbSep

local function inside(r: Rec, px: number, py: number, pz: number): boolean
	local dx, dy, dz = px - r.cx, py - r.cy, pz - r.cz
	local A = r.ax
	for i = 0, 2 do
		local d = dx * A[i * 3 + 1] + dy * A[i * 3 + 2] + dz * A[i * 3 + 3]
		if abs(d) > r.h[i + 1] + 1e-6 then
			return false
		end
	end
	return true
end

-- Share of the smaller box's volume inside the larger one, sampled on a 5x5x5 grid of cell centres.
local function overlapFraction(small: Rec, big: Rec): number
	local A, h = small.ax, small.h
	local hit = 0
	for u = 0, 4 do
		local fu = ((u + 0.5) / 5 * 2 - 1) * h[1]
		for v = 0, 4 do
			local fv = ((v + 0.5) / 5 * 2 - 1) * h[2]
			for w = 0, 4 do
				local fw = ((w + 0.5) / 5 * 2 - 1) * h[3]
				local px = small.cx + A[1] * fu + A[4] * fv + A[7] * fw
				local py = small.cy + A[2] * fu + A[5] * fv + A[8] * fw
				local pz = small.cz + A[3] * fu + A[6] * fv + A[9] * fw
				if inside(big, px, py, pz) then
					hit += 1
				end
			end
		end
	end
	return hit / 125
end

-- --------------------------------------------------------------------------- spatial hash

type Hash = {
	cell: number,
	cells: { [number]: { number } },
	big: { number },
	isBig: { [number]: boolean },
	recs: { Rec },
	stamp: { number },
	stampId: number,
}

local OFF = 32768
local function cellKey(ix: number, iy: number, iz: number): number
	return ((ix + OFF) * 65536 + (iy + OFF)) * 65536 + (iz + OFF)
end

local function clampCell(v: number): number
	return max(-OFF + 1, min(OFF - 1, v))
end

local function buildHash(ctx: Ctx, recs: { Rec }, cellOpt: number?): Hash
	local cell = cellOpt
	if not cell then
		local sizes = {}
		for _, r in recs do
			table.insert(sizes, max(r.maxx - r.minx, r.maxy - r.miny, r.maxz - r.minz))
		end
		table.sort(sizes)
		cell = if #sizes > 0 then max(2, min(32, sizes[floor(#sizes / 2) + 1])) else 4
	end
	local c = cell :: number
	local hash: Hash = {
		cell = c,
		cells = {},
		big = {},
		isBig = {},
		recs = recs,
		stamp = table.create(#recs, 0),
		stampId = 0,
	}
	for _, r in recs do
		local x0, x1 = clampCell(floor(r.minx / c)), clampCell(floor(r.maxx / c))
		local y0, y1 = clampCell(floor(r.miny / c)), clampCell(floor(r.maxy / c))
		local z0, z1 = clampCell(floor(r.minz / c)), clampCell(floor(r.maxz / c))
		if (x1 - x0 + 1) * (y1 - y0 + 1) * (z1 - z0 + 1) > 512 then
			table.insert(hash.big, r.i)
			hash.isBig[r.i] = true
		else
			for ix = x0, x1 do
				for iy = y0, y1 do
					for iz = z0, z1 do
						local key = cellKey(ix, iy, iz)
						local list = hash.cells[key]
						if list then
							table.insert(list, r.i)
						else
							hash.cells[key] = { r.i }
						end
					end
				end
			end
		end
		if r.i % 1000 == 0 then
			tick(ctx)
		end
	end
	return hash
end

-- All record indices whose AABB may touch the query box (big parts always included).
local function query(hash: Hash, minx: number, miny: number, minz: number, maxx: number, maxy: number, maxz: number): { number }
	local c = hash.cell
	hash.stampId += 1
	local id, stamp, out = hash.stampId, hash.stamp, {}
	local x0, x1 = clampCell(floor(minx / c)), clampCell(floor(maxx / c))
	local y0, y1 = clampCell(floor(miny / c)), clampCell(floor(maxy / c))
	local z0, z1 = clampCell(floor(minz / c)), clampCell(floor(maxz / c))
	if (x1 - x0 + 1) * (y1 - y0 + 1) * (z1 - z0 + 1) > 4096 then
		for _, r in hash.recs do
			table.insert(out, r.i)
		end
		return out
	end
	for ix = x0, x1 do
		for iy = y0, y1 do
			for iz = z0, z1 do
				local list = hash.cells[cellKey(ix, iy, iz)]
				if list then
					for _, j in list do
						if stamp[j] ~= id then
							stamp[j] = id
							table.insert(out, j)
						end
					end
				end
			end
		end
	end
	for _, j in hash.big do
		table.insert(out, j)
	end
	return out
end

local function aabbNear(a: Rec, b: Rec, m: number): boolean
	return a.minx - m <= b.maxx and b.minx - m <= a.maxx and a.miny - m <= b.maxy and b.miny - m <= a.maxy
		and a.minz - m <= b.maxz and b.minz - m <= a.maxz
end

-- Calls visit(a, b) once for every pair whose boxes come within `margin`.
local function forPairs(ctx: Ctx, recs: { Rec }, hash: Hash, margin: number, visit: (Rec, Rec) -> ())
	local engine = ctx.env.partsInBox
	local index: { [any]: number } = {}
	if engine then
		for _, r in recs do
			index[r.inst] = r.i
		end
	end
	local count = 0
	for _, a in recs do
		local engineOk = false
		if engine and a.queryable then
			-- Engine spatial query (Studio). Pairs with a non-queryable part come from the hash below.
			local ok, parts = pcall(engine, a.inst, margin)
			if ok then
				engineOk = true
				for _, p in parts do
					local j = index[p]
					if j and j > a.i and recs[j].queryable then
						local b = recs[j]
						if aabbNear(a, b, margin) then
							visit(a, b)
							count += 1
						end
					end
				end
			end
		end
		local candidates = query(hash, a.minx - margin, a.miny - margin, a.minz - margin, a.maxx + margin, a.maxy + margin, a.maxz + margin)
		for _, j in candidates do
			if j ~= a.i then
				local b = recs[j]
				-- Each unordered pair once: big parts are not in cells, so big-vs-small pairs come from the small side.
				local mine = if hash.isBig[a.i] == hash.isBig[j] then j > a.i else hash.isBig[j] == true
				if mine then
					local engineCovered = engineOk and b.queryable
					if not engineCovered and aabbNear(a, b, margin) then
						visit(a, b)
						count += 1
					end
				end
			end
		end
		if a.i % 200 == 0 then
			tick(ctx)
		end
	end
	ctx.info.pairs = count
end

-- --------------------------------------------------------------------------- face analysis (blocks only)

-- Parallel face pairs of two blocks: near-miss gaps (opposite faces a hair apart) and z-fighting
-- (same-facing faces in one plane, overlapping).
local function faceChecks(ctx: Ctx, a: Rec, b: Rec)
	local o = ctx.opts
	local A, B = a.ax, b.ax
	local tx, ty, tz = b.cx - a.cx, b.cy - a.cy, b.cz - a.cz
	local bestArea, bestDist, bestSign, bx, by, bz = 0, 0, 0, 0, 0, 0
	for i = 0, 2 do
		local nx, ny, nz = A[i * 3 + 1], A[i * 3 + 2], A[i * 3 + 3]
		for j = 0, 2 do
			local d = nx * B[j * 3 + 1] + ny * B[j * 3 + 2] + nz * B[j * 3 + 3]
			if abs(d) > 0.9999 then
				local ha, hb = a.h[i + 1], b.h[j + 1]
				local tn = tx * nx + ty * ny + tz * nz
				-- lateral overlap of the two face rectangles, in A's other two axes
				local okLat, ou, ov = true, 0, 0
				for step = 1, 2 do
					local k = (i + step) % 3
					local ux, uy, uz = A[k * 3 + 1], A[k * 3 + 2], A[k * 3 + 3]
					local e = 0
					for m = 0, 2 do
						e += abs(ux * B[m * 3 + 1] + uy * B[m * 3 + 2] + uz * B[m * 3 + 3]) * b.h[m + 1]
					end
					local tu = tx * ux + ty * uy + tz * uz
					local lo, hi = max(-a.h[k + 1], tu - e), min(a.h[k + 1], tu + e)
					local len = hi - lo
					if step == 1 then
						ou = len
					else
						ov = len
					end
					if len <= 0 then
						okLat = false
					end
				end
				if okLat then
					-- gaps: B beyond A's +face, or below A's -face
					local gapPlus = (tn - hb) - ha
					local gapMinus = -ha - (tn + hb)
					for side = 1, 2 do
						local gap = if side == 1 then gapPlus else gapMinus
						if gap >= o.gapMin and gap <= o.gapMax and ou > o.minFaceOverlap and ov > o.minFaceOverlap then
							local sign = if side == 1 then 1 else -1
							local small, other, dir = b, a, -sign
							if a.vol < b.vol then
								small, other, dir = a, b, sign
							end
							local f: Finding = {
								detector = "near_miss_gap",
								-- a hair-thin gap is almost always accidental; from 0.05 it may be deliberate
								severity = if gap < 0.05 then "medium" else "low",
								path = pathOf(ctx, small.inst),
								partner = pathOf(ctx, other.inst),
								value = round(gap, 4),
								unit = "studs",
								message = string.format("%s is %s studs away from %s (faces almost touch: light leak / seam).",
									small.name, fmt(gap), other.name),
								fix = string.format("Move %s %s studs to close the gap, or open it to a deliberate width.", small.name, fmt(gap)),
							}
							add(ctx, f)
							addChange(ctx, f, small.inst, dir * gap * nx, dir * gap * ny, dir * gap * nz, "close near-miss gap")
						end
					end
					-- z-fighting: same-facing coplanar faces (B's face along n: centre tn +/- hb)
					if ou > 0.02 and ov > 0.02 and ou * ov >= o.zMinArea and a.visible and b.visible then
						for side = 1, 2 do
							local sign = if side == 1 then 1 else -1
							local pa, pb = sign * ha, tn + sign * hb
							local dist = abs(pa - pb)
							if dist <= o.coplanarTol and ou * ov > bestArea then
								bestArea, bestDist, bestSign, bx, by, bz = ou * ov, dist, sign, nx, ny, nz
							end
						end
					end
				end
			end
		end
	end
	if bestArea > 0 then
		local small, other = a, b
		if b.vol < a.vol then
			small, other = b, a
		end
		local same = a.look == b.look
		local f: Finding = {
			detector = "z_fighting",
			severity = if same or bestArea < 0.25 then "low" else "high",
			path = pathOf(ctx, small.inst),
			partner = pathOf(ctx, other.inst),
			value = round(bestArea, 4),
			unit = "sq studs",
			message = string.format("%s and %s share a face plane (%s apart) over %s sq studs: the surfaces flicker%s.",
				small.name, other.name, fmt(bestDist), fmt(bestArea), if same then " (same colour and material, so barely visible)" else ""),
			fix = string.format("Nudge %s %s studs outward along the face normal, or shrink it inside the other part.",
				small.name, fmt(o.zNudge)),
		}
		add(ctx, f)
		local nudge = o.zNudge * bestSign
		addChange(ctx, f, small.inst, nudge * bx, nudge * by, nudge * bz, "separate coplanar faces")
	end
end

-- --------------------------------------------------------------------------- 3D detectors

local function find(parent: { [number]: number }, x: number): number
	while parent[x] ~= x do
		parent[x] = parent[parent[x]]
		x = parent[x]
	end
	return x
end

local function geometry(ctx: Ctx, recs: { Rec }, hash: Hash)
	local o, en = ctx.opts, ctx.enabled
	local parent: { number } = table.create(#recs, 0)
	for k = 1, #recs do
		parent[k] = k
	end
	local function union(a: number, b: number)
		local ra, rb = find(parent, a), find(parent, b)
		if ra ~= rb then
			parent[ra] = rb
		end
	end
	local margin = max(o.supportEps, o.gapMax) + 0.01
	local t0 = os.clock()
	forPairs(ctx, recs, hash, margin, function(a: Rec, b: Rec)
		local sep = obbSep(a, b)
		if sep <= o.supportEps and a.solid and b.solid then
			union(a.i, b.i)
		end
		if a.block and b.block and sep <= o.gapMax + 1e-6 and (en.near_miss_gap or en.z_fighting) then
			faceChecks(ctx, a, b)
		end
		-- blocks only: the box of a mesh, union or wedge is not its shape
		if en.interpenetration and sep < -o.penDepth and a.block and b.block and a.visible and b.visible then
			local small, big = a, b
			if b.vol < a.vol then
				small, big = b, a
			end
			local frac = overlapFraction(small, big)
			if frac >= o.penFraction then
				local hidden = frac >= 0.999
				add(ctx, {
					detector = "interpenetration",
					-- same colour and material merge seamlessly (a common building technique)
					severity = if hidden or a.look == b.look then "low" elseif frac >= 0.5 then "high" else "medium",
					path = pathOf(ctx, small.inst),
					partner = pathOf(ctx, big.inst),
					value = round(frac * 100, 1),
					unit = "% of volume",
					message = if hidden
						then string.format("%s is entirely inside %s: hidden, wasted part (unless a face is flush, see z_fighting).",
							small.name, big.name)
						else string.format("%s is %d%% inside %s (penetration depth %s studs).", small.name,
							floor(frac * 100 + 0.5), big.name, fmt(-sep)),
					fix = string.format("Move %s out of %s by about %s studs, or cut one of them.", small.name, big.name, fmt(-sep)),
				})
			end
		end
	end)
	ctx.timings.pairs = os.clock() - t0

	-- welds and joints connect parts that do not touch
	local index: { [any]: number } = {}
	for _, r in recs do
		index[r.inst] = r.i
	end
	local root = ctx.info.partsRoot
	for _, inst in root:GetDescendants() do
		if inst:IsA("WeldConstraint") or inst:IsA("JointInstance") or inst:IsA("RigidConstraint") then
			local p0 = get(inst, "Part0", nil)
			local p1 = get(inst, "Part1", nil)
			if p0 and p1 and index[p0] and index[p1] then
				union(index[p0], index[p1])
			end
		end
	end

	if en.floating then
		local groundY = o.groundY
		if groundY == nil then
			groundY = math.huge
			for _, r in recs do
				if r.solid and r.miny < groundY then
					groundY = r.miny
				end
			end
		end
		local grounded: { [number]: boolean } = {}
		local onTerrain = ctx.env.onTerrain
		for _, r in recs do
			if r.solid and (r.miny <= groundY + o.supportEps or (onTerrain and onTerrain(r.cx, r.miny, r.cz))) then
				grounded[find(parent, r.i)] = true
			end
		end
		local comps: { [number]: { Rec } } = {}
		for _, r in recs do
			local root2 = find(parent, r.i)
			if r.solid and not grounded[root2] then
				local list = comps[root2]
				if list then
					table.insert(list, r)
				else
					comps[root2] = { r }
				end
			end
		end
		local terrainBlind = ctx.info.terrain and not onTerrain
		local terrainSkipped = 0
		for compRoot, list in comps do
			-- report groups with a visible, collidable part; non-collidable floaters (coins, effects) are usually art
			local visible = false
			for _, r in list do
				if r.visible and r.collide then
					visible = true
				end
			end
			if visible then
				local biggest, lowest = list[1], list[1]
				for _, r in list do
					if r.vol > biggest.vol then
						biggest = r
					end
					if r.miny < lowest.miny then
						lowest = r
					end
				end
				-- how far it would drop to the surface below it
				local surface, onPart = groundY, false
				for _, j in query(hash, lowest.minx, groundY - 1, lowest.minz, lowest.maxx, lowest.miny, lowest.maxz) do
					local s = recs[j]
					if find(parent, j) ~= compRoot and s.solid and s.maxy <= lowest.miny + 1e-6 and s.maxy > surface
						and s.minx < lowest.maxx and s.maxx > lowest.minx and s.minz < lowest.maxz and s.maxz > lowest.minz then
						surface, onPart = s.maxy, true
					end
				end
				local drop = lowest.miny - surface
				if terrainBlind and not onPart then
					-- nothing but terrain could be under it, and headless cannot read terrain voxels
					terrainSkipped += 1
					continue
				end
				local members = {}
				for k, r in list do
					if k > 20 then
						break
					end
					table.insert(members, pathOf(ctx, r.inst))
				end
				add(ctx, {
					detector = "floating",
					severity = "high",
					path = pathOf(ctx, biggest.inst),
					members = members,
					value = round(drop, 3),
					unit = "studs above support",
					message = string.format("%s%s touches nothing that reaches the ground (nearest surface %s studs below).",
						biggest.name, if #list > 1 then string.format(" (group of %d parts)", #list) else "", fmt(drop)),
					fix = string.format("Lower it %s studs onto the surface below, attach it (weld) to a supported part, or mark it XrayIgnore if it floats on purpose.", fmt(drop)),
				})
			end
		end
		if terrainSkipped > 0 then
			ctx.skipped.floating = string.format("%d groups over terrain not judged (headless cannot read terrain; use Studio mode)", terrainSkipped)
		end
	end
end

local GRIDS = { 4, 2, 1, 0.5, 0.25, 0.2, 0.125, 0.1, 0.05 }

local function gridOffset(v: number, g: number): number
	return v - floor(v / g + 0.5) * g
end

-- smallest move that puts the min corner, the centre or the max corner of one axis on the grid
local function axisSnap(lo: number, hi: number, g: number): number
	local best = gridOffset(lo, g)
	for _, v in { (lo + hi) / 2, hi } do
		local off = gridOffset(v, g)
		if abs(off) < abs(best) then
			best = off
		end
	end
	return best
end

local function offGrid(ctx: Ctx, recs: { Rec })
	local o = ctx.opts
	local aligned: { Rec } = {}
	local near: { Rec } = {}
	for _, r in recs do
		if r.visible then
			if r.aligned then
				table.insert(aligned, r)
			else
				table.insert(near, r)
			end
		end
	end
	local total = #aligned + #near
	if #aligned < 10 or #aligned / total < 0.5 then
		ctx.skipped.off_grid = "fewer than 10 axis-aligned visible parts"
		return
	end
	-- the coarsest grid that most parts sit on, unless a finer grid explains clearly more of them
	local shares = {}
	for gi, g in GRIDS do
		local on = 0
		for _, r in aligned do
			if abs(axisSnap(r.minx, r.maxx, g)) <= o.gridTol and abs(axisSnap(r.miny, r.maxy, g)) <= o.gridTol
				and abs(axisSnap(r.minz, r.maxz, g)) <= o.gridTol then
				on += 1
			end
		end
		shares[gi] = on / #aligned
	end
	local chosen: number? = nil
	for gi, g in GRIDS do
		local finer = shares[gi + 1] or shares[gi]
		if shares[gi] >= o.gridShare and finer - shares[gi] <= o.gridGain then
			chosen = g
			ctx.info.gridShare = round(shares[gi], 3)
			break
		end
	end
	ctx.info.grid = chosen
	if chosen then
		local g = chosen :: number
		for _, r in aligned do
			local dx, dy, dz = axisSnap(r.minx, r.maxx, g), axisSnap(r.miny, r.maxy, g), axisSnap(r.minz, r.maxz, g)
			local worst = max(abs(dx), abs(dy), abs(dz))
			if worst > o.gridTol then
				local f: Finding = {
					detector = "off_grid",
					severity = "medium",
					path = pathOf(ctx, r.inst),
					value = round(worst, 4),
					unit = "studs off grid",
					message = string.format("%s is %s studs off the %s-stud grid that %d%% of the build uses.", r.name,
						fmt(worst), fmt(g), floor((ctx.info.gridShare or 0) * 100)),
					fix = string.format("Move it by (%s, %s, %s) to snap it to the grid.", fmt(-dx), fmt(-dy), fmt(-dz)),
				}
				add(ctx, f)
				addChange(ctx, f, r.inst, -dx, -dy, -dz, "snap to grid")
			end
		end
	else
		ctx.info.grid = "none"
	end
	-- rotation a hair away from a right angle, when nearly everything is axis-aligned
	if #aligned / total >= 0.8 then
		for _, r in near do
			local dev = 0
			for i = 0, 2 do
				-- angle from the off-axis part (asin): float32 rounds the cosine of a small turn to exactly 1
				local x, y, z = abs(r.ax[i * 3 + 1]), abs(r.ax[i * 3 + 2]), abs(r.ax[i * 3 + 3])
				local m = max(x, y, z)
				local off = sqrt(max(0, x * x + y * y + z * z - m * m))
				dev = max(dev, math.deg(math.asin(min(1, off))))
			end
			if dev >= o.rotMinDeg and dev <= o.rotMaxDeg then
				add(ctx, {
					detector = "off_grid",
					severity = "medium",
					path = pathOf(ctx, r.inst),
					value = round(dev, 3),
					unit = "degrees off right angle",
					message = string.format("%s is rotated %s degrees off a right angle while the build is axis-aligned.", r.name, fmt(dev)),
					fix = "Set its orientation to the nearest multiple of 90 degrees.",
				})
			end
		end
	end
end

-- --------------------------------------------------------------------------- scale vs avatar

local function roleOf(inst: any): string?
	local r = attr(inst, "XrayRole")
	if type(r) == "string" then
		return r
	end
	local n = string.lower(inst.Name)
	if string.find(n, "door", 1, true) then
		for _, bad in { "frame", "knob", "handle", "mat", "bell", "way", "stop", "hinge", "sign", "step", "lock", "crown",
			"trim", "arch", "plate", "window", "light", "lamp", "number", "glass", "panel", "top", "casing", "jamb", "sill", "lintel", "header", "threshold", "mould",
			"molding", "bell" } do
			if string.find(n, bad, 1, true) then
				return nil
			end
		end
		return "Door"
	end
	if string.find(n, "stair", 1, true) then
		return "Stairs"
	end
	for _, word in { "railing", "handrail", "guardrail", "balustrade" } do
		if string.find(n, word, 1, true) then
			return "Railing"
		end
	end
	if string.match(n, "^floor[%d_ ]*$") or string.match(n, "^ground[%d_ ]*$") or string.match(n, "^slab") then
		return "Floor"
	end
	if string.match(n, "^ceiling") or string.match(n, "^roof") then
		return "Ceiling"
	end
	return nil
end

type Box = { minx: number, miny: number, minz: number, maxx: number, maxy: number, maxz: number }

local function boxOf(inst: any, byInst: { [any]: Rec }): (Box?, { Rec })
	local parts: { Rec } = {}
	local own = byInst[inst]
	if own then
		table.insert(parts, own)
	else
		for _, d in inst:GetDescendants() do
			local r = byInst[d]
			if r then
				table.insert(parts, r)
			end
		end
	end
	if #parts == 0 then
		return nil, parts
	end
	local b: Box = { minx = math.huge, miny = math.huge, minz = math.huge, maxx = -math.huge, maxy = -math.huge, maxz = -math.huge }
	for _, r in parts do
		b.minx, b.miny, b.minz = min(b.minx, r.minx), min(b.miny, r.miny), min(b.minz, r.minz)
		b.maxx, b.maxy, b.maxz = max(b.maxx, r.maxx), max(b.maxy, r.maxy), max(b.maxz, r.maxz)
	end
	return b, parts
end

local function scale(ctx: Ctx, recs: { Rec }, hash: Hash)
	local o = ctx.opts
	local av = ctx.env.avatar or Xray.AVATAR
	ctx.info.avatar = av
	local byInst: { [any]: Rec } = {}
	for _, r in recs do
		byInst[r.inst] = r
	end
	local root = ctx.info.partsRoot
	local floors, ceilings = {}, {}
	for _, inst in root:GetDescendants() do
		local role = roleOf(inst)
		if role and not ignored(inst, root) then
			local isPart = byInst[inst] ~= nil
			local isGroup = inst:IsA("Model") or inst:IsA("Folder")
			if role == "Door" and (isPart or isGroup) and not (isPart and inst.Parent and roleOf(inst.Parent) == "Door") then
				local b = boxOf(inst, byInst)
				if b then
					local height = b.maxy - b.miny
					local width = max(b.maxx - b.minx, b.maxz - b.minz)
					local r = byInst[inst]
					if r and not r.aligned then
						-- rotated door part: use its own axes (the most vertical one is the height)
						local up, best = 1, -1
						for i = 0, 2 do
							if abs(r.ax[i * 3 + 2]) > best then
								best, up = abs(r.ax[i * 3 + 2]), i + 1
							end
						end
						height = r.h[up] * 2
						width = 0
						for i = 1, 3 do
							if i ~= up then
								width = max(width, r.h[i] * 2)
							end
						end
					end
					local path = pathOf(ctx, inst)
					-- a door-named box that is not door-shaped is trim or a prop, not an opening
					local doorShaped = height >= 2 and width >= 1 and height >= width * 0.8
					if doorShaped and height < av.heightMax * 1.08 then
						add(ctx, {
							detector = "scale",
							severity = if height < av.heightMax then "high" else "medium",
							path = path,
							value = round(height, 3),
							unit = "studs tall",
							message = string.format("Door %s is %s studs tall; R15 avatars are up to %s studs (Normal body scale), Classic %s.",
								inst.Name, fmt(height), fmt(av.heightMax), fmt(av.heightClassic)),
							fix = string.format("Make the opening at least %s studs tall.", fmt(math.ceil(av.heightMax * 1.08 * 2) / 2)),
						})
					end
					if doorShaped and width < av.width then
						add(ctx, {
							detector = "scale",
							severity = if width < 2 then "high" else "medium",
							path = path,
							value = round(width, 3),
							unit = "studs wide",
							message = string.format("Door %s is %s studs wide; a default R15 avatar is %s studs across the shoulders (root part 2), so arms clip the frame%s.",
								inst.Name, fmt(width), fmt(av.width), if width < 2 then " and the avatar cannot pass" else ""),
							fix = string.format("Make the opening at least %s studs wide.", fmt(av.width + 0.5)),
						})
					end
				end
			elseif role == "Stairs" and isGroup then
				local _, parts = boxOf(inst, byInst)
				local steps = {}
				for _, r in parts do
					if r.visible and r.block then -- a mesh's box top is not a tread
						table.insert(steps, r)
					end
				end
				table.sort(steps, function(p: Rec, q: Rec)
					return p.maxy < q.maxy
				end)
				local risers, treads = {}, {}
				for k = 2, #steps do
					local rise = steps[k].maxy - steps[k - 1].maxy
					if rise > 0.05 then
						table.insert(risers, { rise = rise, lo = steps[k - 1], hi = steps[k] })
						local dx, dz = steps[k].cx - steps[k - 1].cx, steps[k].cz - steps[k - 1].cz
						table.insert(treads, sqrt(dx * dx + dz * dz))
					end
				end
				if #risers >= 2 then
					local sorted = {}
					for _, r in risers do
						table.insert(sorted, r.rise)
					end
					table.sort(sorted)
					local median = sorted[floor(#sorted / 2) + 1]
					local hi, lo = sorted[#sorted], sorted[1]
					local path = pathOf(ctx, inst)
					if hi > o.riserMax then
						add(ctx, {
							detector = "scale",
							severity = if hi > o.riserHigh then "high" else "medium",
							path = path,
							value = round(hi, 3),
							unit = "studs riser",
							message = string.format("Stairs %s have a %s-stud step; the comfortable maximum used here is %s studs (R15 avatar %s studs tall).",
								inst.Name, fmt(hi), fmt(o.riserMax), fmt(av.height)),
							fix = "Use more, lower steps (about 1 stud each).",
						})
					end
					if hi - lo > o.riserUneven then
						local members, worst, worstDev = {}, nil, -1
						for _, r in risers do
							local dev = abs(r.rise - median)
							if dev > o.riserUneven then
								table.insert(members, pathOf(ctx, r.lo.inst))
								table.insert(members, pathOf(ctx, r.hi.inst))
							end
							if dev > worstDev then
								worstDev, worst = dev, r
							end
						end
						add(ctx, {
							detector = "scale",
							severity = "medium",
							path = path,
							partner = if worst then pathOf(ctx, worst.hi.inst) else nil,
							members = members,
							value = round(hi - lo, 3),
							unit = "studs riser spread",
							message = string.format("Stairs %s have uneven steps: risers from %s to %s studs (median %s).", inst.Name,
								fmt(lo), fmt(hi), fmt(median)),
							fix = "Make every riser the same height.",
						})
					end
					local shortest = math.huge
					for _, t in treads do
						shortest = min(shortest, t)
					end
					if shortest < o.treadMin then
						add(ctx, {
							detector = "scale",
							severity = "medium",
							path = path,
							value = round(shortest, 3),
							unit = "studs tread",
							message = string.format("Stairs %s have a %s-stud tread; less than %s stud is hard to land on.", inst.Name,
								fmt(shortest), fmt(o.treadMin)),
							fix = "Make each tread at least 1 stud deep.",
						})
					end
				end
			elseif role == "Railing" and (isPart or isGroup) and not (isPart and inst.Parent and roleOf(inst.Parent) == "Railing") then
				local b = boxOf(inst, byInst)
				if b then
					local cx, cz = (b.minx + b.maxx) / 2, (b.minz + b.maxz) / 2
					local walk = -math.huge
					for _, j in query(hash, cx - 0.01, b.miny - 2, cz - 0.01, cx + 0.01, b.miny + 0.3, cz + 0.01) do
						local s = recs[j]
						if roleOf(s.inst) ~= "Railing" and s.solid and s.maxy <= b.miny + 0.3 and s.maxy > walk
							and s.minx <= cx and s.maxx >= cx and s.minz <= cz and s.maxz >= cz then
							walk = s.maxy
						end
					end
					if walk == -math.huge then
						walk = b.miny
					end
					local height = b.maxy - walk
					local path = pathOf(ctx, inst)
					if height < o.railMin then
						add(ctx, {
							detector = "scale",
							severity = if height < o.railHigh then "high" else "medium",
							path = path,
							value = round(height, 3),
							unit = "studs railing height",
							message = string.format("Railing %s is %s studs above the walkway; below about %s studs it is under an R15 avatar's hip (avatar %s studs).",
								inst.Name, fmt(height), fmt(o.railMin), fmt(av.height)),
							fix = "Raise the railing to about 3-3.5 studs.",
						})
					elseif height > o.railMax then
						add(ctx, {
							detector = "scale",
							severity = "low",
							path = path,
							value = round(height, 3),
							unit = "studs railing height",
							message = string.format("Railing %s is %s studs tall, about head height for an R15 avatar (%s studs).",
								inst.Name, fmt(height), fmt(av.height)),
							fix = "Lower the railing to about 3-3.5 studs.",
						})
					end
				end
			elseif role == "Floor" and isPart then
				table.insert(floors, byInst[inst])
			elseif role == "Ceiling" and isPart then
				table.insert(ceilings, byInst[inst])
			end
		end
		tick(ctx)
	end
	-- ceiling clearance: lowest ceiling/roof/upper floor above five points of every floor
	local overhead: { [Rec]: boolean } = {}
	for _, r in floors do
		overhead[r] = true
	end
	for _, r in ceilings do
		overhead[r] = true
	end
	for _, f in floors do
		local top = f.maxy
		local lowest, lowRec = math.huge, nil
		local w, d = f.maxx - f.minx, f.maxz - f.minz
		for _, s in { { 0, 0 }, { -0.3, -0.3 }, { 0.3, -0.3 }, { -0.3, 0.3 }, { 0.3, 0.3 } } do
			local px, pz = f.cx + s[1] * w, f.cz + s[2] * d
			for _, j in query(hash, px - 0.01, top + 0.5, pz - 0.01, px + 0.01, top + 40, pz + 0.01) do
				local c = recs[j]
				if c ~= f and overhead[c] and c.miny > top + 0.5 and c.miny < lowest and c.minx <= px and c.maxx >= px
					and c.minz <= pz and c.maxz >= pz then
					lowest, lowRec = c.miny, c
				end
			end
		end
		if lowRec then
			local clear = lowest - top
			if clear < av.heightMax * 1.15 then
				add(ctx, {
					detector = "scale",
					severity = if clear < av.heightMax then "high" else "medium",
					path = pathOf(ctx, lowRec.inst),
					partner = pathOf(ctx, f.inst),
					value = round(clear, 3),
					unit = "studs clearance",
					message = string.format("Ceiling %s is %s studs above %s; R15 avatars are up to %s studs tall, and the camera needs room above the head.",
						lowRec.name, fmt(clear), f.name, fmt(av.heightMax)),
					fix = string.format("Raise it to at least %s studs of clearance.", fmt(math.ceil(av.heightMax * 1.15 * 2) / 2)),
				})
			end
		end
	end
end

-- --------------------------------------------------------------------------- textures and decals

local function faceDims(size: any, face: string): (number, number)
	if face == "Top" or face == "Bottom" then
		return size.X, size.Z
	elseif face == "Left" or face == "Right" then
		return size.Z, size.Y
	end
	return size.X, size.Y
end

local function textures(ctx: Ctx)
	local o = ctx.opts
	local root = ctx.info.partsRoot
	for _, inst in root:GetDescendants() do
		local isTexture, isDecal = inst:IsA("Texture"), inst:IsA("Decal")
		local part = inst.Parent
		local boxy = part and (part.ClassName == "Part" and enumName(get(part, "Shape", nil)) == "Block")
		if (isTexture or isDecal) and part and part:IsA("BasePart") and boxy and not ignored(inst, root)
			and get(inst, "Transparency", 0) < 0.99 then
			local aspect = attr(inst, "XrayImageAspect")
			local imageAspect = if type(aspect) == "number" and aspect > 0 then aspect else 1
			local fw, fh = faceDims(part.Size, enumName(get(inst, "Face", nil)))
			local ratio, what
			if isTexture then
				local u, v = get(inst, "StudsPerTileU", 2), get(inst, "StudsPerTileV", 2)
				if u > 0 and v > 0 then
					ratio = (u / v) / imageAspect
					what = string.format("tiles %s x %s studs", fmt(u), fmt(v))
				end
			elseif fh > 0 then
				ratio = (fw / fh) / imageAspect
				what = string.format("fills a %s x %s face", fmt(fw), fmt(fh))
			end
			if ratio and ratio > 0 then
				local stretch = max(ratio, 1 / ratio)
				if stretch >= o.stretchRatio then
					add(ctx, {
						detector = "stretched_texture",
						-- a decal's image may really have the face's proportions; only the tile ratio of a Texture is near-certain
						severity = if isDecal and type(aspect) ~= "number" then "low" elseif stretch >= 2.5 then "high" else "medium",
						path = pathOf(ctx, inst),
						partner = pathOf(ctx, part),
						value = round(stretch, 3),
						unit = "x stretch",
						message = string.format("%s %s on %s %s: the image is stretched %sx (image aspect %s assumed).", inst.ClassName,
							inst.Name, part.Name, what, fmt(stretch), fmt(imageAspect)),
						fix = if isTexture
							then "Set StudsPerTileU and StudsPerTileV to the image's aspect (equal for a square image)."
							else "Put the decal on a face with the image's proportions, or use a Texture with matching StudsPerTile.",
					})
				end
			end
		end
	end
end

-- --------------------------------------------------------------------------- UI layout (UDim2 at any viewport)

local function isGui(inst: any): boolean
	return inst:IsA("GuiObject")
end

local function sortedChildren(parent: any, byOrder: boolean): { any }
	local list = {}
	for _, c in parent:GetChildren() do
		if isGui(c) and get(c, "Visible", true) then
			table.insert(list, c)
		end
	end
	table.sort(list, function(a, b)
		if byOrder then
			local la, lb = get(a, "LayoutOrder", 0), get(b, "LayoutOrder", 0)
			if la ~= lb then
				return la < lb
			end
		end
		return a.Name < b.Name
	end)
	return list
end

local function textMeasure(ctx: Ctx, text: string, size: number, font: any, width: number): (number, number, boolean)
	local exact = ctx.env.textSize
	if exact then
		local ok, w, h = pcall(exact, text, size, font, width)
		if ok and type(w) == "number" then
			return w, h, false
		end
	end
	-- estimate: per-character advance in ems
	local family = string.lower(tostring(get(font, "Family", "")))
	local weight = enumName(get(font, "Weight", nil))
	local mono = string.find(family, "mono", 1, true) ~= nil or string.find(family, "code", 1, true) ~= nil
	local bold = weight == "Bold" or weight == "Heavy" or weight == "ExtraBold" or weight == "SemiBold"
	local function advance(word: string): number
		local wsum = 0
		for _, cp in utf8.codes(word) do
			local ch = utf8.char(cp)
			local em
			if mono then
				em = 0.6
			elseif string.find("iljt.,;:'!|I fr", ch, 1, true) then
				em = 0.3
			elseif string.find("mwMW@", ch, 1, true) then
				em = 0.85
			elseif string.match(ch, "%u") then
				em = 0.65
			elseif string.match(ch, "%d") then
				em = 0.55
			else
				em = 0.52
			end
			wsum += em
		end
		return wsum * size * (if bold then 1.08 else 1)
	end
	local lines, widest = 0, 0
	for line in string.gmatch(text .. "\n", "([^\n]*)\n") do
		if width >= 1e5 then
			lines += 1
			widest = max(widest, advance(line))
		else
			local cur = 0
			lines += 1
			for word in string.gmatch(line, "%S+") do
				local wlen = advance(word)
				local spaced = if cur > 0 then cur + advance(" ") + wlen else wlen
				if spaced > width and cur > 0 then
					lines += 1
					widest = max(widest, cur)
					cur = wlen
				else
					cur = spaced
				end
			end
			widest = max(widest, cur)
		end
	end
	return widest, lines * size, true
end

local function isText(inst: any): boolean
	return inst:IsA("TextLabel") or inst:IsA("TextButton") or inst:IsA("TextBox")
end

local function plainText(inst: any): string
	local text = tostring(get(inst, "Text", ""))
	if get(inst, "RichText", false) then
		text = string.gsub(text, "<[^>]->", "")
	end
	return text
end

local function padding(inst: any, w: number, h: number, k: number): (number, number, number, number)
	local pad = inst:FindFirstChildWhichIsA("UIPadding")
	if not pad then
		return 0, 0, 0, 0
	end
	local function u(name: string, base: number): number
		local d = get(pad, name, nil)
		return if d then d.Scale * base + d.Offset * k else 0
	end
	return u("PaddingLeft", w), u("PaddingTop", h), u("PaddingRight", w), u("PaddingBottom", h)
end

local function constrain(inst: any, w: number, h: number): (number, number)
	local sc = inst:FindFirstChildWhichIsA("UISizeConstraint")
	if sc then
		local mn, mx = get(sc, "MinSize", nil), get(sc, "MaxSize", nil)
		if mx then
			w, h = min(w, mx.X), min(h, mx.Y)
		end
		if mn then
			w, h = max(w, mn.X), max(h, mn.Y)
		end
	end
	local ar = inst:FindFirstChildWhichIsA("UIAspectRatioConstraint")
	if ar then
		local ratio = get(ar, "AspectRatio", 1)
		if ratio > 0 then
			local kind = enumName(get(ar, "AspectType", nil))
			local axis = enumName(get(ar, "DominantAxis", nil))
			if kind == "ScaleWithParentSize" then
				if axis == "Height" then
					w = h * ratio
				else
					h = w / ratio
				end
			elseif h > 0 and w / h > ratio then
				w = h * ratio
			else
				h = w / ratio
			end
		end
	end
	return w, h
end

local function layoutInto(ctx: Ctx, parent: any, content: Rect, visible: boolean, k: number, scroll: boolean, out: { [any]: GuiBox })
	local list = parent:FindFirstChildWhichIsA("UIListLayout")
	local grid = parent:FindFirstChildWhichIsA("UIGridLayout")
	local layout = list or grid
	local children = {}
	for _, c in parent:GetChildren() do
		if isGui(c) then
			table.insert(children, c)
		end
	end
	local sizes: { [any]: { number } } = {}
	for _, c in children do
		local s = get(c, "Size", nil)
		local w = if s then content.w * s.X.Scale + s.X.Offset * k else 0
		local h = if s then content.h * s.Y.Scale + s.Y.Offset * k else 0
		w, h = constrain(c, w, h)
		local uiScale = c:FindFirstChildWhichIsA("UIScale")
		local sk = if uiScale then get(uiScale, "Scale", 1) else 1
		w, h = w * sk, h * sk
		local auto = enumName(get(c, "AutomaticSize", nil))
		if auto ~= "" and auto ~= "None" and isText(c) and not get(c, "TextScaled", false) then
			local tw, th = textMeasure(ctx, plainText(c), get(c, "TextSize", 14) * k * sk, get(c, "FontFace", nil),
				if get(c, "TextWrapped", false) and (auto == "Y") then w else 1e5)
			local pl, pt, pr, pb = padding(c, w, h, k)
			if auto == "X" or auto == "XY" then
				w = max(w, tw + pl + pr)
			end
			if auto == "Y" or auto == "XY" then
				h = max(h, th + pt + pb)
			end
		end
		sizes[c] = { w, h, sk }
	end
	local positions: { [any]: { number } } = {}
	if grid then
		local cs, cp = get(grid, "CellSize", nil), get(grid, "CellPadding", nil)
		local cw = if cs then content.w * cs.X.Scale + cs.X.Offset * k else 100
		local ch = if cs then content.h * cs.Y.Scale + cs.Y.Offset * k else 100
		local px = if cp then content.w * cp.X.Scale + cp.X.Offset * k else 5
		local py = if cp then content.h * cp.Y.Scale + cp.Y.Offset * k else 5
		local horizontal = enumName(get(grid, "FillDirection", nil)) ~= "Vertical"
		local per = if horizontal then max(1, floor((content.w + px) / (cw + px))) else max(1, floor((content.h + py) / (ch + py)))
		local maxCells = get(grid, "FillDirectionMaxCells", 0)
		if maxCells > 0 then
			per = min(per, maxCells)
		end
		local ordered = sortedChildren(parent, enumName(get(grid, "SortOrder", nil)) == "LayoutOrder")
		for idx, c in ordered do
			local n = idx - 1
			local col, row = n % per, floor(n / per)
			if not horizontal then
				col, row = row, col
			end
			positions[c] = { content.x + col * (cw + px), content.y + row * (ch + py) }
			sizes[c] = { cw, ch, sizes[c][3] }
		end
	elseif list then
		local vertical = enumName(get(list, "FillDirection", nil)) ~= "Horizontal"
		local pad = get(list, "Padding", nil)
		local gap = if pad then (if vertical then content.h else content.w) * pad.Scale + pad.Offset * k else 0
		local ordered = sortedChildren(parent, enumName(get(list, "SortOrder", nil)) == "LayoutOrder")
		local total = 0
		for idx, c in ordered do
			total += if vertical then sizes[c][2] else sizes[c][1]
			if idx > 1 then
				total += gap
			end
		end
		local mainAlign = enumName(get(list, if vertical then "VerticalAlignment" else "HorizontalAlignment", nil))
		local crossAlign = enumName(get(list, if vertical then "HorizontalAlignment" else "VerticalAlignment", nil))
		local span = if vertical then content.h else content.w
		local cursor = if vertical then content.y else content.x
		if mainAlign == "Center" then
			cursor += (span - total) / 2
		elseif mainAlign == "Bottom" or mainAlign == "Right" then
			cursor += span - total
		end
		for _, c in ordered do
			local w, h = sizes[c][1], sizes[c][2]
			local cross
			if vertical then
				cross = content.x
				if crossAlign == "Center" then
					cross += (content.w - w) / 2
				elseif crossAlign == "Right" then
					cross += content.w - w
				end
				positions[c] = { cross, cursor }
				cursor += h + gap
			else
				cross = content.y
				if crossAlign == "Center" then
					cross += (content.h - h) / 2
				elseif crossAlign == "Bottom" then
					cross += content.h - h
				end
				positions[c] = { cursor, cross }
				cursor += w + gap
			end
		end
	end
	for _, c in children do
		local w, h, sk = sizes[c][1], sizes[c][2], sizes[c][3]
		local x, y
		local placed = positions[c]
		if placed then
			x, y = placed[1], placed[2]
		elseif layout and get(c, "Visible", true) == false then
			x, y = content.x, content.y
		else
			local p = get(c, "Position", nil)
			local a = get(c, "AnchorPoint", nil)
			local ax, ay = if a then a.X else 0, if a then a.Y else 0
			x = content.x + (if p then content.w * p.X.Scale + p.X.Offset * k else 0) - ax * w
			y = content.y + (if p then content.h * p.Y.Scale + p.Y.Offset * k else 0) - ay * h
		end
		local vis = visible and get(c, "Visible", true) == true
		out[c] = { x = x, y = y, w = w, h = h, visible = vis, scroll = scroll, k = k * sk }
		local pl, pt, pr, pb = padding(c, w, h, k * sk)
		local inner: Rect = { x = x + pl, y = y + pt, w = max(0, w - pl - pr), h = max(0, h - pt - pb) }
		local childScroll = scroll
		if c:IsA("ScrollingFrame") then
			childScroll = true
			local cs = get(c, "CanvasSize", nil)
			if cs then
				inner.w = max(inner.w, w * cs.X.Scale + cs.X.Offset * k)
				inner.h = max(inner.h, h * cs.Y.Scale + cs.Y.Offset * k)
			end
		end
		layoutInto(ctx, c, inner, vis, k * sk, childScroll, out)
	end
end

-- Absolute rectangles of every GuiObject under a ScreenGui at a viewport size (pixels/points).
function Xray.layout(screenGui: any, vw: number, vh: number, opts: Options?, env: Env?): { [any]: GuiBox }
	local o = opts or Xray.DEFAULTS
	local ctx = { env = env or { mode = "lune" }, opts = o } :: any
	local inset = 0
	local ignoreInset = get(screenGui, "IgnoreGuiInset", false)
	local insets = enumName(get(screenGui, "ScreenInsets", nil))
	if not ignoreInset and (insets == "" or insets == "CoreUISafeInsets") then
		inset = o.topInset or 58
	end
	local out: { [any]: GuiBox } = {}
	layoutInto(ctx, screenGui, { x = 0, y = inset, w = vw, h = vh - inset }, get(screenGui, "Enabled", true) ~= false, 1, false, out)
	return out
end

local function screenGuis(root: any): { any }
	local list = {}
	if root:IsA("ScreenGui") then
		table.insert(list, root)
	end
	for _, d in root:GetDescendants() do
		if d:IsA("ScreenGui") then
			table.insert(list, d)
		end
	end
	return list
end

-- WCAG 2.x relative luminance and contrast ratio
local function channel(c: number): number
	return if c <= 0.04045 then c / 12.92 else ((c + 0.055) / 1.055) ^ 2.4
end
local function luminance(r: number, g: number, b: number): number
	return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
end
function Xray.contrastRatio(r1: number, g1: number, b1: number, r2: number, g2: number, b2: number): number
	local l1, l2 = luminance(r1, g1, b1), luminance(r2, g2, b2)
	if l1 < l2 then
		l1, l2 = l2, l1
	end
	return (l1 + 0.05) / (l2 + 0.05)
end

-- The colour behind a GuiObject, compositing semi-transparent backgrounds; nil when it is the 3D world or an image.
local function backdrop(gui: any): (number?, number?, number?)
	return Xray.backdrop(gui)
end

function Xray.backdrop(gui: any): (number?, number?, number?)
	if not gui or not gui:IsA("GuiObject") then
		return nil, nil, nil
	end
	if (gui:IsA("ImageLabel") or gui:IsA("ImageButton")) and tostring(get(gui, "Image", "")) ~= ""
		and get(gui, "ImageTransparency", 0) < 0.5 then
		return nil, nil, nil
	end
	if gui:FindFirstChildWhichIsA("UIGradient") then
		return nil, nil, nil -- gradient colours: not one backdrop colour
	end
	local t = get(gui, "BackgroundTransparency", 0)
	local c = get(gui, "BackgroundColor3", nil)
	if t >= 0.99 or not c then
		return Xray.backdrop(gui.Parent)
	end
	if t <= 0.01 then
		return c.R, c.G, c.B
	end
	local ur, ug, ub = Xray.backdrop(gui.Parent)
	if ur == nil then
		if t <= 0.5 then
			return c.R, c.G, c.B
		end
		return nil, nil, nil
	end
	return c.R * (1 - t) + (ur :: number) * t, c.G * (1 - t) + (ug :: number) * t, c.B * (1 - t) + (ub :: number) * t
end

local function ui(ctx: Ctx)
	local o, en = ctx.opts, ctx.enabled
	local guis = screenGuis(ctx.info.uiRoot)
	ctx.info.screenGuis = #guis
	local overflow: { [any]: { ratio: number, views: { string }, estimated: boolean } } = {}
	local offscreen: { [any]: { px: number, views: { string }, full: boolean } } = {}
	for _, sg in guis do
		if not ignored(sg, ctx.info.uiRoot) then
			for _, vp in o.viewports :: { Viewport } do
				local boxes = Xray.layout(sg, vp.w, vp.h, o, ctx.env)
				local reported: { [any]: boolean } = {}
				-- parents first, so a child of an off-screen frame is not reported again
				local order = {}
				for gui in boxes do
					table.insert(order, gui)
				end
				local depth: { [any]: number } = {}
				for _, gui in order do
					local d, node = 0, gui
					while node and node ~= sg do
						d += 1
						node = node.Parent
					end
					depth[gui] = d
				end
				table.sort(order, function(a, b)
					if depth[a] ~= depth[b] then
						return depth[a] < depth[b]
					end
					return a.Name < b.Name
				end)
				for _, gui in order do
					local box = boxes[gui]
					if box.visible and box.w > 0 and box.h > 0 and not ignored(gui, sg) then
						if en.ui_off_screen and not box.scroll then
							local parentReported = gui.Parent and reported[gui.Parent]
							local ix = max(0, min(box.x + box.w, vp.w) - max(box.x, 0))
							local iy = max(0, min(box.y + box.h, vp.h) - max(box.y, 0))
							local share = (ix * iy) / (box.w * box.h)
							local over = max(-box.x, -box.y, box.x + box.w - vp.w, box.y + box.h - vp.h)
							if parentReported then
								reported[gui] = true
							elseif over > 2 then
								reported[gui] = true
								local rec = offscreen[gui]
								if not rec then
									rec = { px = 0, views = {}, full = false }
									offscreen[gui] = rec
								end
								rec.px = max(rec.px, over)
								rec.full = rec.full or share <= 0
								table.insert(rec.views, vp.name .. (if share <= 0 then " (fully)" else " (partly)"))
							end
						end
						if en.text_overflow and isText(gui) and not get(gui, "TextScaled", false) then
							local text = plainText(gui)
							if text ~= "" and get(gui, "TextTransparency", 0) < 0.99 then
								local pl, pt, pr, pb = padding(gui, box.w, box.h, box.k)
								local aw, ah = box.w - pl - pr, box.h - pt - pb
								local wrapped = get(gui, "TextWrapped", false)
								local size = get(gui, "TextSize", 14) * box.k
								local lineHeight = get(gui, "LineHeight", 1)
								local tw, th, est = textMeasure(ctx, text, size, get(gui, "FontFace", nil), if wrapped then max(1, aw) else 1e5)
								th *= lineHeight
								local slack = if est then o.textSlack else 1
								local ratio = 0
								if aw > 0 and not wrapped then
									ratio = tw / aw
								end
								if ah > 0 then
									ratio = max(ratio, th / ah)
								end
								if ratio > slack and (tw > aw + 1 or th > ah + 1) then
									local rec = overflow[gui]
									if not rec then
										rec = { ratio = 0, views = {}, estimated = est }
										overflow[gui] = rec
									end
									rec.ratio = max(rec.ratio, ratio)
									table.insert(rec.views, vp.name)
								end
							end
						end
						if en.touch_target and vp.name == "phone" and (gui:IsA("GuiButton") or gui:IsA("TextBox")) then
							local side = min(box.w, box.h)
							if side < o.touchMin then
								add(ctx, {
									detector = "touch_target",
									severity = if side < 30 then "high" else "medium",
									path = pathOf(ctx, gui),
									value = round(side, 1),
									unit = "px",
									viewport = vp.name,
									message = string.format("%s is %s x %s px on a phone (%dx%d); fingers need at least %d px.", gui.Name,
										fmt(round(box.w, 1)), fmt(round(box.h, 1)), vp.w, vp.h, o.touchMin),
									fix = string.format("Make it at least %d x %d px on phones (Scale sizing or a UISizeConstraint MinSize).", o.touchMin, o.touchMin),
								})
							end
						end
					end
				end
				tick(ctx)
			end
			if en.contrast then
				for _, gui in sg:GetDescendants() do
					local styled = gui:FindFirstChildWhichIsA("UIStroke") or gui:FindFirstChildWhichIsA("UIGradient")
					if isText(gui) and plainText(gui) ~= "" and not styled and not ignored(gui, sg) then
						local tt = get(gui, "TextTransparency", 0)
						local stroke = get(gui, "TextStrokeTransparency", 1)
						local br, bg, bb = backdrop(gui)
						if br ~= nil and tt < 0.99 and stroke >= 0.5 then
							local c = get(gui, "TextColor3", nil)
							if c then
								local r, g, b = c.R * (1 - tt) + (br :: number) * tt, c.G * (1 - tt) + (bg :: number) * tt, c.B * (1 - tt) + (bb :: number) * tt
								local ratio = Xray.contrastRatio(r, g, b, br :: number, bg :: number, bb :: number)
								local size = get(gui, "TextSize", 14)
								local weight = enumName(get(get(gui, "FontFace", nil), "Weight", nil))
								local large = size >= 24 or (size >= 19 and (weight == "Bold" or weight == "Heavy" or weight == "ExtraBold"))
								local need = if large then o.contrastLarge else o.contrastNormal
								if ratio < need then
									add(ctx, {
										detector = "contrast",
										severity = if ratio < 3 then "high" else "medium",
										path = pathOf(ctx, gui),
										value = round(ratio, 2),
										unit = ": 1 contrast",
										message = string.format("Text of %s has contrast %s:1 against its background; WCAG needs %s:1 for %s text.",
											gui.Name, fmt(round(ratio, 2)), fmt(need), if large then "large" else "normal"),
										fix = "Darken or lighten the text or the background (or add a TextStroke) until the ratio passes.",
									})
								end
							end
						end
					end
				end
			end
		end
	end
	for gui, rec in overflow do
		add(ctx, {
			detector = "text_overflow",
			severity = if rec.ratio >= 1.5 then "high" else "medium",
			path = pathOf(ctx, gui),
			value = round(rec.ratio, 3),
			unit = "x box",
			viewport = table.concat(rec.views, ","),
			estimated = rec.estimated or nil,
			message = string.format("Text of %s needs %sx its box at %s%s.", gui.Name, fmt(rec.ratio), table.concat(rec.views, ", "),
				if rec.estimated then " (estimated font metrics)" else ""),
			fix = "Shorten the text, enlarge the box, turn on TextWrapped, or use TextScaled with a UITextSizeConstraint.",
		})
	end
	for gui, rec in offscreen do
		local interactive = isText(gui) or gui:IsA("GuiButton")
		add(ctx, {
			detector = "ui_off_screen",
			severity = if rec.full then "high" elseif interactive then "medium" else "low",
			path = pathOf(ctx, gui),
			value = round(rec.px, 1),
			unit = "px outside",
			viewport = table.concat(rec.views, ","),
			message = string.format("%s is off-screen at %s (up to %s px outside).", gui.Name, table.concat(rec.views, ", "),
				fmt(round(rec.px, 1))),
			fix = "Position it with Scale and AnchorPoint instead of fixed Offset pixels, or clamp it with a UISizeConstraint.",
		})
	end
end

-- --------------------------------------------------------------------------- unreachable (Studio only)

local KEY_NAMES = { "^goal", "^exit", "^finish", "^checkpoint", "^chest", "^keypoint" }

local function unreachable(ctx: Ctx, recs: { Rec })
	local pathfind = ctx.env.pathfind
	if not pathfind then
		ctx.skipped.unreachable = "needs PathfindingService (Studio mode only)"
		return
	end
	local spawn = nil
	local keys = {}
	for _, r in recs do
		local inst = r.inst
		if inst:IsA("SpawnLocation") and not spawn then
			spawn = inst
		end
		local isKey = attr(inst, "XrayKeyPoint") == true
		local okTag, tagged = pcall(function()
			return inst:HasTag("XrayKeyPoint")
		end)
		isKey = isKey or (okTag and tagged == true)
		if not isKey then
			local n = string.lower(inst.Name)
			for _, pat in KEY_NAMES do
				if string.match(n, pat) then
					isKey = true
				end
			end
		end
		if isKey and #keys < 50 then
			table.insert(keys, inst)
		end
	end
	if not spawn then
		ctx.skipped.unreachable = "no SpawnLocation to start from"
		return
	end
	ctx.info.keyPoints = #keys
	for _, key in keys do
		local ok, status = pcall(pathfind, spawn, key)
		local result = if ok then tostring(status) else "Error"
		if result ~= "Success" then
			add(ctx, {
				detector = "unreachable",
				severity = "high",
				path = pathOf(ctx, key),
				partner = pathOf(ctx, spawn),
				value = 0,
				unit = "path found",
				message = string.format("No walkable path from %s to %s (PathfindingService: %s).", spawn.Name, key.Name, result),
				fix = "Open a route (gap, wall, missing stairs or a jump higher than JumpHeight 7.2 studs).",
			})
		end
		tick(ctx)
	end
end

-- --------------------------------------------------------------------------- entry point

local function merged(opts: Options?): Options
	local o: Options = {}
	for k, v in Xray.DEFAULTS do
		o[k] = v
	end
	if opts then
		for k, v in opts do
			o[k] = v
		end
	end
	return o
end

--[[ Scan a place (DataModel), a model or folder. Returns the report (plain data, JSON-ready) and the
instances of the change list (targets[k] belongs to report.changes[k]). ]]
function Xray.scan(root: any, opts: Options?, env: Env?): ({ [string]: any }, { any })
	local started = os.clock()
	local o = merged(opts)
	local e: Env = env or { mode = "lune" }
	local enabled: { [string]: boolean } = {}
	for _, name in (o.detectors or ALL_DETECTORS) :: { string } do
		enabled[name] = true
	end
	local ctx: Ctx = {
		opts = o,
		env = e,
		findings = {},
		changes = {},
		targets = {},
		changed = {},
		skipped = {},
		enabled = enabled,
		paths = {},
		lastYield = os.clock(),
		timings = {},
		info = {},
	}
	local partsRoot, uiRoot = root, root
	if root:IsA("DataModel") then
		partsRoot = root:GetService("Workspace")
		uiRoot = root:GetService("StarterGui")
	end
	ctx.info.partsRoot, ctx.info.uiRoot = partsRoot, uiRoot
	local terrain = partsRoot:FindFirstChildOfClass("Terrain")
	if terrain then
		local grid = get(terrain, "SmoothGrid", nil)
		ctx.info.terrain = e.onTerrain ~= nil or (type(grid) == "string" and #grid > 64)
	end

	local t = os.clock()
	local recs = collectParts(ctx, partsRoot)
	ctx.timings.collect = os.clock() - t
	t = os.clock()
	local hash = buildHash(ctx, recs, o.cell)
	ctx.timings.hash = os.clock() - t
	ctx.info.cell = hash.cell
	if enabled.floating or enabled.near_miss_gap or enabled.z_fighting or enabled.interpenetration then
		geometry(ctx, recs, hash)
	end
	if enabled.off_grid then
		t = os.clock()
		offGrid(ctx, recs)
		ctx.timings.off_grid = os.clock() - t
	end
	if enabled.scale then
		t = os.clock()
		scale(ctx, recs, hash)
		ctx.timings.scale = os.clock() - t
	end
	if enabled.stretched_texture then
		textures(ctx)
	end
	if enabled.text_overflow or enabled.ui_off_screen or enabled.contrast or enabled.touch_target then
		t = os.clock()
		ui(ctx)
		ctx.timings.ui = os.clock() - t
	end
	if enabled.unreachable then
		unreachable(ctx, recs)
	end

	-- most severe first; cap the list but keep the true counts
	local counts: { [string]: number } = {}
	for _, f in ctx.findings do
		counts[f.detector] = (counts[f.detector] or 0) + 1
	end
	table.sort(ctx.findings, function(a, b)
		local ra, rb = SEVERITY_RANK[a.severity] or 0, SEVERITY_RANK[b.severity] or 0
		if ra ~= rb then
			return ra > rb
		end
		if a.detector ~= b.detector then
			return a.detector < b.detector
		end
		return a.path < b.path
	end)
	local shown = ctx.findings
	if #shown > o.maxFindings then
		shown = table.move(ctx.findings, 1, o.maxFindings, 1, {})
	end
	local timings = {}
	for k, v in ctx.timings do
		timings[k] = round(v * 1000, 1)
	end
	local grid = ctx.info.grid
	local avatar = ctx.info.avatar
	local report = {
		tool = "star-xray",
		version = Xray.version,
		mode = e.mode,
		parts = #recs,
		pairs = ctx.info.pairs or 0,
		screenGuis = ctx.info.screenGuis or 0,
		grid = grid,
		cell = hash.cell,
		avatar = avatar,
		counts = counts,
		total = #ctx.findings,
		truncated = #ctx.findings > #shown,
		findings = shown,
		changes = ctx.changes,
		skipped = ctx.skipped,
		ms = timings,
		totalMs = round((os.clock() - started) * 1000, 1),
		textMetrics = if e.textSize then "exact" else "estimated",
		spatial = if e.partsInBox then "engine" else "hash",
	}
	return report, ctx.targets
end

return Xray
