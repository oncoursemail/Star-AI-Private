--!nocheck
-- STAR sandbox: a small fake Roblox that runs Litha's Luau answers with no engine, no network and no files.
-- The harness (harness.py) prepends `local MEMBERS = {...}` (API member names per class), appends the answer's
-- blocks as strings plus a scenario, and reads one JSON line from stdout. Virtual time: task.wait never sleeps.
-- Mock limits raise errors that start with "[mock]"; those never count as findings.

local REPORT = { errors = {}, warns = {}, events = {}, probes = {}, unmodelled = {} }
local NOW = 0
local SEQ = 0
local QUEUE = {}
local CTX = setmetatable({}, { __mode = "k" })     -- thread -> "server" | "client"
local BLOCK_OF = setmetatable({}, { __mode = "k" }) -- thread -> block index that started it
local PHASE = "load"
local FRAGMENT = {}                                 -- block index -> unknown global names read
local DS_FAIL = false                               -- inject DataStore GetAsync failures

local function note_unmodelled(what)
	REPORT.unmodelled[what] = (REPORT.unmodelled[what] or 0) + 1
end

local function event(kind, data)
	data = data or {}
	data.kind, data.t, data.phase = kind, math.floor(NOW * 100 + 0.5) / 100, PHASE
	table.insert(REPORT.events, data)
end

local function current_ctx()
	return CTX[coroutine.running()] or "server"
end

local function report_error(co, err)
	local msg = tostring(err)
	local tb = debug.traceback(co, msg)
	table.insert(REPORT.errors, { msg = msg, tb = tb, phase = PHASE, t = NOW, block = BLOCK_OF[co], ctx = CTX[co] })
end

local function resume(co, ...)
	local ok, err = coroutine.resume(co, ...)
	if not ok then report_error(co, err) end
end

local function schedule(co, t, ...)
	SEQ += 1
	table.insert(QUEUE, { t = t, seq = SEQ, co = co, args = table.pack(...) })
end

local function spawn_fn(fn, ctx, block, ...)
	local co = type(fn) == "thread" and fn or coroutine.create(fn)
	CTX[co] = CTX[co] or ctx or current_ctx()
	BLOCK_OF[co] = BLOCK_OF[co] or block or BLOCK_OF[coroutine.running()]
	resume(co, ...)
	return co
end

local function run_until(t_end)
	-- resume every thread due before t_end in time order; time jumps (no sleeping)
	local guard = 0
	while true do
		local best, bi = nil, nil
		for i, it in ipairs(QUEUE) do
			if it.t <= t_end and (best == nil or it.t < best.t or (it.t == best.t and it.seq < best.seq)) then
				best, bi = it, i
			end
		end
		if not best then break end
		table.remove(QUEUE, bi)
		if best.t > NOW then NOW = best.t end
		if coroutine.status(best.co) == "suspended" then
			resume(best.co, table.unpack(best.args, 1, best.args.n))
		end
		guard += 1
		if guard > 200000 then error("[mock] scheduler guard") end
	end
	if t_end > NOW then NOW = t_end end
end

-- ---- task library ---------------------------------------------------------------------------------------------------
local task = {}
function task.wait(t)
	t = tonumber(t) or 0
	if t < 1 / 60 then t = 1 / 60 end
	local co = coroutine.running()
	local start = NOW
	schedule(co, NOW + t)
	coroutine.yield()
	return NOW - start, NOW
end
function task.spawn(f, ...)
	return spawn_fn(f, nil, nil, ...)
end
function task.defer(f, ...)
	local co = type(f) == "thread" and f or coroutine.create(f)
	CTX[co] = CTX[co] or current_ctx()
	BLOCK_OF[co] = BLOCK_OF[co] or BLOCK_OF[coroutine.running()]
	schedule(co, NOW, ...)
	return co
end
function task.delay(t, f, ...)
	local co = type(f) == "thread" and f or coroutine.create(f)
	CTX[co] = CTX[co] or current_ctx()
	BLOCK_OF[co] = BLOCK_OF[co] or BLOCK_OF[coroutine.running()]
	schedule(co, NOW + (tonumber(t) or 0), ...)
	return co
end
function task.cancel(co)
	for i = #QUEUE, 1, -1 do
		if QUEUE[i].co == co then table.remove(QUEUE, i) end
	end
end
function task.synchronize() end
function task.desynchronize() end

-- ---- permissive stub for things the mock does not model --------------------------------------------------------------
local Stub
local StubMT = {}
StubMT.__index = function(_, k) return Stub end
StubMT.__newindex = function() end
StubMT.__call = function() return Stub end
StubMT.__tostring = function() return "stub" end
StubMT.__len = function() return 0 end
StubMT.__iter = function() return next, {} end
for _, m in ipairs({ "__add", "__sub", "__mul", "__div", "__mod", "__pow", "__unm", "__idiv" }) do
	StubMT[m] = function() return Stub end
end
StubMT.__concat = function(a, b) return tostring(a) .. tostring(b) end
StubMT.__lt = function() return false end
StubMT.__le = function() return false end
Stub = setmetatable({}, StubMT)

-- ---- datatypes --------------------------------------------------------------------------------------------------------
local TYPES = setmetatable({}, { __mode = "k" })  -- value -> typeof name

local Vector3 = {}
local V3MT = {}
local function v3(x, y, z)
	local v = setmetatable({ X = x or 0, Y = y or 0, Z = z or 0 }, V3MT)
	TYPES[v] = "Vector3"
	return v
end
V3MT.__index = function(v, k)
	if k == "Magnitude" or k == "magnitude" then return math.sqrt(v.X * v.X + v.Y * v.Y + v.Z * v.Z) end
	if k == "Unit" or k == "unit" then
		local m = math.sqrt(v.X * v.X + v.Y * v.Y + v.Z * v.Z)
		if m == 0 then return v3(0, 0, 0) end
		return v3(v.X / m, v.Y / m, v.Z / m)
	end
	if k == "x" then return v.X elseif k == "y" then return v.Y elseif k == "z" then return v.Z end
	if k == "Dot" then return function(a, b) return a.X * b.X + a.Y * b.Y + a.Z * b.Z end end
	if k == "Cross" then return function(a, b) return v3(a.Y * b.Z - a.Z * b.Y, a.Z * b.X - a.X * b.Z, a.X * b.Y - a.Y * b.X) end end
	if k == "Lerp" then return function(a, b, t) return v3(a.X + (b.X - a.X) * t, a.Y + (b.Y - a.Y) * t, a.Z + (b.Z - a.Z) * t) end end
	if k == "Abs" then return function(a) return v3(math.abs(a.X), math.abs(a.Y), math.abs(a.Z)) end end
	if k == "Floor" then return function(a) return v3(math.floor(a.X), math.floor(a.Y), math.floor(a.Z)) end end
	if k == "Min" then return function(a, b) return v3(math.min(a.X, b.X), math.min(a.Y, b.Y), math.min(a.Z, b.Z)) end end
	if k == "Max" then return function(a, b) return v3(math.max(a.X, b.X), math.max(a.Y, b.Y), math.max(a.Z, b.Z)) end end
	if k == "FuzzyEq" then return function(a, b, e) e = e or 1e-5; return (a - b).Magnitude <= e end end
	error(tostring(k) .. " is not a valid member of Vector3", 2)
end
local function vnum(a)
	if type(a) == "number" then return v3(a, a, a) end
	return a
end
V3MT.__add = function(a, b) return v3(a.X + b.X, a.Y + b.Y, a.Z + b.Z) end
V3MT.__sub = function(a, b) return v3(a.X - b.X, a.Y - b.Y, a.Z - b.Z) end
V3MT.__mul = function(a, b) a, b = vnum(a), vnum(b); return v3(a.X * b.X, a.Y * b.Y, a.Z * b.Z) end
V3MT.__div = function(a, b) a, b = vnum(a), vnum(b); return v3(a.X / b.X, a.Y / b.Y, a.Z / b.Z) end
V3MT.__unm = function(a) return v3(-a.X, -a.Y, -a.Z) end
V3MT.__eq = function(a, b) return a.X == b.X and a.Y == b.Y and a.Z == b.Z end
V3MT.__tostring = function(a) return a.X .. ", " .. a.Y .. ", " .. a.Z end
Vector3.new = function(x, y, z) return v3(tonumber(x) or 0, tonumber(y) or 0, tonumber(z) or 0) end
Vector3.zero, Vector3.one = v3(0, 0, 0), v3(1, 1, 1)
Vector3.xAxis, Vector3.yAxis, Vector3.zAxis = v3(1, 0, 0), v3(0, 1, 0), v3(0, 0, 1)
Vector3.FromNormalId = function() return v3(0, 1, 0) end
Vector3.FromAxis = function() return v3(0, 1, 0) end

local Vector2 = {}
local V2MT = {}
local function v2(x, y)
	local v = setmetatable({ X = x or 0, Y = y or 0 }, V2MT)
	TYPES[v] = "Vector2"
	return v
end
V2MT.__index = function(v, k)
	if k == "Magnitude" then return math.sqrt(v.X * v.X + v.Y * v.Y) end
	if k == "Unit" then local m = math.sqrt(v.X * v.X + v.Y * v.Y); return m == 0 and v2(0, 0) or v2(v.X / m, v.Y / m) end
	if k == "x" then return v.X elseif k == "y" then return v.Y end
	if k == "Dot" then return function(a, b) return a.X * b.X + a.Y * b.Y end end
	if k == "Lerp" then return function(a, b, t) return v2(a.X + (b.X - a.X) * t, a.Y + (b.Y - a.Y) * t) end end
	error(tostring(k) .. " is not a valid member of Vector2", 2)
end
V2MT.__add = function(a, b) return v2(a.X + b.X, a.Y + b.Y) end
V2MT.__sub = function(a, b) return v2(a.X - b.X, a.Y - b.Y) end
V2MT.__mul = function(a, b)
	if type(a) == "number" then return v2(a * b.X, a * b.Y) end
	if type(b) == "number" then return v2(a.X * b, a.Y * b) end
	return v2(a.X * b.X, a.Y * b.Y)
end
V2MT.__div = function(a, b) if type(b) == "number" then return v2(a.X / b, a.Y / b) end return v2(a.X / b.X, a.Y / b.Y) end
V2MT.__eq = function(a, b) return a.X == b.X and a.Y == b.Y end
Vector2.new = function(x, y) return v2(tonumber(x) or 0, tonumber(y) or 0) end
Vector2.zero, Vector2.one = v2(0, 0), v2(1, 1)

-- CFrame: position + 3x3 rotation (rows)
local CFrame = {}
local CFMT = {}
local function cf(px, py, pz, r)
	r = r or { 1, 0, 0, 0, 1, 0, 0, 0, 1 }
	local c = setmetatable({ _p = v3(px, py, pz), _r = r }, CFMT)
	TYPES[c] = "CFrame"
	return c
end
local function rmul(a, b)
	local r = {}
	for i = 0, 2 do
		for j = 0, 2 do
			r[i * 3 + j + 1] = a[i * 3 + 1] * b[j + 1] + a[i * 3 + 2] * b[3 + j + 1] + a[i * 3 + 3] * b[6 + j + 1]
		end
	end
	return r
end
local function rvec(r, v)
	return v3(r[1] * v.X + r[2] * v.Y + r[3] * v.Z, r[4] * v.X + r[5] * v.Y + r[6] * v.Z, r[7] * v.X + r[8] * v.Y + r[9] * v.Z)
end
local function rtrans(r) return { r[1], r[4], r[7], r[2], r[5], r[8], r[3], r[6], r[9] } end
local function angles(rx, ry, rz)
	local cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
	local X = { 1, 0, 0, 0, cx, -sx, 0, sx, cx }
	local Y = { cy, 0, sy, 0, 1, 0, -sy, 0, cy }
	local Z = { cz, -sz, 0, sz, cz, 0, 0, 0, 1 }
	return rmul(rmul(X, Y), Z)
end
local function lookat(pos, target)
	local f = (target - pos).Unit
	if f.Magnitude == 0 then return cf(pos.X, pos.Y, pos.Z) end
	local up = v3(0, 1, 0)
	local rt = f:Cross(up)
	if rt.Magnitude < 1e-6 then rt = v3(1, 0, 0) end
	rt = rt.Unit
	local u = rt:Cross(f)
	return cf(pos.X, pos.Y, pos.Z, { rt.X, u.X, -f.X, rt.Y, u.Y, -f.Y, rt.Z, u.Z, -f.Z })
end
CFMT.__index = function(c, k)
	local r = c._r
	if k == "Position" or k == "p" then return c._p end
	if k == "X" then return c._p.X elseif k == "Y" then return c._p.Y elseif k == "Z" then return c._p.Z end
	if k == "LookVector" or k == "lookVector" then return v3(-r[3], -r[6], -r[9]) end
	if k == "RightVector" then return v3(r[1], r[4], r[7]) end
	if k == "UpVector" then return v3(r[2], r[5], r[8]) end
	if k == "Rotation" then return cf(0, 0, 0, r) end
	if k == "Inverse" then
		return function(a)
			local t = rtrans(a._r)
			local p = rvec(t, -a._p)
			return cf(p.X, p.Y, p.Z, t)
		end
	end
	if k == "ToWorldSpace" then return function(a, b) return a * b end end
	if k == "ToObjectSpace" then return function(a, b) return a:Inverse() * b end end
	if k == "PointToWorldSpace" then return function(a, v) return a * v end end
	if k == "PointToObjectSpace" then return function(a, v) return a:Inverse() * v end end
	if k == "VectorToWorldSpace" then return function(a, v) return rvec(a._r, v) end end
	if k == "VectorToObjectSpace" then return function(a, v) return rvec(rtrans(a._r), v) end end
	if k == "Lerp" then
		return function(a, b, t) local p = a._p:Lerp(b._p, t); return cf(p.X, p.Y, p.Z, t < 0.5 and a._r or b._r) end
	end
	if k == "ToEulerAnglesXYZ" or k == "ToOrientation" or k == "ToEulerAnglesYXZ" then
		return function() return 0, 0, 0 end
	end
	if k == "GetComponents" or k == "components" then
		return function(a) local rr = a._r; return a._p.X, a._p.Y, a._p.Z, rr[1], rr[2], rr[3], rr[4], rr[5], rr[6], rr[7], rr[8], rr[9] end
	end
	if k == "FuzzyEq" then return function(a, b) return (a._p - b._p).Magnitude < 1e-4 end end
	error(tostring(k) .. " is not a valid member of CFrame", 2)
end
CFMT.__mul = function(a, b)
	if TYPES[b] == "Vector3" then return rvec(a._r, b) + a._p end
	local p = rvec(a._r, b._p) + a._p
	return cf(p.X, p.Y, p.Z, rmul(a._r, b._r))
end
CFMT.__add = function(a, v) local p = a._p + v; return cf(p.X, p.Y, p.Z, a._r) end
CFMT.__sub = function(a, v) local p = a._p - v; return cf(p.X, p.Y, p.Z, a._r) end
CFMT.__eq = function(a, b)
	if a._p ~= b._p then return false end
	for i = 1, 9 do if math.abs(a._r[i] - b._r[i]) > 1e-9 then return false end end
	return true
end
CFMT.__tostring = function(a) return tostring(a._p) end
CFrame.new = function(a, b, c, ...)
	if a == nil then return cf(0, 0, 0) end
	if TYPES[a] == "Vector3" then
		if TYPES[b] == "Vector3" then return lookat(a, b) end
		return cf(a.X, a.Y, a.Z)
	end
	local rest = { ... }
	if #rest == 9 then return cf(a, b, c, rest) end
	return cf(tonumber(a) or 0, tonumber(b) or 0, tonumber(c) or 0)
end
CFrame.Angles = function(x, y, z) return cf(0, 0, 0, angles(x or 0, y or 0, z or 0)) end
CFrame.fromEulerAnglesXYZ = CFrame.Angles
CFrame.fromEulerAnglesYXZ = function(x, y, z) return cf(0, 0, 0, angles(x or 0, y or 0, z or 0)) end
CFrame.fromOrientation = CFrame.fromEulerAnglesYXZ
CFrame.lookAt = function(a, b) return lookat(a, b) end
CFrame.fromAxisAngle = function(_, a) return cf(0, 0, 0, angles(0, a or 0, 0)) end
CFrame.fromMatrix = function(p) return cf(p.X, p.Y, p.Z) end
CFrame.identity = cf(0, 0, 0)

local Color3 = {}
local C3MT = {}
local function c3(r, g, b)
	local c = setmetatable({ R = r or 0, G = g or 0, B = b or 0 }, C3MT)
	TYPES[c] = "Color3"
	return c
end
C3MT.__index = function(c, k)
	if k == "r" then return c.R elseif k == "g" then return c.G elseif k == "b" then return c.B end
	if k == "Lerp" then return function(a, b, t) return c3(a.R + (b.R - a.R) * t, a.G + (b.G - a.G) * t, a.B + (b.B - a.B) * t) end end
	if k == "ToHSV" then return function() return 0, 0, 1 end end
	if k == "ToHex" then return function() return "ffffff" end end
	error(tostring(k) .. " is not a valid member of Color3", 2)
end
C3MT.__eq = function(a, b) return a.R == b.R and a.G == b.G and a.B == b.B end
Color3.new = function(r, g, b) return c3(r or 0, g or 0, b or 0) end
Color3.fromRGB = function(r, g, b) return c3((r or 0) / 255, (g or 0) / 255, (b or 0) / 255) end
Color3.fromHSV = function(h, s, v) return c3(v or 1, v or 1, v or 1) end
Color3.fromHex = function() return c3(1, 1, 1) end

local BrickColor = {}
local BCMT = {}
local function bc(name)
	local b = setmetatable({ Name = name or "Medium stone grey", Number = 194 }, BCMT)
	TYPES[b] = "BrickColor"
	return b
end
BCMT.__index = function(b, k)
	if k == "Color" then return c3(0.5, 0.5, 0.5) end
	if k == "r" or k == "g" or k == "b" then return 0.5 end
	error(tostring(k) .. " is not a valid member of BrickColor", 2)
end
BCMT.__eq = function(a, b) return a.Name == b.Name end
BrickColor.new = function(n) return bc(type(n) == "string" and n or "Medium stone grey") end
BrickColor.random = function() return bc("Bright red") end
BrickColor.Random = BrickColor.random
BrickColor.palette = function() return bc("Bright blue") end
for _, n in ipairs({ "Red", "Green", "Blue", "White", "Black", "Gray", "Yellow", "DarkGray" }) do
	BrickColor[n] = function() return bc(n) end
end

local UDim = {}
local UDim2 = {}
local UMT, U2MT = {}, {}
local function udim(s, o)
	local u = setmetatable({ Scale = s or 0, Offset = o or 0 }, UMT)
	TYPES[u] = "UDim"
	return u
end
UMT.__index = function(_, k) error(tostring(k) .. " is not a valid member of UDim", 2) end
UMT.__add = function(a, b) return udim(a.Scale + b.Scale, a.Offset + b.Offset) end
UMT.__sub = function(a, b) return udim(a.Scale - b.Scale, a.Offset - b.Offset) end
UMT.__eq = function(a, b) return a.Scale == b.Scale and a.Offset == b.Offset end
local function udim2(xs, xo, ys, yo)
	local u = setmetatable({ X = udim(xs, xo), Y = udim(ys, yo) }, U2MT)
	TYPES[u] = "UDim2"
	return u
end
U2MT.__index = function(u, k)
	if k == "Width" then return u.X elseif k == "Height" then return u.Y end
	if k == "Lerp" then return function(a, b, t) return udim2(a.X.Scale + (b.X.Scale - a.X.Scale) * t, a.X.Offset, a.Y.Scale + (b.Y.Scale - a.Y.Scale) * t, a.Y.Offset) end end
	error(tostring(k) .. " is not a valid member of UDim2", 2)
end
U2MT.__add = function(a, b) return udim2(a.X.Scale + b.X.Scale, a.X.Offset + b.X.Offset, a.Y.Scale + b.Y.Scale, a.Y.Offset + b.Y.Offset) end
U2MT.__sub = function(a, b) return udim2(a.X.Scale - b.X.Scale, a.X.Offset - b.X.Offset, a.Y.Scale - b.Y.Scale, a.Y.Offset - b.Y.Offset) end
U2MT.__eq = function(a, b) return a.X == b.X and a.Y == b.Y end
UDim.new = function(s, o) return udim(s or 0, o or 0) end
UDim2.new = function(a, b, c, d)
	if TYPES[a] == "UDim" then return udim2(a.Scale, a.Offset, b.Scale, b.Offset) end
	return udim2(a or 0, b or 0, c or 0, d or 0)
end
UDim2.fromScale = function(x, y) return udim2(x or 0, 0, y or 0, 0) end
UDim2.fromOffset = function(x, y) return udim2(0, x or 0, 0, y or 0) end

local function plain(name, fields)
	return function(...)
		local t = setmetatable(fields and fields(...) or {}, { __index = function() return Stub end })
		TYPES[t] = name
		return t
	end
end
local TweenInfo = { new = plain("TweenInfo", function(time, style, dir, rep, rev, delay)
	return { Time = tonumber(time) or 1, EasingStyle = style, EasingDirection = dir, RepeatCount = rep or 0,
		Reverses = rev or false, DelayTime = delay or 0 }
end) }
local NumberSequence = { new = plain("NumberSequence") }
local NumberSequenceKeypoint = { new = plain("NumberSequenceKeypoint") }
local ColorSequence = { new = plain("ColorSequence") }
local ColorSequenceKeypoint = { new = plain("ColorSequenceKeypoint") }
local NumberRange = { new = plain("NumberRange", function(a, b) return { Min = a or 0, Max = b or a or 0 } end) }
local Ray = { new = plain("Ray", function(o, d) return { Origin = o, Direction = d } end) }
local RaycastParams = { new = plain("RaycastParams", function() return { FilterDescendantsInstances = {}, IgnoreWater = false } end) }
local OverlapParams = { new = plain("OverlapParams", function() return { FilterDescendantsInstances = {} } end) }
local Region3 = { new = plain("Region3") }
local Rect = { new = plain("Rect") }
local PhysicalProperties = { new = plain("PhysicalProperties") }
local Font = { new = plain("Font"), fromEnum = plain("Font"), fromName = plain("Font") }
local DateTime = {
	now = function()
		local d = setmetatable({ UnixTimestamp = 1767225600 + math.floor(NOW), UnixTimestampMillis = (1767225600 + NOW) * 1000 },
			{ __index = function() return function() return "2026-01-01" end end })
		TYPES[d] = "DateTime"
		return d
	end,
}
DateTime.fromUnixTimestamp = DateTime.now

local Random = {}
Random.new = function(seed)
	local r = setmetatable({}, { __index = {
		NextInteger = function(_, a, b) return math.random(a, b) end,
		NextNumber = function(_, a, b) a = a or 0; b = b or 1; return a + (b - a) * math.random() end,
		NextUnitVector = function() return v3(0, 1, 0) end,
		Shuffle = function() end,
		Clone = function(self) return self end,
	} })
	TYPES[r] = "Random"
	return r
end

-- Enum: any name is accepted (the verifier checks enum names); items are memoized so == works
local ENUM_ITEMS = {}
local Enum
local function enum_type(tname)
	local t = ENUM_ITEMS[tname]
	if t then return t end
	local items = {}
	local et = setmetatable({}, {
		__index = function(_, k)
			if k == "GetEnumItems" then return function() return {} end end
			if k == "FromName" then return function(_, n) return items[n] end end
			local it = items[k]
			if not it then
				it = setmetatable({ Name = k, EnumType = tname, Value = 0 }, { __tostring = function() return "Enum." .. tname .. "." .. k end })
				TYPES[it] = "EnumItem"
				items[k] = it
			end
			return it
		end,
		__tostring = function() return tname end,
	})
	TYPES[et] = "Enum"
	ENUM_ITEMS[tname] = et
	return et
end
Enum = setmetatable({}, { __index = function(_, k)
	if k == "GetEnums" then return function() return {} end end
	return enum_type(k)
end })
TYPES[Enum] = "Enums"

-- ---- signals ---------------------------------------------------------------------------------------------------------
local SignalMT = {}
local ConnMT = {}
local function new_signal(name)
	local s = setmetatable({ _conns = {}, _waiting = {}, _name = name or "signal" }, SignalMT)
	TYPES[s] = "RBXScriptSignal"
	return s
end
local SignalMethods = {}
function SignalMethods.Connect(self, fn)
	if type(fn) ~= "function" then error("Attempt to connect failed: Passed value is not a function", 2) end
	local c = setmetatable({ Connected = true, _fn = fn, _sig = self, _ctx = current_ctx(), _block = BLOCK_OF[coroutine.running()] }, ConnMT)
	TYPES[c] = "RBXScriptConnection"
	table.insert(self._conns, c)
	return c
end
function SignalMethods.Once(self, fn)
	local c
	c = SignalMethods.Connect(self, function(...)
		c:Disconnect()
		return fn(...)
	end)
	return c
end
SignalMethods.ConnectParallel = SignalMethods.Connect
function SignalMethods.Wait(self)
	table.insert(self._waiting, coroutine.running())
	return coroutine.yield()
end
SignalMethods.connect = SignalMethods.Connect
SignalMethods.wait = SignalMethods.Wait
function SignalMethods.Fire(self, ...)
	local conns = table.clone(self._conns)
	for _, c in ipairs(conns) do
		if c.Connected then
			local co = coroutine.create(rawget(c, "_fn"))
			CTX[co] = rawget(c, "_ctx")
			BLOCK_OF[co] = rawget(c, "_block")
			resume(co, ...)
		end
	end
	local waiting = self._waiting
	self._waiting = {}
	for _, co in ipairs(waiting) do
		if coroutine.status(co) == "suspended" then resume(co, ...) end
	end
end
function SignalMethods.Count(self)
	local n = 0
	for _, c in ipairs(self._conns) do if c.Connected then n += 1 end end
	return n
end
SignalMT.__index = function(s, k)
	if k == "Connect" or k == "Once" or k == "Wait" or k == "connect" or k == "wait" or k == "ConnectParallel" then
		return SignalMethods[k]
	end
	error(tostring(k) .. " is not a valid member of RBXScriptSignal", 2)
end
ConnMT.__index = function(c, k)
	if k == "Disconnect" or k == "disconnect" then
		return function(self) self.Connected = false end
	end
	error(tostring(k) .. " is not a valid member of RBXScriptConnection", 2)
end

-- ---- API members (from MEMBERS) --------------------------------------------------------------------------------------
local PARSED = {}
local function class_info(cls)
	local p = PARSED[cls]
	if p then return p end
	local raw = MEMBERS[cls]
	if not raw then return nil end
	local sup, rest = string.match(raw, "^([^|]*)|(.*)$")
	p = { super = sup ~= "" and sup or nil, m = {} }
	for name, kind in string.gmatch(rest, "([%w_]+):(%a)") do p.m[name] = kind end
	PARSED[cls] = p
	return p
end
local function member_kind(cls, name)
	local c = cls
	while c do
		local info = class_info(c)
		if not info then return nil end
		local k = info.m[name]
		if k then return k end
		c = info.super
	end
	return nil
end
-- names that are player/character data, never objects a kid builds in Studio (workspace.Team is a bug, not a part)
local NEVER_STUDIO = { Team = true, TeamColor = true, Character = true, UserId = true, DisplayName = true, Backpack = true,
	PlayerGui = true, Humanoid = true, HumanoidRootPart = true, LocalPlayer = true, Health = true, MaxHealth = true,
	WalkSpeed = true, JumpPower = true, Position = true, CFrame = true, Size = true, Value = true }
local ANY = nil
local function ANY_MEMBER()
	if ANY then return ANY end
	ANY = { Connect = true, Wait = true, Once = true, Fire = true, Disconnect = true }
	for _, raw in pairs(MEMBERS) do
		for name, kind in string.gmatch(raw, "([%w_]+):(%a)") do
			if kind ~= "p" then ANY[name] = true end
		end
	end
	return ANY
end
local function is_a(cls, want)
	if want == "Instance" then return true end
	local c = cls
	while c do
		if c == want then return true end
		local info = class_info(c)
		if not info then return false end
		c = info.super
	end
	return false
end

-- ---- instances ------------------------------------------------------------------------------------------------------
local D = setmetatable({}, { __mode = "k" })  -- instance -> data
local InstMT = {}
local Methods = {}     -- class -> {name = fn}; looked up along the superclass chain
local Instance = {}
local game, workspace, Players

local DEFAULTS = {
	Anchored = false, CanCollide = true, CanTouch = true, CanQuery = true, Transparency = 0, Reflectance = 0,
	Locked = false, Massless = false, CastShadow = true,
	Health = 100, MaxHealth = 100, WalkSpeed = 16, JumpPower = 50, JumpHeight = 7.2, UseJumpPower = true,
	HipHeight = 2, AutoRotate = true, PlatformStand = false, Sit = false, Jump = false,
	Text = "", TextSize = 14, Visible = true, Enabled = true, Active = false, ZIndex = 1, BackgroundTransparency = 0,
	TextTransparency = 0, ImageTransparency = 0, Image = "", Value = nil, Volume = 0.5, Playing = false, Looped = false,
	TimePosition = 0, PlaybackSpeed = 1, SoundId = "", AnimationId = "", MaxActivationDistance = 10, HoldDuration = 0,
	ActionText = "Interact", ObjectText = "", RequiresLineOfSight = true, KeyboardKeyCode = nil, Gravity = 196.2,
	ClockTime = 14, Brightness = 2, FogEnd = 100000, FogStart = 0, RespawnTime = 5, CharacterAutoLoads = true,
	ResetOnSpawn = true, IgnoreGuiInset = false, DisplayOrder = 0, MaxForce = nil, Neutral = true, AutoAssignable = true,
	RequiresHandle = true, CanBeDropped = true, ManualActivationOnly = false, ToolTip = "", Disabled = false,
	Rate = 20, Lifetime = nil, Speed = nil, Range = 8, Angle = 0, TargetAngle = 0, AngularVelocity = 0,
	MotorMaxTorque = 0, LinearResponsiveness = 50, Damping = 0, Stiffness = 0, Restitution = 0, Friction = 0.3,
	UserId = 0, AccountAge = 30, DisplayName = "", Archivable = true, RunContext = nil, LoadCharacterAppearance = true,
	AutoJumpEnabled = true, DevEnableMouseLock = true, CameraMaxZoomDistance = 128, CameraMinZoomDistance = 0.5,
	Duration = 0, AttachmentPoint = nil,
}

local function inst_new(cls, name, studio)
	local inst = setmetatable({}, InstMT)
	D[inst] = { ClassName = cls, Name = name or cls, Parent = nil, children = {}, props = {}, signals = {}, attrs = {},
		tags = {}, studio = studio or false, changed = {}, destroyed = false }
	TYPES[inst] = "Instance"
	return inst
end
local function is_inst(x) return type(x) == "table" and D[x] ~= nil end

local function full_name(inst)
	local parts = {}
	local cur = inst
	while cur and cur ~= game do
		table.insert(parts, 1, D[cur].Name)
		cur = D[cur].Parent
	end
	return table.concat(parts, ".")
end

local function get_signal(inst, name)
	local d = D[inst]
	local s = d.signals[name]
	if not s then
		s = new_signal(name)
		d.signals[name] = s
	end
	return s
end

local function fire_changed(inst, prop, value)
	local d = D[inst]
	local s = d.changed[prop]
	if s then SignalMethods.Fire(s) end
	if d.signals.Changed then
		if is_a(d.ClassName, "ValueBase") and prop == "Value" then
			SignalMethods.Fire(d.signals.Changed, value)
		elseif not is_a(d.ClassName, "ValueBase") then
			SignalMethods.Fire(d.signals.Changed, prop)
		end
	end
end

local function is_descendant(inst, anc)
	local cur = D[inst].Parent
	while cur do
		if cur == anc then return true end
		cur = D[cur].Parent
	end
	return false
end

local function set_parent(inst, parent)
	local d = D[inst]
	if d.destroyed then error("The Parent property of " .. d.Name .. " is locked, current parent: NULL, new parent " .. (parent and D[parent].Name or "nil"), 3) end
	if parent ~= nil and not is_inst(parent) then error("Invalid value for Parent (Instance expected)", 3) end
	local old = d.Parent
	if old == parent then return end
	if parent == inst or (parent and is_descendant(parent, inst)) then error("Attempt to set parent of " .. d.Name .. " to itself or a descendant", 3) end
	if old then
		local oc = D[old].children
		for i, c in ipairs(oc) do if c == inst then table.remove(oc, i) break end end
		if D[old].signals.ChildRemoved then SignalMethods.Fire(D[old].signals.ChildRemoved, inst) end
	end
	d.Parent = parent
	if parent then
		table.insert(D[parent].children, inst)
		if D[parent].signals.ChildAdded then SignalMethods.Fire(D[parent].signals.ChildAdded, inst) end
		local cur = parent
		while cur do
			if D[cur].signals.DescendantAdded then SignalMethods.Fire(D[cur].signals.DescendantAdded, inst) end
			cur = D[cur].Parent
		end
		-- WaitForChild waiters
		local w = D[parent].waiters
		if w and w[d.Name] then
			local list = w[d.Name]
			w[d.Name] = nil
			for _, co in ipairs(list) do schedule(co, NOW, inst) end
		end
	end
	if d.signals.AncestryChanged then SignalMethods.Fire(d.signals.AncestryChanged, inst, parent) end
	fire_changed(inst, "Parent", parent)
end

local function find_child(inst, name)
	for _, c in ipairs(D[inst].children) do
		if D[c].Name == name then return c end
	end
	return nil
end

-- what class a studio object probably is, from the name an answer uses for it
local function guess_class(name)
	if MEMBERS[name] and not string.find(MEMBERS[name], "|!", 1, true) then return name end
	local n = string.lower(name)
	local rules = {
		{ "proximityprompt", "ProximityPrompt" }, { "prompt", "ProximityPrompt" }, { "clickdetector", "ClickDetector" },
		{ "remotefunction", "RemoteFunction" }, { "function$", "RemoteFunction" }, { "remote", "RemoteEvent" },
		{ "event$", "RemoteEvent" }, { "bindable", "BindableEvent" }, { "humanoid$", "Humanoid" },
		{ "screengui", "ScreenGui" }, { "billboard", "BillboardGui" }, { "surfacegui", "SurfaceGui" }, { "gui$", "ScreenGui" }, { "button", "TextButton" }, { "label", "TextLabel" },
		{ "textbox", "TextBox" }, { "^cframe", "Part" }, { "frame", "Frame" }, { "image", "ImageLabel" }, { "sound", "Sound" }, { "music", "Sound" },
		{ "animation", "Animation" }, { "attachment", "Attachment" }, { "particle", "ParticleEmitter" },
		{ "config", "ModuleScript" }, { "module", "ModuleScript" }, { "settings", "ModuleScript" }, { "data$", "ModuleScript" },
		{ "folder", "Folder" }, { "tool", "Tool" }, { "spawn", "SpawnLocation" }, { "light", "PointLight" },
		{ "hinge", "HingeConstraint" }, { "weld", "WeldConstraint" }, { "beam", "Beam" }, { "value$", "IntValue" },
		{ "model$", "Model" }, { "npc", "Model" }, { "camera", "Camera" }, { "highlight", "Highlight" },
	}
	for _, r in ipairs(rules) do
		if string.find(n, r[1]) then return r[2] end
	end
	return "Part"
end

local function SERVICES_TEAMS() return game and find_child(game, "Teams") end
-- a studio object whose class the name does not tell: it becomes the first of these classes that has the member the
-- answer uses first (remote:FireServer -> RemoteEvent, x.Value -> IntValue)
local LAZY_CLASSES = { "RemoteEvent", "RemoteFunction", "BindableEvent", "BindableFunction", "ProximityPrompt",
	"ClickDetector", "Sound", "IntValue", "Humanoid", "Tool", "TextButton", "ScreenGui", "Animation", "ParticleEmitter",
	"Model", "Folder" }
local function resolve_lazy(inst, k)
	local d = D[inst]
	if not d.lazy then return end
	if member_kind(d.ClassName, k) ~= nil or Methods.Instance[k] then return end
	if find_child(inst, k) then return end
	for _, cls in ipairs(d.lazy_classes or LAZY_CLASSES) do
		if member_kind(cls, k) ~= nil then
			d.ClassName = cls
			d.lazy = false
			return
		end
	end
end

local GUI_PARENT = { ScreenGui = true, Frame = true, BillboardGui = true, SurfaceGui = true, ScrollingFrame = true,
	TextButton = true, ImageButton = true, TextLabel = true, ImageLabel = true, CanvasGroup = true }
local function materialize(parent, name)
	local cls = guess_class(name)
	if parent == SERVICES_TEAMS() then cls = "Team" end
	local gui_parent = GUI_PARENT[D[parent].ClassName]
	if cls == "Part" and gui_parent then cls = "Frame" end
	local child = inst_new(cls, name, true)
	if cls == "Part" and not string.find(string.lower(name), "part") then D[child].lazy = true end
	if cls == "Frame" and gui_parent then
		D[child].lazy = true
		D[child].lazy_classes = { "Frame", "TextLabel", "TextButton", "ImageLabel", "ImageButton", "TextBox", "ScrollingFrame" }
	end
	if cls == "Model" then
		local h = inst_new("Humanoid", "Humanoid", true)
		set_parent(h, child)
		local root = inst_new("Part", "HumanoidRootPart", true)
		set_parent(root, child)
	elseif cls == "Tool" then
		set_parent(inst_new("Part", "Handle", true), child)
	elseif cls == "ScreenGui" then
		-- nothing: children are materialized on demand
	end
	set_parent(child, parent)
	event("studio_object", { name = full_name(child), class = cls })
	return child
end

local function prop_default(inst, k)
	local d = D[inst]
	local cls = d.ClassName
	if k == "Position" then return d.props.CFrame and d.props.CFrame._p or v3(0, 5, 0) end
	if k == "CFrame" then local p = d.props.Position or v3(0, 5, 0); return cf(p.X, p.Y, p.Z) end
	if k == "Size" then return is_a(cls, "GuiObject") and udim2(0, 100, 0, 50) or v3(4, 1, 2) end
	if k == "Orientation" or k == "Rotation" and is_a(cls, "BasePart") then return v3(0, 0, 0) end
	if k == "Color" then return c3(0.64, 0.64, 0.64) end
	if k == "BrickColor" or k == "TeamColor" then return bc() end
	if k == "Material" then return Enum.Material.Plastic end
	if k == "Velocity" or k == "AssemblyLinearVelocity" or k == "AssemblyAngularVelocity" then return v3(0, 0, 0) end
	if k == "BackgroundColor3" or k == "TextColor3" or k == "ImageColor3" then return c3(1, 1, 1) end
	if k == "AnchorPoint" then return v2(0, 0) end
	if k == "AbsoluteSize" or k == "AbsolutePosition" then return v2(100, 50) end
	if k == "Value" then
		if cls == "IntValue" or cls == "NumberValue" then return 0 end
		if cls == "StringValue" then return "" end
		if cls == "BoolValue" then return false end
		if cls == "Vector3Value" then return v3(0, 0, 0) end
		if cls == "CFrameValue" then return cf(0, 0, 0) end
		if cls == "Color3Value" then return c3(0, 0, 0) end
		return nil
	end
	if k == "Name" then return d.Name end
	if k == "ClassName" then return cls end
	if DEFAULTS[k] ~= nil then return DEFAULTS[k] end
	return nil
end

InstMT.__index = function(inst, k)
	local d = D[inst]
	if d.lazy then resolve_lazy(inst, k) end
	if k == "Name" then return d.Name end
	if k == "Parent" then return d.Parent end
	if k == "ClassName" then return d.ClassName end
	local v = d.props[k]
	if v ~= nil then return v end
	-- implemented methods
	local c = d.ClassName
	while c do
		local mt = Methods[c]
		if mt and mt[k] then return mt[k] end
		local info = class_info(c)
		c = info and info.super
	end
	if Methods.Instance[k] then return Methods.Instance[k] end
	local kind = member_kind(d.ClassName, k)
	if kind == "e" then return get_signal(inst, k) end
	-- a child with that name (members win over children, as in Roblox)
	if kind == nil then
		local ch = find_child(inst, k)
		if ch then return ch end
	end
	if kind == "p" then
		local ch = find_child(inst, k)
		if ch then return ch end
		local dv = prop_default(inst, k)
		if dv ~= nil then return dv end
		return nil
	end
	if kind == "f" or kind == "c" then
		note_unmodelled(d.ClassName .. ":" .. k)
		return function() return Stub end
	end
	if d.studio and string.match(k, "^%u") and not NEVER_STUDIO[k] then
		if ANY_MEMBER()[k] then error("[mock] " .. k .. " belongs to another class than " .. d.ClassName, 2) end
		return materialize(inst, k)
	end
	if MEMBERS[d.ClassName] == nil then
		note_unmodelled("class " .. d.ClassName)
		return Stub
	end
	error(tostring(k) .. " is not a valid member of " .. d.ClassName .. " \"" .. full_name(inst) .. "\"", 2)
end

local READONLY = { ClassName = true, AbsoluteSize = true, AbsolutePosition = true, UserId = true, LocalPlayer = true }

InstMT.__newindex = function(inst, k, v)
	local d = D[inst]
	if d.lazy then resolve_lazy(inst, k) end
	if k == "Parent" then return set_parent(inst, v) end
	if k == "Name" then d.Name = tostring(v); fire_changed(inst, "Name", v); return end
	if READONLY[k] and not d.engine_write then error("Unable to assign property " .. k .. ". Property is read only", 2) end
	local kind = member_kind(d.ClassName, k)
	if kind == nil and MEMBERS[d.ClassName] ~= nil and DEFAULTS[k] == nil then
		error(tostring(k) .. " is not a valid member of " .. d.ClassName .. " \"" .. full_name(inst) .. "\"", 2)
	end
	if kind == "e" or kind == "f" then
		error("Unable to assign property " .. k .. ". Property is read only", 2)
	end
	if k == "Position" and TYPES[v] == "Vector3" then
		local old = d.props.CFrame
		d.props.CFrame = cf(v.X, v.Y, v.Z, old and old._r)
	elseif k == "CFrame" and TYPES[v] == "CFrame" then
		d.props.Position = v._p
	end
	if k == "Value" and (d.ClassName == "IntValue") and type(v) == "number" then v = math.floor(v + 0.5) end
	if k == "Health" and type(v) == "number" then
		local mx = d.props.MaxHealth or 100
		v = math.clamp(v, 0, mx)
	end
	local old = d.props[k]
	if old == nil then old = prop_default(inst, k) end
	d.props[k] = v
	if old ~= v then
		fire_changed(inst, k, v)
		if k == "Health" and d.ClassName == "Humanoid" then
			if d.signals.HealthChanged then SignalMethods.Fire(d.signals.HealthChanged, v) end
			if v <= 0 and not d.dead then
				d.dead = true
				event("died", { name = full_name(inst) })
				if d.signals.Died then SignalMethods.Fire(d.signals.Died) end
			end
		end
	end
end
InstMT.__tostring = function(inst) return D[inst].Name end
InstMT.__eq = rawequal

-- ---- Instance methods ------------------------------------------------------------------------------------------------
Methods.Instance = {}
local IM = Methods.Instance
local STRONG = { ProximityPrompt = true, ClickDetector = true, Sound = true, RemoteEvent = true, RemoteFunction = true,
	BindableEvent = true, Animation = true, ParticleEmitter = true, Attachment = true, SurfaceGui = true, BillboardGui = true }
function IM.FindFirstChild(self, name, recursive)
	if recursive then
		for _, c in ipairs(self:GetDescendants()) do if D[c].Name == name then return c end end
		return nil
	end
	local c = find_child(self, name)
	-- an object the answer told the kid to put inside a studio part ("a ProximityPrompt inside the lamp")
	if c == nil and D[self].studio and not D[self].service and type(name) == "string" and STRONG[guess_class(name)] then
		return materialize(self, name)
	end
	return c
end
function IM.FindFirstChildOfClass(self, cls)
	for _, c in ipairs(D[self].children) do if D[c].ClassName == cls then return c end end
	return nil
end
function IM.FindFirstChildWhichIsA(self, cls, recursive)
	local list = recursive and self:GetDescendants() or D[self].children
	for _, c in ipairs(list) do if is_a(D[c].ClassName, cls) then return c end end
	return nil
end
function IM.FindFirstAncestor(self, name)
	local cur = D[self].Parent
	while cur do if D[cur].Name == name then return cur end cur = D[cur].Parent end
	return nil
end
function IM.FindFirstAncestorOfClass(self, cls)
	local cur = D[self].Parent
	while cur do if D[cur].ClassName == cls then return cur end cur = D[cur].Parent end
	return nil
end
function IM.FindFirstAncestorWhichIsA(self, cls)
	local cur = D[self].Parent
	while cur do if is_a(D[cur].ClassName, cls) then return cur end cur = D[cur].Parent end
	return nil
end
function IM.FindFirstDescendant(self, name)
	for _, c in ipairs(self:GetDescendants()) do if D[c].Name == name then return c end end
	return nil
end
function IM.WaitForChild(self, name, timeout)
	local c = find_child(self, name)
	if c then return c end
	local d = D[self]
	d.waiters = d.waiters or {}
	d.waiters[name] = d.waiters[name] or {}
	local co = coroutine.running()
	table.insert(d.waiters[name], co)
	local limit = tonumber(timeout)
	-- studio objects the answer told the user to create: appear after 2 s if no script made them
	if d.studio then
		schedule(co, NOW + 2, "__studio")
	elseif limit then
		schedule(co, NOW + limit, "__timeout")
	else
		schedule(co, NOW + 5, "__infinite")
	end
	while true do
		local got = coroutine.yield()
		local now_c = find_child(self, name)
		if now_c then
			-- drop stale wakeups
			for i = #QUEUE, 1, -1 do if QUEUE[i].co == co then table.remove(QUEUE, i) end end
			local list = d.waiters and d.waiters[name]
			if list then for i = #list, 1, -1 do if list[i] == co then table.remove(list, i) end end end
			return now_c
		end
		if got == "__studio" then
			return materialize(self, name)
		elseif got == "__timeout" then
			return nil
		elseif got == "__infinite" then
			table.insert(REPORT.warns, { msg = "Infinite yield possible on '" .. full_name(self) .. ":WaitForChild(\"" .. name .. "\")'",
				block = BLOCK_OF[co], phase = PHASE, t = NOW })
			-- keep waiting (Roblox waits forever)
		end
	end
end
function IM.GetChildren(self) return table.clone(D[self].children) end
function IM.GetDescendants(self)
	local out = {}
	local function walk(x)
		for _, c in ipairs(D[x].children) do table.insert(out, c); walk(c) end
	end
	walk(self)
	return out
end
function IM.IsA(self, cls) return is_a(D[self].ClassName, cls) end
function IM.IsDescendantOf(self, anc) return is_descendant(self, anc) end
function IM.IsAncestorOf(self, x) return is_descendant(x, self) end
function IM.GetFullName(self) return full_name(self) end
function IM.Destroy(self)
	local d = D[self]
	if d.destroyed then return end
	for _, c in ipairs(table.clone(d.children)) do IM.Destroy(c) end
	if d.Parent then set_parent(self, nil) end
	d.destroyed = true
	if d.signals.Destroying then SignalMethods.Fire(d.signals.Destroying) end
	for _, s in pairs(d.signals) do for _, c in ipairs(s._conns) do c.Connected = false end end
	event("destroyed", { name = d.Name })
end
IM.Remove = IM.Destroy
function IM.ClearAllChildren(self) for _, c in ipairs(table.clone(D[self].children)) do IM.Destroy(c) end end
local function clone(self)
	local d = D[self]
	local n = inst_new(d.ClassName, d.Name, d.studio)
	local nd = D[n]
	for k, v in pairs(d.props) do nd.props[k] = v end
	for k, v in pairs(d.attrs) do nd.attrs[k] = v end
	for k in pairs(d.tags) do nd.tags[k] = true end
	nd.source_block = d.source_block
	for _, c in ipairs(d.children) do set_parent(clone(c), n) end
	return n
end
IM.Clone = clone
function IM.GetAttribute(self, k) return D[self].attrs[k] end
function IM.SetAttribute(self, k, v)
	D[self].attrs[k] = v
	local s = D[self].changed["@" .. k]
	if s then SignalMethods.Fire(s) end
	if D[self].signals.AttributeChanged then SignalMethods.Fire(D[self].signals.AttributeChanged, k) end
end
function IM.GetAttributes(self) return table.clone(D[self].attrs) end
function IM.GetAttributeChangedSignal(self, k)
	local d = D[self]
	d.changed["@" .. k] = d.changed["@" .. k] or new_signal("attr")
	return d.changed["@" .. k]
end
function IM.GetPropertyChangedSignal(self, k)
	local d = D[self]
	if d.lazy then resolve_lazy(self, k) end
	if member_kind(d.ClassName, k) == nil and MEMBERS[d.ClassName] ~= nil and k ~= "Name" and k ~= "Parent" then
		error(tostring(k) .. " is not a valid property name.", 2)
	end
	d.changed[k] = d.changed[k] or new_signal("prop")
	return d.changed[k]
end
function IM.AddTag(self, tag) D[self].tags[tag] = true end
function IM.RemoveTag(self, tag) D[self].tags[tag] = nil end
function IM.HasTag(self, tag) return D[self].tags[tag] == true end
function IM.GetTags(self) local t = {} for k in pairs(D[self].tags) do table.insert(t, k) end return t end
function IM.GetActor() return nil end
function IM.IsPropertyModified() return false end

-- parts and models
Methods.BasePart = {
	GetTouchingParts = function() return {} end,
	GetConnectedParts = function() return {} end,
	SetNetworkOwner = function(self, p)
		if p ~= nil and not is_inst(p) then error("Unable to cast value to Object", 2) end
		if not D[self].props.Anchored then return end
		error("Network Ownership API cannot be called on Anchored parts or parts welded to Anchored parts.", 2)
	end,
	GetNetworkOwner = function() return nil end,
	SetNetworkOwnershipAuto = function() end,
	ApplyImpulse = function() end,
	ApplyAngularImpulse = function() end,
	GetMass = function() return 1 end,
	BreakJoints = function() end,
	GetRootPart = function(self) return self end,
	CanCollideWith = function() return true end,
	GetVelocityAtPosition = function() return v3(0, 0, 0) end,
	Resize = function() return true end,
}
local function model_pivot(self)
	local pp = D[self].props.PrimaryPart
	if pp then return pp.CFrame end
	for _, c in ipairs(self:GetDescendants()) do
		if is_a(D[c].ClassName, "BasePart") then return c.CFrame end
	end
	return cf(0, 0, 0)
end
Methods.PVInstance = {
	GetPivot = function(self)
		if is_a(D[self].ClassName, "BasePart") then return self.CFrame end
		return model_pivot(self)
	end,
	PivotTo = function(self, c)
		if is_a(D[self].ClassName, "BasePart") then self.CFrame = c return end
		local old = model_pivot(self)
		for _, p in ipairs(self:GetDescendants()) do
			if is_a(D[p].ClassName, "BasePart") then p.CFrame = c * (old:Inverse() * p.CFrame) end
		end
	end,
}
Methods.Model = {
	SetPrimaryPartCFrame = function(self, c) Methods.PVInstance.PivotTo(self, c) end,
	GetPrimaryPartCFrame = function(self) return model_pivot(self) end,
	MoveTo = function(self, p) Methods.PVInstance.PivotTo(self, cf(p.X, p.Y, p.Z)) end,
	GetBoundingBox = function(self) return model_pivot(self), v3(4, 4, 4) end,
	GetExtentsSize = function() return v3(4, 4, 4) end,
	ScaleTo = function() end,
	GetScale = function() return 1 end,
}

-- humanoid / animation
local function anim_track(anim)
	local t = inst_new("AnimationTrack", "AnimationTrack")
	D[t].props.Animation = anim
	return t
end
Methods.AnimationTrack = {
	Play = function(self) D[self].props.IsPlaying = true; event("anim_play", {}) end,
	Stop = function(self) D[self].props.IsPlaying = false; if D[self].signals.Stopped then SignalMethods.Fire(D[self].signals.Stopped) end end,
	AdjustSpeed = function() end, AdjustWeight = function() end,
	GetMarkerReachedSignal = function(self, n) return get_signal(self, "Marker_" .. tostring(n)) end,
	GetTimeOfKeyframe = function() return 0 end,
}
Methods.Animator = {
	LoadAnimation = function(self, a)
		if not is_inst(a) or D[a].ClassName ~= "Animation" then error("Unable to cast value to Object", 2) end
		return anim_track(a)
	end,
	GetPlayingAnimationTracks = function() return {} end,
}
Methods.Humanoid = {
	TakeDamage = function(self, n)
		if type(n) ~= "number" then error("Unable to cast " .. type(n) .. " to float", 2) end
		if self:FindFirstChildOfClass("ForceField") or (D[self].Parent and D[self].Parent:FindFirstChildOfClass("ForceField")) then return end
		self.Health = self.Health - n
	end,
	LoadAnimation = Methods.Animator.LoadAnimation,
	MoveTo = function(self, p) event("move_to", {}); task.delay(0.5, function() if D[self].signals.MoveToFinished then SignalMethods.Fire(D[self].signals.MoveToFinished, true) end end) end,
	ChangeState = function() end,
	GetState = function() return Enum.HumanoidStateType.Running end,
	SetStateEnabled = function() end,
	GetStateEnabled = function() return true end,
	EquipTool = function(self, tool) tool.Parent = D[self].Parent end,
	UnequipTools = function() end,
	GetAppliedDescription = function() return Stub end,
	ApplyDescription = function() end,
	AddAccessory = function(self, a) a.Parent = D[self].Parent end,
	GetAccessories = function() return {} end,
	BuildRigFromAttachments = function() end,
	GetPlayingAnimationTracks = function() return {} end,
	Move = function() end,
}
Methods.Sound = {
	Play = function(self) D[self].props.Playing = true; event("sound_play", {}) end,
	Stop = function(self) D[self].props.Playing = false end,
	Pause = function(self) D[self].props.Playing = false end,
	Resume = function(self) D[self].props.Playing = true end,
}
Methods.ParticleEmitter = { Emit = function() event("emit", {}) end, Clear = function() end }
Methods.Tool = { Activate = function(self) if D[self].signals.Activated then SignalMethods.Fire(D[self].signals.Activated) end end, Deactivate = function() end }
Methods.BindableEvent = {
	Fire = function(self, ...) local s = get_signal(self, "Event"); SignalMethods.Fire(s, ...) end,
}
Methods.BindableFunction = {
	Invoke = function(self, ...)
		local cb = D[self].props.OnInvoke
		if not cb then error("[mock] BindableFunction has no OnInvoke", 2) end
		return cb(...)
	end,
}
Methods.GuiObject = { TweenPosition = function() return true end, TweenSize = function() return true end, TweenSizeAndPosition = function() return true end }
Methods.GuiButton = {}
Methods.LayerCollector = {}
Methods.ProximityPrompt = { InputHoldBegin = function() end, InputHoldEnd = function() end }

-- remotes (one VM: client and server share it; the receiving side runs in its own context)
local LOCAL_PLAYER = nil
local function serializable(v, depth)
	depth = depth or 0
	if depth > 20 then return true end
	if type(v) == "function" then return false end
	if type(v) == "table" and TYPES[v] == nil then
		for _, x in pairs(v) do if not serializable(x, depth + 1) then return false end end
	end
	return true
end
Methods.RemoteEvent = {
	FireServer = function(self, ...)
		if current_ctx() ~= "client" then error("FireServer can only be called from the client", 2) end
		for _, a in ipairs({ ... }) do if not serializable(a) then error("[mock] non-serializable remote argument", 2) end end
		event("fire_server", { remote = D[self].Name })
		local s = get_signal(self, "OnServerEvent")
		local args = table.pack(...)
		local plr = LOCAL_PLAYER
		task.defer(function() CTX[coroutine.running()] = "server"; SignalMethods.Fire(s, plr, table.unpack(args, 1, args.n)) end)
	end,
	FireClient = function(self, player, ...)
		if current_ctx() ~= "server" then error("FireClient can only be called from the server", 2) end
		if not is_inst(player) or D[player].ClassName ~= "Player" then error("FireClient: player argument must be a Player object", 2) end
		event("fire_client", { remote = D[self].Name })
		local s = get_signal(self, "OnClientEvent")
		local args = table.pack(...)
		task.defer(function() CTX[coroutine.running()] = "client"; SignalMethods.Fire(s, table.unpack(args, 1, args.n)) end)
	end,
	FireAllClients = function(self, ...)
		if current_ctx() ~= "server" then error("FireAllClients can only be called from the server", 2) end
		event("fire_all", { remote = D[self].Name })
		local s = get_signal(self, "OnClientEvent")
		local args = table.pack(...)
		task.defer(function() CTX[coroutine.running()] = "client"; SignalMethods.Fire(s, table.unpack(args, 1, args.n)) end)
	end,
}
Methods.UnreliableRemoteEvent = Methods.RemoteEvent
Methods.RemoteFunction = {
	InvokeServer = function(self, ...)
		if current_ctx() ~= "client" then error("InvokeServer can only be called from the client", 2) end
		local cb = D[self].props.OnServerInvoke
		if not cb then
			-- Roblox yields until a callback is set
			local t0 = NOW
			while not D[self].props.OnServerInvoke and NOW - t0 < 5 do task.wait(0.1) end
			cb = D[self].props.OnServerInvoke
			if not cb then error("[mock] OnServerInvoke never set", 2) end
		end
		local co = coroutine.running()
		local prev = CTX[co]
		CTX[co] = "server"
		local res = table.pack(pcall(cb, LOCAL_PLAYER, ...))
		CTX[co] = prev
		if not res[1] then error(res[2], 0) end
		return table.unpack(res, 2, res.n)
	end,
	InvokeClient = function(self, player, ...)
		local cb = D[self].props.OnClientInvoke
		if not cb then return nil end
		return cb(...)
	end,
}

-- ---- services --------------------------------------------------------------------------------------------------------
local SERVICES = {}
local function service(cls, name)
	local s = SERVICES[cls]
	if s then return s end
	s = inst_new(cls, name or cls, true)
	D[s].service = true
	SERVICES[cls] = s
	if game then set_parent(s, game) end
	return s
end

game = inst_new("DataModel", "Game", false)
D[game].props.PlaceId = 0
D[game].props.GameId = 0
D[game].props.JobId = ""
D[game].props.CreatorId = 0
D[game].props.PrivateServerId = ""
D[game].props.PrivateServerOwnerId = 0
local WORLD_LAZY = { "Part", "Seat", "VehicleSeat", "SpawnLocation", "MeshPart", "Model", "ProximityPrompt", "ClickDetector",
	"Sound", "ParticleEmitter", "Tool", "SurfaceGui", "BillboardGui", "PointLight", "Attachment" }
local GUI_LAZY = { "TextButton", "TextLabel", "ImageButton", "ImageLabel", "Frame", "TextBox", "ScreenGui", "BillboardGui" }
local CLOSE_FNS = {}
Methods.DataModel = {
	GetService = function(self, name)
		if type(name) ~= "string" then error("Argument 1 missing or nil", 2) end
		if MEMBERS[name] == nil and name ~= "Workspace" then error("'" .. name .. "' is not a valid Service name", 2) end
		return service(name)
	end,
	FindService = function(self, name) return SERVICES[name] end,
	BindToClose = function(self, fn)
		if current_ctx() ~= "server" then error("BindToClose can only be called on the server.", 2) end
		table.insert(CLOSE_FNS, { fn = fn, ctx = "server", block = BLOCK_OF[coroutine.running()] })
	end,
	IsLoaded = function() return true end,
	Shutdown = function() end,
}
Methods.DataModel.getService = Methods.DataModel.GetService
workspace = service("Workspace", "Workspace")
SERVICES.Workspace = workspace
Methods.Workspace = {
	Raycast = function() return nil end,
	GetPartBoundsInBox = function() return {} end,
	GetPartBoundsInRadius = function() return {} end,
	GetPartsInPart = function() return {} end,
	FindPartOnRay = function() return nil, v3(0, 0, 0) end,
	FindPartOnRayWithIgnoreList = function() return nil, v3(0, 0, 0) end,
	FindPartsInRegion3 = function() return {} end,
	GetServerTimeNow = function() return 1767225600 + NOW end,
	Spherecast = function() return nil end,
	Blockcast = function() return nil end,
	Shapecast = function() return nil end,
	BulkMoveTo = function() end,
}
D[workspace].props.Gravity = 196.2
D[game].props.Workspace = workspace
local baseplate = inst_new("Part", "Baseplate", true)
baseplate.Anchored = true
set_parent(baseplate, workspace)
local terrain = inst_new("Terrain", "Terrain", false)
set_parent(terrain, workspace)
D[workspace].props.Terrain = terrain

Players = service("Players")
local PLAYERS_LIST = {}
Methods.Players = {
	GetPlayers = function() return table.clone(PLAYERS_LIST) end,
	GetPlayerFromCharacter = function(self, m)
		if m == nil then return nil end
		for _, p in ipairs(PLAYERS_LIST) do if D[p].props.Character == m then return p end end
		return nil
	end,
	GetPlayerByUserId = function(self, id)
		for _, p in ipairs(PLAYERS_LIST) do if D[p].props.UserId == id then return p end end
		return nil
	end,
	GetUserIdFromNameAsync = function() return 1001 end,
	GetNameFromUserIdAsync = function() return "Player1" end,
	GetUserThumbnailAsync = function() return "rbxasset://thumb", true end,
	GetFriendsAsync = function() return Stub end,
	GetHumanoidDescriptionFromUserId = function() return inst_new("HumanoidDescription") end,
	CreateHumanoidModelFromDescription = function() return inst_new("Model") end,
}

for _, n in ipairs({ "ReplicatedStorage", "ServerStorage", "ServerScriptService", "StarterGui", "StarterPack",
	"StarterPlayer", "Lighting", "SoundService", "Teams", "ReplicatedFirst", "Chat", "TextChatService" }) do
	service(n)
end
local StarterPlayer = SERVICES.StarterPlayer
local SPS = inst_new("StarterPlayerScripts", "StarterPlayerScripts", true)
set_parent(SPS, StarterPlayer)
local SCS = inst_new("StarterCharacterScripts", "StarterCharacterScripts", true)
set_parent(SCS, StarterPlayer)
D[StarterPlayer].props.CharacterWalkSpeed = 16
D[StarterPlayer].props.CharacterJumpPower = 50

local TweenService = service("TweenService")
local TWEENS = {}
Methods.TweenService = {
	Create = function(self, inst, info, goals)
		if not is_inst(inst) then error("Unable to cast value to Object", 2) end
		if TYPES[info] ~= "TweenInfo" then error("Unable to cast value to TweenInfo", 2) end
		if type(goals) ~= "table" then error("Unable to cast to Dictionary", 2) end
		for k in pairs(goals) do
			if D[inst].lazy then resolve_lazy(inst, k) end
			if member_kind(D[inst].ClassName, k) ~= "p" and MEMBERS[D[inst].ClassName] then
				error("TweenService:Create property named '" .. tostring(k) .. "' cannot be tweened due to type mismatch (property is a 'nil', but given type is 'unknown')", 2)
			end
		end
		local tw = inst_new("Tween", "Tween")
		D[tw].props.Instance = inst
		D[tw].props.TweenInfo = info
		D[tw].props.PlaybackState = Enum.PlaybackState.Begin
		D[tw].goals = goals
		return tw
	end,
	GetValue = function(self, a) return a end,
}
Methods.Tween = {
	Play = function(self)
		local d = D[self]
		d.props.PlaybackState = Enum.PlaybackState.Playing
		d.gen = (d.gen or 0) + 1
		local gen = d.gen
		local info = d.props.TweenInfo
		event("tween_play", { target = D[d.props.Instance].Name })
		task.delay((info.Time or 1) + (info.DelayTime or 0), function()
			if d.gen ~= gen or d.props.PlaybackState ~= Enum.PlaybackState.Playing then return end
			local target = d.props.Instance
			for k, v in pairs(d.goals) do target[k] = v end
			if info.Reverses then
				-- ends where it started; the mock skips the way back
			end
			d.props.PlaybackState = Enum.PlaybackState.Completed
			if d.signals.Completed then SignalMethods.Fire(d.signals.Completed, Enum.PlaybackState.Completed) end
		end)
	end,
	Cancel = function(self) D[self].props.PlaybackState = Enum.PlaybackState.Cancelled end,
	Pause = function(self) D[self].props.PlaybackState = Enum.PlaybackState.Paused end,
}

-- DataStores: in memory; writes are recorded; GetAsync can be made to fail (DS_FAIL)
local DSS = service("DataStoreService")
local STORES = {}
local WRITES = {}
local READS = {}
local function check_ds_ctx()
	if current_ctx() ~= "server" then error("DataStore can't be accessed from client", 3) end
end
local function ds_value_ok(v, depth)
	depth = depth or 0
	local t = type(v)
	if t == "number" or t == "string" or t == "boolean" or v == nil then return true end
	if t == "table" and TYPES[v] == nil then
		for k, x in pairs(v) do
			if type(k) ~= "string" and type(k) ~= "number" then return false end
			if not ds_value_ok(x, depth + 1) then return false end
		end
		return true
	end
	return false
end
local function make_store(name, ordered)
	local key = (ordered and "O:" or "") .. tostring(name)
	if STORES[key] then return STORES[key] end
	local data = {}
	local st = inst_new(ordered and "OrderedDataStore" or "DataStore", tostring(name))
	local function write(k, v, how)
		if not ds_value_ok(v) then error("Cannot store " .. typeof(v) .. " in data store. Data stores can only accept valid UTF-8 characters.", 3) end
		task.wait(0.05)
		data[tostring(k)] = v
		table.insert(WRITES, { store = tostring(name), key = tostring(k), how = how, t = NOW, phase = PHASE, failed_load = READS[tostring(k)] == "failed" })
		event("ds_write", { key = tostring(k), how = how })
	end
	D[st].ds = {
		GetAsync = function(self, k)
			check_ds_ctx()
			task.wait(0.05)
			if DS_FAIL then
				READS[tostring(k)] = "failed"
				event("ds_read_failed", { key = tostring(k) })
				error("502: API Services rejected request with error. HTTP 500 (Internal Server Error)", 2)
			end
			READS[tostring(k)] = "ok"
			return data[tostring(k)], nil
		end,
		SetAsync = function(self, k, v) check_ds_ctx(); write(k, v, "set") end,
		UpdateAsync = function(self, k, fn)
			check_ds_ctx()
			task.wait(0.05)
			if DS_FAIL then
				READS[tostring(k)] = "failed"
				error("502: API Services rejected request with error. HTTP 500 (Internal Server Error)", 2)
			end
			local new = fn(data[tostring(k)], nil)
			if new ~= nil then write(k, new, "update") end
			return new
		end,
		IncrementAsync = function(self, k, n) check_ds_ctx(); local v = (data[tostring(k)] or 0) + (n or 1); write(k, v, "increment"); return v end,
		RemoveAsync = function(self, k) check_ds_ctx(); local v = data[tostring(k)]; data[tostring(k)] = nil; return v end,
		GetSortedAsync = function()
			check_ds_ctx()
			local pages = inst_new("DataStorePages", "Pages")
			D[pages].props.IsFinished = true
			D[pages].ds = { GetCurrentPage = function() return {} end, AdvanceToNextPageAsync = function() end }
			return pages
		end,
		ListKeysAsync = function() return Stub end,
		GetVersionAsync = function() return nil end,
	}
	STORES[key] = st
	return st
end
Methods.DataStore = setmetatable({}, { __index = function() return nil end })
Methods.GlobalDataStore = Methods.DataStore
Methods.DataStoreService = {
	GetDataStore = function(self, name, scope)
		check_ds_ctx()
		if type(name) ~= "string" then error("Unable to cast value to std::string", 2) end
		return make_store(name, false)
	end,
	GetOrderedDataStore = function(self, name) check_ds_ctx(); return make_store(name, true) end,
	GetGlobalDataStore = function(self) check_ds_ctx(); return make_store("global", false) end,
	GetRequestBudgetForRequestType = function() return 60 end,
}
-- DataStore methods resolve through D[inst].ds
local base_index = InstMT.__index
InstMT.__index = function(inst, k)
	local d = D[inst]
	if d and d.ds and d.ds[k] then return d.ds[k] end
	if d and inst == Players and k == "LocalPlayer" then
		if current_ctx() == "client" then return LOCAL_PLAYER end
		return nil
	end
	return base_index(inst, k)
end

local RunService = service("RunService")
Methods.RunService = {
	IsServer = function() return current_ctx() == "server" end,
	IsClient = function() return current_ctx() == "client" end,
	IsStudio = function() return false end,
	IsRunning = function() return true end,
	IsRunMode = function() return false end,
	BindToRenderStep = function(self, name, prio, fn)
		if current_ctx() ~= "client" then error("BindToRenderStep can only be called from the client", 2) end
		get_signal(self, "RenderStepped"):Connect(fn)
	end,
	UnbindFromRenderStep = function() end,
}

local UIS = service("UserInputService")
D[UIS].props.KeyboardEnabled = true
D[UIS].props.TouchEnabled = false
D[UIS].props.MouseEnabled = true
D[UIS].props.GamepadEnabled = false
Methods.UserInputService = {
	IsKeyDown = function() return false end,
	IsMouseButtonPressed = function() return false end,
	GetMouseLocation = function() return v2(400, 300) end,
	GetMouseDelta = function() return v2(0, 0) end,
	GetKeysPressed = function() return {} end,
	GetFocusedTextBox = function() return nil end,
	GetLastInputType = function() return Enum.UserInputType.Keyboard end,
	GetConnectedGamepads = function() return {} end,
}
local CAS = service("ContextActionService")
local CAS_ACTIONS = {}
Methods.ContextActionService = {
	BindAction = function(self, name, fn, touch, ...)
		if type(fn) ~= "function" then error("Argument 2 missing or nil", 2) end
		CAS_ACTIONS[name] = { fn = fn, ctx = current_ctx(), block = BLOCK_OF[coroutine.running()] }
	end,
	BindActionAtPriority = function(self, name, fn, touch, prio, ...) CAS_ACTIONS[name] = { fn = fn, ctx = current_ctx(), block = BLOCK_OF[coroutine.running()] } end,
	UnbindAction = function(self, name) CAS_ACTIONS[name] = nil end,
	SetTitle = function() end, SetImage = function() end, SetPosition = function() end, GetButton = function() return nil end,
}

local CollectionService = service("CollectionService")
local function tagged(tag)
	local out = {}
	local function walk(x)
		for _, c in ipairs(D[x].children) do
			if D[c].tags[tag] then table.insert(out, c) end
			walk(c)
		end
	end
	walk(game)
	return out
end
Methods.CollectionService = {
	GetTagged = function(self, tag) return tagged(tag) end,
	AddTag = function(self, inst, tag) D[inst].tags[tag] = true; local s = D[self].signals["Added_" .. tag]; if s then SignalMethods.Fire(s, inst) end end,
	RemoveTag = function(self, inst, tag) D[inst].tags[tag] = nil end,
	HasTag = function(self, inst, tag) return D[inst].tags[tag] == true end,
	GetTags = function(self, inst) return IM.GetTags(inst) end,
	GetInstanceAddedSignal = function(self, tag) return get_signal(self, "Added_" .. tostring(tag)) end,
	GetInstanceRemovedSignal = function(self, tag) return get_signal(self, "Removed_" .. tostring(tag)) end,
	GetAllTags = function() return {} end,
}
local Debris = service("Debris")
Methods.Debris = {
	AddItem = function(self, inst, t)
		task.delay(tonumber(t) or 10, function() if is_inst(inst) then IM.Destroy(inst) end end)
	end,
}
local MPS = service("MarketplaceService")
Methods.MarketplaceService = {
	PromptProductPurchase = function(self, p, id) event("prompt_product", { id = id }) end,
	PromptGamePassPurchase = function(self, p, id) event("prompt_pass", { id = id }) end,
	PromptPurchase = function() event("prompt_purchase", {}) end,
	UserOwnsGamePassAsync = function(self, uid, id)
		if current_ctx() ~= "server" and false then end
		task.wait(0.05)
		return false
	end,
	PlayerOwnsAsset = function() return false end,
	GetProductInfo = function() return { Name = "Item", PriceInRobux = 10, Description = "" } end,
	GetDeveloperProductsAsync = function() return Stub end,
	PromptPremiumPurchase = function() end,
}
local HttpService = service("HttpService")
local function json_encode(v, depth)
	depth = depth or 0
	local t = type(v)
	if t == "nil" then return "null" end
	if t == "boolean" or t == "number" then return tostring(v) end
	if t == "string" then return string.format("%q", v) end
	if t == "table" and TYPES[v] == nil then
		if #v > 0 then
			local parts = {}
			for _, x in ipairs(v) do table.insert(parts, json_encode(x, depth + 1)) end
			return "[" .. table.concat(parts, ",") .. "]"
		end
		local parts = {}
		for k, x in pairs(v) do table.insert(parts, string.format("%q", tostring(k)) .. ":" .. json_encode(x, depth + 1)) end
		return "{" .. table.concat(parts, ",") .. "}"
	end
	return "null"
end
local JSON_STASH = {}
Methods.HttpService = {
	JSONEncode = function(self, v) local s = json_encode(v); JSON_STASH[s] = v; return s end,
	JSONDecode = function(self, s)
		if JSON_STASH[s] ~= nil then return JSON_STASH[s] end
		note_unmodelled("JSONDecode")
		return Stub
	end,
	GenerateGUID = function() return "00000000-0000-0000-0000-000000000000" end,
	UrlEncode = function(self, s) return s end,
	GetAsync = function() error("[mock] no network", 2) end,
	PostAsync = function() error("[mock] no network", 2) end,
	RequestAsync = function() error("[mock] no network", 2) end,
}
local Teams = SERVICES.Teams
Methods.Teams = { GetTeams = function(self) return self:GetChildren() end }
Methods.Team = { GetPlayers = function(self) local o = {} for _, p in ipairs(PLAYERS_LIST) do if D[p].props.Team == self then table.insert(o, p) end end return o end }
local BadgeService = service("BadgeService")
Methods.BadgeService = {
	AwardBadge = function(self, uid, id) event("badge", { id = id }); return true end,
	AwardBadgeAsync = function(self, uid, id) event("badge", { id = id }); return true end,
	UserHasBadgeAsync = function() return false end,
	GetBadgeInfoAsync = function() return { IsEnabled = true, Name = "Badge" } end,
}
local TeleportService = service("TeleportService")
Methods.TeleportService = {
	Teleport = function() event("teleport", {}) end,
	TeleportAsync = function() event("teleport", {}); return Stub end,
	TeleportToPlaceInstance = function() event("teleport", {}) end,
	ReserveServer = function() return "code", "id" end,
	GetLocalPlayerTeleportData = function() return nil end,
}
local PhysicsService = service("PhysicsService")
local GROUPS = { Default = true }
Methods.PhysicsService = {
	RegisterCollisionGroup = function(self, n) GROUPS[n] = true end,
	CreateCollisionGroup = function(self, n) GROUPS[n] = true; return 1 end,
	CollisionGroupSetCollidable = function(self, a, b, v)
		if not GROUPS[a] or not GROUPS[b] then error("Collision group does not exist", 2) end
	end,
	IsCollisionGroupRegistered = function(self, n) return GROUPS[n] == true end,
	GetRegisteredCollisionGroups = function() return {} end,
	SetPartCollisionGroup = function() end,
	CollisionGroupsAreCollidable = function() return true end,
	GetMaxCollisionGroups = function() return 32 end,
}
local Pathfinding = service("PathfindingService")
Methods.PathfindingService = {
	CreatePath = function()
		local p = inst_new("Path", "Path")
		D[p].props.Status = Enum.PathStatus.Success
		return p
	end,
	FindPathAsync = function() local p = inst_new("Path", "Path"); D[p].props.Status = Enum.PathStatus.Success; return p end,
}
Methods.Path = {
	ComputeAsync = function() task.wait(0.05) end,
	GetWaypoints = function() return {} end,
	CheckOcclusionAsync = function() return -1 end,
}
local StarterGui = SERVICES.StarterGui
Methods.StarterGui = {
	SetCore = function(self, n, v) if current_ctx() ~= "client" then error("SetCore can only be called from the client", 2) end end,
	GetCore = function() return nil end,
	SetCoreGuiEnabled = function() end,
	GetCoreGuiEnabled = function() return true end,
}
local TextService = service("TextService")
Methods.TextService = {
	FilterStringAsync = function(self, s)
		local r = inst_new("TextFilterResult", "TextFilterResult")
		D[r].ds = { GetNonChatStringForBroadcastAsync = function() return s end, GetChatForUserAsync = function() return s end,
			GetNonChatStringForUserAsync = function() return s end }
		return r
	end,
	GetTextSize = function() return v2(50, 14) end,
}
local Messaging = service("MessagingService")
Methods.MessagingService = { PublishAsync = function() end, SubscribeAsync = function() return { Disconnect = function() end } end }
local MemoryStore = service("MemoryStoreService")
Methods.MemoryStoreService = { GetSortedMap = function() return Stub end, GetQueue = function() return Stub end, GetHashMap = function() return Stub end }
local Lighting = SERVICES.Lighting
Methods.Lighting = { GetMinutesAfterMidnight = function() return 14 * 60 end, SetMinutesAfterMidnight = function(self, m) self.ClockTime = m / 60 end, GetMoonDirection = function() return v3(0, 1, 0) end, GetSunDirection = function() return v3(0, 1, 0) end }
local ProximityPromptService = service("ProximityPromptService")
local ChatService = SERVICES.Chat
Methods.Chat = { Chat = function() end, FilterStringForBroadcast = function(self, s) return s end }
Methods.TextChatService = {}
local GroupService = service("GroupService")
Methods.GroupService = { GetGroupInfoAsync = function() return { Name = "Group" } end, GetGroupsAsync = function() return {} end }
local PolicyService = service("PolicyService")
Methods.PolicyService = { GetPolicyInfoForPlayerAsync = function() return { ArePaidRandomItemsRestricted = false, AllowedExternalLinkReferences = {} } end }
local SocialService = service("SocialService")
Methods.SocialService = { PromptGameInvite = function() end, CanSendGameInviteAsync = function() return true end }
local GuiService = service("GuiService")
Methods.GuiService = { GetGuiInset = function() return v2(0, 36), v2(0, 0) end }
local VRService = service("VRService")
local HapticService = service("HapticService")
local LocalizationService = service("LocalizationService")
local AnalyticsService = service("AnalyticsService")
Methods.AnalyticsService = setmetatable({}, { __index = function() return function() end end })

-- camera (client)
local camera = inst_new("Camera", "Camera", false)
set_parent(camera, workspace)
D[camera].props.CFrame = cf(0, 10, 10)
D[camera].props.FieldOfView = 70
D[camera].props.ViewportSize = v2(800, 600)
D[workspace].props.CurrentCamera = camera
Methods.Camera = {
	ScreenPointToRay = function() return Ray.new(v3(0, 10, 10), v3(0, 0, -1)) end,
	ViewportPointToRay = function() return Ray.new(v3(0, 10, 10), v3(0, 0, -1)) end,
	WorldToScreenPoint = function() return v3(400, 300, 10), true end,
	WorldToViewportPoint = function() return v3(400, 300, 10), true end,
}

-- ---- players and characters ------------------------------------------------------------------------------------------
local function make_character(player)
	local m = inst_new("Model", D[player].Name, false)
	local hum = inst_new("Humanoid", "Humanoid", false)
	local animator = inst_new("Animator", "Animator", false)
	set_parent(animator, hum)
	local root = inst_new("Part", "HumanoidRootPart", false)
	root.Position = v3(0, 3, 0)
	local head = inst_new("Part", "Head", false)
	head.Position = v3(0, 4.5, 0)
	local torso = inst_new("Part", "UpperTorso", false)
	torso.Position = v3(0, 3, 0)
	for _, leg in ipairs({ "LeftFoot", "RightFoot", "LeftHand", "RightHand", "LowerTorso" }) do
		local p = inst_new("Part", leg, false)
		p.Position = v3(0, 1, 0)
		set_parent(p, m)
	end
	set_parent(hum, m)
	set_parent(root, m)
	set_parent(head, m)
	set_parent(torso, m)
	D[m].props.PrimaryPart = root
	D[hum].props.RootPart = root
	return m
end

local function spawn_character(player)
	local old = D[player].props.Character
	if old then IM.Destroy(old) end
	local m = make_character(player)
	D[player].props.Character = m
	set_parent(m, workspace)
	local s = D[player].signals.CharacterAdded
	if s then SignalMethods.Fire(s, m) end
	local hum = find_child(m, "Humanoid")
	-- respawn after death (RespawnTime)
	get_signal(hum, "Died"):Connect(function()
		task.wait(D[Players].props.RespawnTime or 5)
		if D[player].Parent == Players then spawn_character(player) end
	end)
	-- tools from StarterPack go to the Backpack
	local bp = find_child(player, "Backpack")
	if bp then
		for _, t in ipairs(D[SERVICES.StarterPack].children) do set_parent(clone(t), bp) end
	end
	-- StarterCharacterScripts LocalScripts run in the character
	return m
end

Methods.Player = {
	Kick = function(self, msg)
		event("kick", { msg = tostring(msg or "") })
		task.defer(function() if D[self].Parent == Players then
			local s = D[Players].signals.PlayerRemoving
			if s then SignalMethods.Fire(s, self) end
			set_parent(self, nil)
		end end)
	end,
	LoadCharacter = function(self) spawn_character(self) end,
	GetMouse = function(self)
		local mouse = inst_new("PlayerMouse", "Mouse", false)
		D[mouse].props.Hit = cf(0, 0, -10)
		D[mouse].props.Target = baseplate
		D[mouse].props.X = 400
		D[mouse].props.Y = 300
		return mouse
	end,
	IsInGroup = function() return false end,
	GetRankInGroup = function() return 0 end,
	GetRoleInGroup = function() return "Guest" end,
	IsFriendsWith = function() return false end,
	GetFriendsOnline = function() return {} end,
	HasAppearanceLoaded = function() return true end,
	DistanceFromCharacter = function() return 5 end,
	GetJoinData = function() return {} end,
	ClearCharacterAppearance = function() end,
	Move = function() end,
	RequestStreamAroundAsync = function() end,
}
local CLIENT_START = {}   -- LocalScripts to start for each joining player

local function add_player(name, uid)
	local p = inst_new("Player", name, false)
	D[p].props.UserId = uid
	D[p].props.DisplayName = name
	D[p].props.AccountAge = 30
	D[p].props.MembershipType = Enum.MembershipType.None
	local bp = inst_new("Backpack", "Backpack", false)
	set_parent(bp, p)
	local pg = inst_new("PlayerGui", "PlayerGui", false)
	set_parent(pg, p)
	local ps = inst_new("PlayerScripts", "PlayerScripts", false)
	set_parent(ps, p)
	table.insert(PLAYERS_LIST, p)
	LOCAL_PLAYER = LOCAL_PLAYER or p
	set_parent(p, Players)
	local s = D[Players].signals.PlayerAdded
	if s then SignalMethods.Fire(s, p) end
	-- StarterGui copies into PlayerGui
	for _, g in ipairs(D[StarterGui].children) do set_parent(clone(g), pg) end
	if D[Players].props.CharacterAutoLoads ~= false then spawn_character(p) end
	return p
end

local function remove_player(p)
	local s = D[Players].signals.PlayerRemoving
	if s then SignalMethods.Fire(s, p) end
	for i, x in ipairs(PLAYERS_LIST) do if x == p then table.remove(PLAYERS_LIST, i) break end end
	local ch = D[p].props.Character
	set_parent(p, nil)
	if ch then IM.Destroy(ch) end
end

-- ---- Instance.new ----------------------------------------------------------------------------------------------------
local NOT_CREATABLE_OK = { Folder = true }
Instance.new = function(cls, parent)
	if type(cls) ~= "string" then error("invalid argument #1 to 'new' (string expected)", 2) end
	local info = class_info(cls)
	if not info then error("Unable to create an Instance of type \"" .. cls .. "\"", 2) end
	local raw = MEMBERS[cls]
	if string.find(raw, "|!", 1, true) then error("Unable to create an Instance of type \"" .. cls .. "\"", 2) end
	local inst = inst_new(cls, cls, false)
	if cls == "Humanoid" then D[inst].props.Health = 100 end
	if parent ~= nil then set_parent(inst, parent) end
	return inst
end
Instance.fromExisting = function(x) return clone(x) end

-- ---- typeof / require / globals ----------------------------------------------------------------------------------------
local real_typeof = typeof
local function mock_typeof(v)
	local t = TYPES[v]
	if t then return t end
	return real_typeof(v)
end

local MODULE_CACHE = {}
local MODULE_SRC = {}   -- ModuleScript instance -> {src, block}
local UNBOUND_MODULES = {}
local function mock_require(m)
	if type(m) == "number" then error("[mock] require by asset id", 2) end
	if not is_inst(m) then error("Attempted to call require with invalid argument(s).", 2) end
	if D[m].lazy then D[m].ClassName = "ModuleScript"; D[m].lazy = false end
	if D[m].ClassName ~= "ModuleScript" then error("Attempted to call require with invalid argument(s).", 2) end
	if MODULE_CACHE[m] ~= nil then return MODULE_CACHE[m] end
	local spec = MODULE_SRC[m]
	if not spec then
		-- bind to the module block whose label names it, else the first unbound one
		local want = string.lower(D[m].Name)
		for i, u in ipairs(UNBOUND_MODULES) do
			if string.find(string.lower(u.label or ""), want, 1, true) then spec = table.remove(UNBOUND_MODULES, i) break end
		end
		if not spec and #UNBOUND_MODULES > 0 then spec = table.remove(UNBOUND_MODULES, 1) end
		if not spec then error("[mock] module " .. D[m].Name .. " has no source in the answer", 2) end
		MODULE_SRC[m] = spec
	end
	local fn = spec.compile(m)
	local res = table.pack(pcall(fn))
	if not res[1] then error(res[2], 0) end
	if res.n < 2 or res[2] == nil then error("Module code did not return exactly one value", 2) end
	MODULE_CACHE[m] = res[2]
	return res[2]
end

local function legacy_wait(t) local d = task.wait(t); return d, NOW end
local function legacy_spawn(f) return task.defer(f) end
local function legacy_delay(t, f) return task.delay(t, f) end

local function make_env(script_inst, block)
	local env = {
		game = game, Game = game, workspace = workspace, Workspace = workspace, script = script_inst,
		Instance = Instance, Vector3 = Vector3, Vector2 = Vector2, CFrame = CFrame, Color3 = Color3, BrickColor = BrickColor,
		UDim = UDim, UDim2 = UDim2, TweenInfo = TweenInfo, Enum = Enum, Ray = Ray, RaycastParams = RaycastParams,
		OverlapParams = OverlapParams, NumberSequence = NumberSequence, NumberSequenceKeypoint = NumberSequenceKeypoint,
		ColorSequence = ColorSequence, ColorSequenceKeypoint = ColorSequenceKeypoint, NumberRange = NumberRange,
		Region3 = Region3, Rect = Rect, PhysicalProperties = PhysicalProperties, Font = Font, DateTime = DateTime,
		Random = Random, task = task, wait = legacy_wait, spawn = legacy_spawn, delay = legacy_delay,
		tick = function() return 1767225600 + NOW end, time = function() return NOW end, elapsedTime = function() return NOW end,
		typeof = mock_typeof, require = mock_require, print = function() end, warn = function() end,
		os = { time = function(t) if t then return os.time(t) end return 1767225600 + math.floor(NOW) end, clock = function() return NOW end,
			date = function(f, t) return os.date(f, t or (1767225600 + math.floor(NOW))) end, difftime = os.difftime },
		math = math, string = string, table = table, coroutine = coroutine, utf8 = utf8, bit32 = bit32, buffer = buffer,
		pairs = pairs, ipairs = ipairs, next = next, select = select, type = type, tostring = tostring, tonumber = tonumber,
		pcall = pcall, xpcall = xpcall, error = error, assert = assert, setmetatable = setmetatable,
		getmetatable = getmetatable, rawget = rawget, rawset = rawset, rawequal = rawequal, rawlen = rawlen, unpack = table.unpack,
		debug = { traceback = debug.traceback, info = debug.info, profilebegin = function() end, profileend = function() end },
		shared = {}, _G = nil, newproxy = newproxy, gcinfo = function() return 0 end, collectgarbage = function() return 0 end,
		settings = function() return Stub end, UserSettings = function() return Stub end, version = function() return "0.745" end,
		plugin = nil, Axes = { new = plain("Axes") }, Faces = { new = plain("Faces") }, SharedTable = { new = function() return {} end },
	}
	env._G = env
	setmetatable(env, { __index = function(_, k)
		FRAGMENT[block] = FRAGMENT[block] or {}
		FRAGMENT[block][k] = true
		return nil
	end })
	return env
end

-- ---- loading the answer's scripts -------------------------------------------------------------------------------------
local BLOCKS = {}       -- {index, src, kind, place, label, part}
local SCRIPT_INST = {}

local function compile(block, script_inst)
	local fn, err = loadstring(block.src, "=blk" .. block.index)
	if not fn then
		table.insert(REPORT.errors, { msg = tostring(err), phase = "compile", t = 0, block = block.index, ctx = "?" })
		return nil
	end
	setfenv(fn, make_env(script_inst, block.index))
	return fn
end

local function studio_part(name)
	local p = inst_new("Part", name or "Part", true)
	D[p].lazy = true
	D[p].lazy_classes = WORLD_LAZY
	p.Anchored = true
	p.Position = v3(10, 3, 0)
	set_parent(p, workspace)
	return p
end

local SERVER_STARTS, CLIENT_BLOCKS = {}, {}

local function place_block(b)
	local kind, place = b.kind, b.place
	if kind == "module" then
		table.insert(UNBOUND_MODULES, { label = b.label, compile = function(m) return compile(b, m) end })
		return
	end
	if kind == "local" then
		table.insert(CLIENT_BLOCKS, b)
		return
	end
	-- server Script
	local s = inst_new("Script", "Script", false)
	if place == "world" then
		set_parent(s, studio_part(b.part))
	elseif place == "tool" then
		local tool = inst_new("Tool", b.part or "Tool", true)
		set_parent(inst_new("Part", "Handle", true), tool)
		set_parent(tool, SERVICES.StarterPack)
		set_parent(s, tool)
		D[tool].script_block = b
		return
	elseif place == "storage" then
		set_parent(s, SERVICES.ServerStorage)
	else
		set_parent(s, SERVICES.ServerScriptService)
	end
	table.insert(SERVER_STARTS, { b = b, inst = s })
end

local function start_client_scripts(player)
	for _, b in ipairs(CLIENT_BLOCKS) do
		local s = inst_new("LocalScript", "LocalScript", false)
		local place = b.place
		local pg = find_child(player, "PlayerGui")
		if b.gui then
			local gui = inst_new("ScreenGui", "ScreenGui", true)
			D[gui].lazy = b.gui == "gui"
			D[gui].lazy_classes = { "ScreenGui", "Frame", "TextButton", "TextLabel", "ImageLabel", "ImageButton", "TextBox" }
			set_parent(gui, pg)
			if b.gui == "button" or b.gui == "element" then
				local btn = inst_new("TextButton", b.part or "TextButton", true)
				D[btn].lazy = b.gui == "element"
				D[btn].lazy_classes = GUI_LAZY
				set_parent(btn, gui)
				set_parent(s, btn)
			else
				set_parent(s, gui)
			end
		elseif b.where == "character" then
			set_parent(s, D[player].props.Character)
		elseif place == "tool" then
			local tool = inst_new("Tool", b.part or "Tool", true)
			set_parent(inst_new("Part", "Handle", true), tool)
			set_parent(tool, find_child(player, "Backpack"))
			set_parent(s, tool)
		else
			set_parent(s, find_child(player, "PlayerScripts"))
		end
		local fn = compile(b, s)
		if fn then spawn_fn(fn, "client", b.index) end
	end
end

-- ---- scenario driver --------------------------------------------------------------------------------------------------
local SC = {}
function SC.load(blocks)
	for _, b in ipairs(blocks) do place_block(b) end
	PHASE = "start"
	for _, st in ipairs(SERVER_STARTS) do
		local fn = compile(st.b, st.inst)
		if fn then spawn_fn(fn, "server", st.b.index) end
	end
	run_until(NOW + 0.5)
end
function SC.join(name, uid)
	PHASE = "join"
	local p = add_player(name or "Player1", uid or 1001)
	-- server scripts inside tools run when the tool is in the backpack
	for _, t in ipairs(D[find_child(p, "Backpack")].children) do
		local tb = nil
		for _, st in ipairs(D[SERVICES.StarterPack].children) do if D[st].script_block and D[st].Name == D[t].Name then tb = D[st].script_block end end
		if tb then
			local s = find_child(t, "Script")
			local fn = compile(tb, s)
			if fn then spawn_fn(fn, "server", tb.index) end
		end
	end
	start_client_scripts(p)
	run_until(NOW + 1)
	return p
end
function SC.advance(t) run_until(NOW + t) end
local function heartbeat(t)
	local t_end = NOW + t
	while NOW < t_end - 1e-9 do
		local step = 1 / 30
		local d = D[RunService]
		for _, n in ipairs({ "Stepped", "Heartbeat", "RenderStepped", "PreSimulation", "PostSimulation", "PreRender" }) do
			if d.signals[n] then
				if n == "Stepped" then SignalMethods.Fire(d.signals[n], NOW, step) else SignalMethods.Fire(d.signals[n], step) end
			end
		end
		run_until(NOW + step)
	end
end
SC.heartbeat = heartbeat
local function conns_of(inst, sig)
	local d = D[inst]
	local s = d and d.signals[sig]
	return s and #s._conns or 0
end
local function all_instances()
	local out = {}
	local function walk(x) for _, c in ipairs(D[x].children) do table.insert(out, c); walk(c) end end
	walk(game)
	return out
end
function SC.touch_all(player, times, gap)
	PHASE = "touch"
	local char = D[player].props.Character
	if not char then return 0 end
	local root = find_child(char, "HumanoidRootPart")
	local n = 0
	for _, inst in ipairs(all_instances()) do
		if is_a(D[inst].ClassName, "BasePart") and conns_of(inst, "Touched") > 0 and not is_descendant(inst, char) then
			n += 1
			for _ = 1, times or 1 do
				local c2 = D[player].props.Character
				if not c2 then break end
				local hit = find_child(c2, "HumanoidRootPart") or root
				SignalMethods.Fire(D[inst].signals.Touched, hit)
				run_until(NOW + (gap or 0.05))
			end
		end
	end
	return n
end
function SC.trigger_prompts(player)
	PHASE = "prompt"
	local n = 0
	for _, inst in ipairs(all_instances()) do
		local cls = D[inst].ClassName
		if cls == "ProximityPrompt" and (conns_of(inst, "Triggered") > 0 or conns_of(ProximityPromptService, "PromptTriggered") > 0) then
			n += 1
			if D[inst].signals.PromptButtonHoldBegan then SignalMethods.Fire(D[inst].signals.PromptButtonHoldBegan, player) end
			if D[inst].signals.Triggered then SignalMethods.Fire(D[inst].signals.Triggered, player) end
			if D[ProximityPromptService].signals.PromptTriggered then SignalMethods.Fire(D[ProximityPromptService].signals.PromptTriggered, inst, player) end
			if D[inst].signals.TriggerEnded then SignalMethods.Fire(D[inst].signals.TriggerEnded, player) end
		elseif cls == "ClickDetector" and conns_of(inst, "MouseClick") > 0 then
			n += 1
			SignalMethods.Fire(D[inst].signals.MouseClick, player)
		end
	end
	run_until(NOW + 0.2)
	return n
end
function SC.click_gui(player)
	PHASE = "gui"
	local n = 0
	local pg = find_child(player, "PlayerGui")
	if not pg then return 0 end
	for _, inst in ipairs(IM.GetDescendants(pg)) do
		for _, sig in ipairs({ "Activated", "MouseButton1Click", "MouseButton1Down", "FocusLost" }) do
			if conns_of(inst, sig) > 0 then
				n += 1
				if sig == "Activated" then SignalMethods.Fire(D[inst].signals[sig], nil, 1)
				elseif sig == "FocusLost" then inst.Text = "10"; SignalMethods.Fire(D[inst].signals[sig], true)
				else SignalMethods.Fire(D[inst].signals[sig]) end
				run_until(NOW + 0.3)
			end
		end
	end
	return n
end
function SC.keys(keys)
	PHASE = "input"
	local n = 0
	for _, k in ipairs(keys) do
		local io = setmetatable({ KeyCode = Enum.KeyCode[k], UserInputType = Enum.UserInputType.Keyboard,
			UserInputState = Enum.UserInputState.Begin, Position = v3(400, 300, 0), Delta = v3(0, 0, 0) }, { __index = function() return Stub end })
		TYPES[io] = "Instance"
		if D[UIS].signals.InputBegan then n += 1; SignalMethods.Fire(D[UIS].signals.InputBegan, io, false) end
		for name, a in pairs(CAS_ACTIONS) do
			n += 1
			local co = coroutine.create(a.fn)
			CTX[co] = a.ctx
			BLOCK_OF[co] = a.block
			resume(co, name, Enum.UserInputState.Begin, io)
		end
		run_until(NOW + 0.2)
		if D[UIS].signals.InputEnded then SignalMethods.Fire(D[UIS].signals.InputEnded, io, false) end
		run_until(NOW + 0.1)
	end
	return n
end
function SC.tools(player)
	PHASE = "tool"
	local n = 0
	local char = D[player].props.Character
	local bp = find_child(player, "Backpack")
	if not char or not bp then return 0 end
	for _, t in ipairs(table.clone(D[bp].children)) do
		if D[t].ClassName == "Tool" then
			set_parent(t, char)
			if D[t].signals.Equipped then SignalMethods.Fire(D[t].signals.Equipped, Methods.Player.GetMouse(player)) end
			run_until(NOW + 0.2)
			if D[t].signals.Activated then n += 1; SignalMethods.Fire(D[t].signals.Activated) end
			run_until(NOW + 0.5)
		end
	end
	return n
end
-- a cheating client fires every server remote with a huge amount
function SC.evil_remotes(player)
	PHASE = "evil"
	local n = 0
	for _, inst in ipairs(all_instances()) do
		if D[inst].ClassName == "RemoteEvent" and conns_of(inst, "OnServerEvent") > 0 then
			n += 1
			for _, args in ipairs({ { 1e9 }, { -1e9 }, { "Sword", 1e9 }, { player, 1e9 } }) do
				SignalMethods.Fire(D[inst].signals.OnServerEvent, player, table.unpack(args))
				run_until(NOW + 0.1)
			end
		end
	end
	return n
end
function SC.leave(player)
	PHASE = "leave"
	remove_player(player)
	run_until(NOW + 1)
end
function SC.close()
	PHASE = "close"
	for _, c in ipairs(CLOSE_FNS) do
		local co = coroutine.create(c.fn)
		CTX[co] = c.ctx
		BLOCK_OF[co] = c.block
		resume(co)
	end
	run_until(NOW + 3)
end
function SC.set_ds_fail(v) DS_FAIL = v end

-- probes read the world
local PR = {}
function PR.stats(player)
	local ls = player and find_child(player, "leaderstats")
	if not ls then return nil end
	local out = {}
	for _, c in ipairs(D[ls].children) do
		if is_a(D[c].ClassName, "ValueBase") then out[D[c].Name] = D[c].props.Value or prop_default(c, "Value") end
	end
	return out
end
function PR.total_stats(player)
	local s = PR.stats(player)
	if not s then return nil end
	local t = 0
	for _, v in pairs(s) do if type(v) == "number" then t += v end end
	return t
end
function PR.health(player)
	local ch = D[player].props.Character
	local h = ch and find_child(ch, "Humanoid")
	return h and (D[h].props.Health or 100)
end
function PR.died() for _, e in ipairs(REPORT.events) do if e.kind == "died" then return true end end return false end
function PR.snapshot_parts()
	-- studio parts the answer's scripts may change (door, platform ...)
	local snap = {}
	for _, inst in ipairs(all_instances()) do
		local d = D[inst]
		if d.studio and is_a(d.ClassName, "BasePart") and d.Name ~= "Baseplate" then
			snap[inst] = { CanCollide = inst.CanCollide, Transparency = inst.Transparency, Pos = inst.Position, CF = inst.CFrame,
				Parent = d.Parent }
		end
	end
	return snap
end
function PR.changed_parts(before)
	local n = 0
	for inst, s in pairs(before) do
		local d = D[inst]
		if d.Parent ~= s.Parent or inst.CanCollide ~= s.CanCollide or inst.Transparency ~= s.Transparency or
			(inst.Position - s.Pos).Magnitude > 0.05 or not (inst.CFrame == s.CF) then
			n += 1
		end
	end
	return n
end
function PR.writes() return WRITES end
function PR.probe(name, ok, msg, extra)
	table.insert(REPORT.probes, { name = name, ok = ok, msg = msg, extra = extra })
end

-- ---- JSON out --------------------------------------------------------------------------------------------------------
local function jstr(s)
	s = tostring(s)
	s = string.gsub(s, '[%c"\\]', function(c)
		if c == "\n" then return "\\n" elseif c == "\t" then return "\\t" elseif c == '"' then return '\\"' elseif c == "\\" then return "\\\\" end
		return string.format("\\u%04x", string.byte(c))
	end)
	return '"' .. s .. '"'
end
local function jenc(v, depth)
	depth = depth or 0
	local t = type(v)
	if t == "nil" then return "null" end
	if t == "boolean" then return tostring(v) end
	if t == "number" then
		if v ~= v or v == math.huge or v == -math.huge then return "null" end
		return tostring(v)
	end
	if t == "string" then return jstr(v) end
	if t == "table" and depth < 8 then
		if TYPES[v] then return jstr(tostring(v)) end
		if #v > 0 or next(v) == nil then
			local parts = {}
			for _, x in ipairs(v) do table.insert(parts, jenc(x, depth + 1)) end
			return "[" .. table.concat(parts, ",") .. "]"
		end
		local parts = {}
		for k, x in pairs(v) do table.insert(parts, jstr(k) .. ":" .. jenc(x, depth + 1)) end
		return "{" .. table.concat(parts, ",") .. "}"
	end
	return jstr(tostring(v))
end
local function finish()
	local frag = {}
	for b, names in pairs(FRAGMENT) do
		local l = {}
		for n in pairs(names) do table.insert(l, n) end
		frag[tostring(b)] = l
	end
	REPORT.fragment = frag
	REPORT.now = NOW
	REPORT.writes = WRITES
	print("@@SANDBOX@@" .. jenc(REPORT))
end

return { SC = SC, PR = PR, finish = finish, D = D, set_blocks = function(b) BLOCKS = b end, Players = Players,
	NOW = function() return NOW end, event = event }
