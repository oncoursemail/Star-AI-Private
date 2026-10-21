--!strict
--[[
The planted-defect exam. Each trial builds the clean sample place, plants one defect of every examinable
type at a random (seeded) target with random size, scans, and scores:

  detected   a finding of the right detector names the planted target (path, partner or members)
  collateral a finding of another detector that names a planted target (a real side effect, e.g. a plate
             embedded flush in a wall is also inside the wall)
  false alarm a finding that names no planted target

The clean place is scanned too: every finding there is a false alarm.
`unreachable` needs PathfindingService and is only examined in Studio.
]]

local Exam = {}

type Plant = { kind: string, detector: string, targets: { string }, note: string }

local function lcg(seed: number)
	local s = seed % 2147483647
	if s <= 0 then
		s += 2147483646
	end
	local r = {}
	function r.next(): number
		s = (s * 48271) % 2147483647
		return s / 2147483647
	end
	function r.uniform(a: number, b: number): number
		return a + (b - a) * r.next()
	end
	function r.int(a: number, b: number): number
		return math.min(b, a + math.floor((b - a + 1) * r.next()))
	end
	function r.pick<T>(list: { T }): T
		return list[r.int(1, #list)]
	end
	return r
end
Exam.lcg = lcg

local function aabb(p: any): (number, number, number, number, number, number)
	local c, s = p.CFrame.Position, p.Size
	return c.X - s.X / 2, c.Y - s.Y / 2, c.Z - s.Z / 2, c.X + s.X / 2, c.Y + s.Y / 2, c.Z + s.Z / 2
end

local function setBox(R: any, p: any, x0: number, y0: number, z0: number, x1: number, y1: number, z1: number)
	p.Size = R.Vector3.new(x1 - x0, y1 - y0, z1 - z0)
	p.CFrame = R.CFrame.new((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
end

local function move(R: any, p: any, dx: number, dy: number, dz: number)
	p.CFrame = p.CFrame + R.Vector3.new(dx, dy, dz)
end

local function newPart(R: any, parent: any, name: string, x0: number, y0: number, z0: number, x1: number, y1: number, z1: number, color: any): any
	local p = R.Instance.new("Part")
	p.Name = name
	p.Anchored = true
	p.Color = color
	p.Material = R.Enum.Material.SmoothPlastic
	setBox(R, p, x0, y0, z0, x1, y1, z1)
	p.Parent = parent
	return p
end

local function fullName(inst: any): string
	return inst:GetFullName()
end

-- Plant one defect of every type. `used` keeps targets distinct so plants do not cancel each other.
function Exam.plant(R: any, Xray: any, meta: any, rng: any): { Plant }
	local P, U = meta.parts, meta.ui
	local house = meta.house
	local plants: { Plant } = {}
	local used: { [string]: boolean } = {}
	local function choose(list: { any }, key: (any) -> string): any
		local free = {}
		for _, item in list do
			if not used[key(item)] then
				table.insert(free, item)
			end
		end
		local item = rng.pick(free)
		used[key(item)] = true
		return item
	end
	local function name(x: any): string
		return if type(x) == "table" then x[1] else x
	end
	local function plant(kind: string, detector: string, targets: { any }, note: string)
		local paths = {}
		for _, t in targets do
			table.insert(paths, fullName(t))
		end
		table.insert(plants, { kind = kind, detector = detector, targets = paths, note = note })
	end

	-- floating: lift a free-standing prop 0.3-6 studs (staying under the upper floor)
	do
		local c = choose({ { "Book", 10.5 }, { "Mug", 10.5 }, { "Lamp", 10.5 }, { "Crate2", 10.5 }, { "Crate3", 10.5 },
			{ "Rug", 10.5 }, { "PlantPot", 99 }, { "Bench", 99 }, { "Chimney", 99 } }, name)
		local p = P[c[1]]
		local _, _, _, _, y1 = aabb(p)
		local lift = rng.uniform(0.3, math.min(6, c[2] - y1))
		move(R, p, 0, lift, 0)
		plant("floating", "floating", { p }, string.format("%s lifted %.2f studs", c[1], lift))
	end
	-- near-miss gap: pull a resting prop 0.005-0.19 studs off its support
	do
		local c = choose({ { "Book", 0, 1, 0 }, { "Mug", 0, 1, 0 }, { "Lamp", 0, 1, 0 }, { "Crate2", 0, 1, 0 }, { "Crate3", 0, 1, 0 },
			{ "Bench", 0, 1, 0 }, { "PlantPot", 0, 1, 0 }, { "Rug", 0, 1, 0 }, { "Chimney", 0, 1, 0 }, { "Vase", 0, 1, 0 },
			{ "TableTop", 0, 1, 0 }, { "Poster", -1, 0, 0 }, { "Shelf", 1, 0, 0 } }, name)
		local d = rng.uniform(0.005, 0.19)
		move(R, P[c[1]], c[2] * d, c[3] * d, c[4] * d)
		plant("gap", "near_miss_gap", { P[c[1]] }, string.format("%s moved %.3f studs off its support", c[1], d))
	end
	-- z-fighting: a plate embedded in a wall or floor with its face flush with the host's face
	do
		local hosts = {
			{ "WallW", "x", 1, 1, { 2, 9 }, { 2, 17 } },
			{ "WallE", "x", 23, -1, { 2, 9 }, { 2, 17 } },
			{ "Floor", "y", 1, 1, { 2, 21 }, { 2, 17 } },
			{ "Floor2", "y", 12, 1, { 2, 21 }, { 2, 17 } },
			{ "WallS_L", "z", 1, 1, { 1, 9 }, { 2, 9 } },
			{ "WallN_L", "z", 19, -1, { 1, 8 }, { 2, 9 } },
		}
		local h = choose(hosts, name)
		local w, l = rng.int(1, 3), rng.int(1, 3)
		local a = rng.int(h[5][1], h[5][2] - w)
		local b = rng.int(h[6][1], h[6][2] - l)
		local face, dir = h[3], h[4]
		local inner = face - dir * 0.5
		local f0, f1 = math.min(face, inner), math.max(face, inner)
		local color = R.Color3.fromRGB(rng.int(0, 255), rng.int(0, 255), rng.int(0, 255))
		local bx, bz = meta.originX, meta.originZ
		local p
		if h[2] == "x" then
			p = newPart(R, house, "Plate", bx + f0, a, bz + b, bx + f1, a + w, bz + b + l, color)
		elseif h[2] == "y" then
			p = newPart(R, house, "Plate", bx + a, f0, bz + b, bx + a + w, f1, bz + b + l, color)
		else
			p = newPart(R, house, "Plate", bx + a, b, bz + f0, bx + a + w, b + l, bz + f1, color)
		end
		plant("zfight", "z_fighting", { p }, string.format("%dx%d plate flush with %s", w, l, h[1]))
	end
	-- heavy interpenetration: a 2-stud crate pushed halfway into a wall
	do
		local walls = { { "WallW", "x", 0.5, { 3, 15 } }, { "WallE", "x", 23.5, { 3, 15 } }, { "WallS_L", "z", 0.5, { 2, 7 } },
			{ "WallN_L", "z", 19.5, { 2, 6 } } }
		local h = choose(walls, function(x)
			return "intr:" .. x[1]
		end)
		local c = h[3] + rng.uniform(-0.4, 0.4)
		local along = rng.int(h[4][1], h[4][2])
		local bx, bz = meta.originX, meta.originZ
		local p
		if h[2] == "x" then
			p = newPart(R, house, "Intruder", bx + c - 1, 1, bz + along, bx + c + 1, 3, bz + along + 2, R.Color3.fromRGB(90, 60, 30))
		else
			p = newPart(R, house, "Intruder", bx + along, 1, bz + c - 1, bx + along + 2, 3, bz + c + 1, R.Color3.fromRGB(90, 60, 30))
		end
		plant("interpenetration", "interpenetration", { p }, string.format("2-stud crate across %s", h[1]))
	end
	-- off-grid: shift a prop 0.02-0.48 studs (never a half-stud multiple) or turn it 0.1-3 degrees
	do
		local c = choose({ { "Crate1", "xz" }, { "Crate2", "xz" }, { "TableTop", "xz" }, { "Bench", "xz" }, { "Shelf", "z" },
			{ "Chimney", "xz" }, { "Rug", "xz" }, { "Poster", "z" }, { "PlantPot", "xz" }, { "WallS_Header", "x" } }, name)
		local p = P[c[1]]
		if rng.next() < 0.7 then
			local s = if rng.next() < 0.5 then rng.uniform(0.02, 0.23) else rng.uniform(0.27, 0.48)
			if rng.next() < 0.5 then
				s = -s
			end
			local axis = if c[2] == "xz" then (if rng.next() < 0.5 then "x" else "z") else c[2]
			move(R, p, if axis == "x" then s else 0, 0, if axis == "z" then s else 0)
			plant("offgrid", "off_grid", { p }, string.format("%s shifted %.3f studs along %s", c[1], s, axis))
		else
			local deg = rng.uniform(0.1, 3) * (if rng.next() < 0.5 then 1 else -1)
			p.CFrame = p.CFrame * R.CFrame.Angles(0, math.rad(deg), 0)
			plant("offgrid", "off_grid", { p }, string.format("%s turned %.2f degrees", c[1], deg))
		end
	end
	-- scale vs avatar: a small door, a low ceiling, an uneven step or a low railing
	do
		local kind = rng.pick({ "door", "ceiling", "stairs", "railing" })
		if kind == "door" then
			local door = P.Door
			local x0, y0, z0, x1, y1, z1 = aabb(door)
			if rng.next() < 0.5 then
				local hgt = rng.uniform(4.5, 6.95)
				setBox(R, door, x0, y0, z0, x1, y0 + hgt, z1)
				plant("scale", "scale", { P.DoorModel, door }, string.format("door %.2f studs tall", hgt))
			else
				local wid = rng.uniform(2.5, 3.95)
				local cx = (x0 + x1) / 2
				setBox(R, door, cx - wid / 2, y0, z0, cx + wid / 2, y1, z1)
				plant("scale", "scale", { P.DoorModel, door }, string.format("door %.2f studs wide", wid))
			end
		elseif kind == "ceiling" then
			local roof = meta.annex:FindFirstChild("Roof")
			local floorTop = 1
			local clear = rng.uniform(3.5, 7.4)
			local x0, y0, z0, x1, y1, z1 = aabb(roof)
			setBox(R, roof, x0, floorTop + clear, z0, x1, floorTop + clear + (y1 - y0), z1)
			plant("scale", "scale", { roof }, string.format("annex ceiling %.2f studs above the floor", clear))
		elseif kind == "stairs" then
			local k = rng.int(2, 11)
			local step = P.Stairs:FindFirstChild("Step" .. k)
			local delta = rng.uniform(0.3, 0.9)
			local x0, y0, z0, x1, y1, z1 = aabb(step)
			setBox(R, step, x0, y0, z0, x1, y1 + delta, z1)
			plant("scale", "scale", { P.Stairs, step }, string.format("Step%d raised %.2f studs", k, delta))
		else
			local rail = P[rng.pick({ "RailingN", "RailingS", "RailingW", "RailingE2" })]
			local hgt = rng.uniform(0.8, 2.45)
			local x0, y0, z0, x1, _, z1 = aabb(rail)
			setBox(R, rail, x0, y0, z0, x1, y0 + hgt, z1)
			plant("scale", "scale", { rail }, string.format("%s %.2f studs tall", rail.Name, hgt))
		end
	end
	-- stretched texture: unequal StudsPerTile, or a decal on a long thin face
	do
		if rng.next() < 0.5 then
			local t = P[rng.pick({ "FloorTex", "Floor2Tex", "WallWTex" })]
			local r = rng.uniform(1.55, 4)
			if rng.next() < 0.5 then
				t.StudsPerTileU = t.StudsPerTileV * r
			else
				t.StudsPerTileV = t.StudsPerTileU * r
			end
			plant("texture", "stretched_texture", { t }, string.format("%s tiles stretched %.2fx", t.Name, r))
		else
			local spot = rng.pick({ { "WallS_Header", "Front" }, { "TableTop", "Front" }, { "Bench", "Front" }, { "RailingN", "Back" },
				{ "Shelf", "Right" } })
			local d = R.Instance.new("Decal")
			d.Name = "Sticker"
			d.Face = R.Enum.NormalId[spot[2]]
			d.Texture = "rbxassetid://6372755229"
			d.Parent = P[spot[1]]
			plant("texture", "stretched_texture", { d }, string.format("decal on %s %s face", spot[1], spot[2]))
		end
	end
	-- UI: text overflow
	do
		local n = choose({ "Title", "Coins", "ShopTitle", "BuySword", "BuyShield", "BuyPotion", "ActionButton", "Toast" }, name)
		local gui = U[n]
		local words = { "Legendary", "rewards", "await", "brave", "explorers", "who", "complete", "every", "quest", "today" }
		local text = {}
		local target = if n == "Toast" then rng.int(260, 400) else rng.int(60, 100)
		local len = 0
		while len < target do
			local w = rng.pick(words)
			table.insert(text, w)
			len += #w + 1
		end
		gui.Text = table.concat(text, " ")
		plant("overflow", "text_overflow", { gui }, string.format("%s text set to %d characters", n, len))
	end
	-- UI: off-screen on phones
	do
		local n = choose({ "TopBar", "ShopPanel", "ActionButton", "Toast", "SettingsButton" }, name)
		local gui = U[n]
		local boxes = Xray.layout(meta.gui, 844, 390)
		local w, h = boxes[gui].w, boxes[gui].h
		local variant = rng.int(1, 4)
		gui.AnchorPoint = R.Vector2.new(0, 0)
		if variant == 4 then
			-- just past the right edge of a phone: 4-30 px
			gui.Position = R.UDim2.new(0, math.floor(844 - w + rng.uniform(4, 30)), 0, 100)
		elseif variant == 1 then
			gui.Position = R.UDim2.new(0, math.floor(rng.uniform(860, 1500)), 0, 100)
		elseif variant == 2 then
			gui.Position = R.UDim2.new(0, -math.floor(rng.uniform(0.4, 0.9) * w), 0, 100)
		else
			gui.Position = R.UDim2.new(0, 100, 0, math.floor(rng.uniform(400, 900)))
		end
		local _ = h
		plant("offscreen", "ui_off_screen", { gui }, string.format("%s moved to %s", n, tostring(gui.Position)))
	end
	-- UI: low contrast text
	do
		local n = choose({ "Title", "Coins", "ShopTitle", "BuySword", "BuyShield", "BuyPotion", "ActionButton", "Toast", "SettingsButton" }, name)
		local gui = U[n]
		local br, bg, bb = Xray.backdrop(gui)
		local need = if gui.TextSize >= 24 then 3 else 4.5
		local goal = rng.uniform(1.05, need - 0.05)
		local dark = (br + bg + bb) / 3 < 0.5
		local function shifted(f: number): (number, number, number)
			local function one(c: number): number
				return if dark then c + (1 - c) * f else c * (1 - f)
			end
			return one(br), one(bg), one(bb)
		end
		local lo, hi = 0, 1
		for _ = 1, 40 do
			local mid = (lo + hi) / 2
			local r1, g1, b1 = shifted(mid)
			if Xray.contrastRatio(r1, g1, b1, br, bg, bb) < goal then
				lo = mid
			else
				hi = mid
			end
		end
		local r, g, b = shifted(lo)
		gui.TextColor3 = R.Color3.new(r, g, b)
		plant("contrast", "contrast", { gui }, string.format("%s text contrast %.2f:1", n, Xray.contrastRatio(r, g, b, br, bg, bb)))
	end
	-- UI: tiny touch target
	do
		local n = choose({ "BuySword", "BuyShield", "BuyPotion", "ActionButton", "SettingsButton" }, name)
		local gui = U[n]
		local side = rng.int(18, 43)
		if n == "ActionButton" then
			gui.Size = R.UDim2.new(0, 180, 0, side)
		elseif n == "SettingsButton" then
			gui.Size = R.UDim2.new(0, side, 0, side)
		else
			gui.Size = R.UDim2.new(1, 0, 0, side)
		end
		plant("touch", "touch_target", { gui }, string.format("%s %d px on phones", n, side))
	end
	return plants
end

local function refs(f: any): { string }
	local list = { f.path }
	if f.partner then
		table.insert(list, f.partner)
	end
	if f.members then
		for _, m in f.members do
			table.insert(list, m)
		end
	end
	return list
end

-- Score one scan against its plants. Returns per-detector tallies and the unmatched findings.
function Exam.score(report: any, plants: { Plant })
	local detected: { [number]: boolean } = {}
	local falseAlarms, collateral = {}, 0
	for _, f in report.findings do
		local matchedAny = false
		for idx, p in plants do
			local hit = false
			for _, r in refs(f) do
				for _, t in p.targets do
					if r == t then
						hit = true
					end
				end
			end
			if hit then
				matchedAny = true
				if f.detector == p.detector then
					detected[idx] = true
				end
			end
		end
		if not matchedAny then
			table.insert(falseAlarms, f)
		else
			local own = false
			for idx, p in plants do
				if detected[idx] and p.detector == f.detector then
					own = true
				end
			end
			if not own then
				collateral += 1
			end
		end
	end
	return detected, falseAlarms, collateral
end

local EXAMINED = { "floating", "near_miss_gap", "z_fighting", "interpenetration", "off_grid", "scale", "stretched_texture",
	"text_overflow", "ui_off_screen", "contrast", "touch_target" }

-- One trial, for debugging a miss: the plants and the full report.
function Exam.trial(R: any, Xray: any, Sample: any, newGame: () -> any, seed: number, t: number, env: any?): { [string]: any }
	local game = newGame()
	local meta = Sample.build(game, R, 1)
	local origin = meta.parts.Floor.CFrame.Position
	meta.originX, meta.originZ = origin.X - 12, origin.Z - 10
	local plants = Exam.plant(R, Xray, meta, lcg(seed * 1000003 + t))
	local report = Xray.scan(game, { maxFindings = 100000 }, env)
	return { plants = plants, report = report }
end

function Exam.run(R: any, Xray: any, Sample: any, newGame: () -> any, trials: number, seed: number, env: any?): { [string]: any }
	local started = os.clock()
	local per: { [string]: { planted: number, detected: number, falseAlarms: number } } = {}
	for _, d in EXAMINED do
		per[d] = { planted = 0, detected = 0, falseAlarms = 0 }
	end
	-- clean place: everything reported is a false alarm
	local cleanGame = newGame()
	Sample.build(cleanGame, R, 1)
	local cleanReport = Xray.scan(cleanGame, nil, env)
	local misses, alarms = {}, {}
	local collateralTotal, scanMs = 0, 0
	for t = 1, trials do
		local rng = lcg(seed * 1000003 + t)
		local game = newGame()
		local meta = Sample.build(game, R, 1)
		local origin = meta.parts.Floor.CFrame.Position
		meta.originX, meta.originZ = origin.X - 12, origin.Z - 10
		local plants = Exam.plant(R, Xray, meta, rng)
		local report = Xray.scan(game, nil, env)
		scanMs += report.totalMs
		local detected, falseAlarms, collateral = Exam.score(report, plants)
		collateralTotal += collateral
		for idx, p in plants do
			local tally = per[p.detector]
			tally.planted += 1
			if detected[idx] then
				tally.detected += 1
			elseif #misses < 40 then
				table.insert(misses, { trial = t, detector = p.detector, note = p.note, targets = p.targets })
			end
		end
		for _, f in falseAlarms do
			local tally = per[f.detector]
			if tally then
				tally.falseAlarms += 1
			end
			if #alarms < 40 then
				table.insert(alarms, { trial = t, detector = f.detector, path = f.path, message = f.message })
			end
		end
	end
	local detectors = {}
	local plantedAll, detectedAll, alarmsAll = 0, 0, 0
	for _, d in EXAMINED do
		local tally = per[d]
		plantedAll += tally.planted
		detectedAll += tally.detected
		alarmsAll += tally.falseAlarms
		table.insert(detectors, {
			detector = d,
			planted = tally.planted,
			detected = tally.detected,
			recall = if tally.planted > 0 then math.floor(tally.detected / tally.planted * 10000 + 0.5) / 10000 else 0,
			falseAlarms = tally.falseAlarms,
			cleanFalseAlarms = cleanReport.counts[d] or 0,
		})
	end
	return {
		trials = trials,
		seed = seed,
		detectors = detectors,
		planted = plantedAll,
		detected = detectedAll,
		recall = if plantedAll > 0 then math.floor(detectedAll / plantedAll * 10000 + 0.5) / 10000 else 0,
		falseAlarms = alarmsAll,
		collateral = collateralTotal,
		clean = { total = cleanReport.total, counts = cleanReport.counts, findings = cleanReport.findings, parts = cleanReport.parts },
		misses = misses,
		alarms = alarms,
		notExamined = { unreachable = "needs PathfindingService: Studio only" },
		scanMsAvg = math.floor(scanMs / math.max(1, trials) * 10 + 0.5) / 10,
		totalMs = math.floor((os.clock() - started) * 1000 + 0.5),
	}
end

return Exam
