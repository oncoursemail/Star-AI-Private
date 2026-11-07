-- Roblox engine stubs for the gold bank's runtime tests (standalone Luau VM; no Roblox, no files, no network).
-- Not the engine: a small, deterministic imitation of the parts the bank's examples use, so pure logic and simple
-- engine wiring can be run. Time is virtual: task.wait/task.delay/os.clock follow __now, moved by __advance(dt).
--
-- Test helpers (globals): check(name, cond), __advance(seconds), __frames(n, dt), __makePlayer(userId, name),
-- __removePlayer(player), __makeCharacter(player, position?), __close() (runs BindToClose handlers),
-- __setClient(bool), DataStoreService.__failNext = n (next n data store calls error), __raycastHits (list, optional),
-- MarketplaceService.__owned[userId][passId] = true, PathfindingService.__status = Enum.PathStatus.NoPath.
-- Remote calls are recorded: remote.__sent = { {player, ...}, ... } for FireClient/FireAllClients/FireServer.

local __realTypeof = typeof
if warn == nil then
	-- the standalone VM has no warn(); Roblox prints it as a warning line
	warn = function(...)
		print("WARN", ...)
	end
end
local __realOs = os
local __passes, __fails = 0, 0

function check(name, cond)
	if cond then
		__passes += 1
		print("@@T\tpass\t" .. tostring(name))
	else
		__fails += 1
		print("@@T\tfail\t" .. tostring(name))
	end
end

function __done()
	print(string.format("@@SUMMARY\t%d\t%d", __passes, __fails))
end

local function stubType(v)
	local mt = getmetatable(v)
	if type(mt) == "table" and rawget(mt, "__type") then
		return rawget(mt, "__type")
	end
	return nil
end

function typeof(v)
	return stubType(v) or __realTypeof(v)
end

------------------------------------------------------------------------------------------------ clock and task
__now = 0
local __queue = {} -- { at, seq, fn, args, thread, cancelled }
local __seq = 0

local function schedule(at, thread, fn, args)
	__seq += 1
	local entry = { at = at, seq = __seq, thread = thread, fn = fn, args = args }
	table.insert(__queue, entry)
	return entry
end

local function resume(thread, ...)
	local ok, err = coroutine.resume(thread, ...)
	if not ok then
		error(err, 0)
	end
end

local function runEntry(e)
	if e.cancelled then
		return
	end
	if e.thread then
		if coroutine.status(e.thread) == "suspended" then
			resume(e.thread, table.unpack(e.args or {}))
		end
	else
		local co = coroutine.create(e.fn)
		resume(co, table.unpack(e.args or {}))
	end
end

function __advance(dt)
	local target = __now + (dt or 0)
	while true do
		local best, bestIndex = nil, nil
		for i, e in __queue do
			if e.at <= target and (best == nil or e.at < best.at or (e.at == best.at and e.seq < best.seq)) then
				best, bestIndex = e, i
			end
		end
		if not best then
			break
		end
		table.remove(__queue, bestIndex)
		if best.at > __now then
			__now = best.at
		end
		runEntry(best)
	end
	__now = target
end

task = {}
function task.spawn(fnOrThread, ...)
	if type(fnOrThread) == "thread" then
		resume(fnOrThread, ...)
		return fnOrThread
	end
	local co = coroutine.create(fnOrThread)
	resume(co, ...)
	return co
end
function task.defer(fn, ...)
	local co = type(fn) == "thread" and fn or coroutine.create(fn)
	schedule(__now, co, nil, { ... })
	return co
end
function task.delay(t, fn, ...)
	local co = type(fn) == "thread" and fn or coroutine.create(fn)
	local entry = schedule(__now + (t or 0), co, nil, { ... })
	return co, entry
end
function task.wait(t)
	t = t or 0
	local start = __now
	if coroutine.isyieldable() then
		schedule(__now + t, coroutine.running(), nil, {})
		coroutine.yield()
	else
		__advance(t)
	end
	return __now - start
end
function task.cancel(thread)
	for _, e in __queue do
		if e.thread == thread then
			e.cancelled = true
		end
	end
	if coroutine.status(thread) == "suspended" then
		coroutine.close(thread)
	end
end
function task.synchronize() end
function task.desynchronize() end

os = {
	clock = function()
		return __now
	end,
	time = function(t)
		if t then
			return __realOs.time(t)
		end
		return 1700000000 + math.floor(__now)
	end,
	date = __realOs.date,
	difftime = __realOs.difftime,
}
local __realDebug = debug
debug = setmetatable({ profilebegin = function(_label) end, profileend = function() end }, { __index = __realDebug })
function tick()
	return 1700000000 + __now
end
function time()
	return __now
end

------------------------------------------------------------------------------------------------ Signal
local Connection = {}
Connection.__index = Connection
Connection.__type = "RBXScriptConnection"
function Connection:Disconnect()
	self.Connected = false
	local list = self._signal._list
	for i, c in list do
		if c == self then
			table.remove(list, i)
			break
		end
	end
end

local Signal = {}
Signal.__index = Signal
Signal.__type = "RBXScriptSignal"
local function newSignal()
	return setmetatable({ _list = {} }, Signal)
end
function Signal:Connect(fn)
	local c = setmetatable({ Connected = true, _fn = fn, _signal = self }, Connection)
	table.insert(self._list, c)
	return c
end
function Signal:Once(fn)
	local c
	c = self:Connect(function(...)
		c:Disconnect()
		fn(...)
	end)
	return c
end
function Signal:Wait()
	local thread = coroutine.running()
	if not coroutine.isyieldable() then
		error("Signal:Wait() outside a coroutine in the stubs")
	end
	self:Once(function(...)
		resume(thread, ...)
	end)
	return coroutine.yield()
end
function Signal:ConnectParallel(fn)
	return self:Connect(fn)
end
function Signal:Fire(...)
	local snapshot = table.clone(self._list)
	for _, c in snapshot do
		if c.Connected then
			task.spawn(c._fn, ...)
		end
	end
end
__newSignal = newSignal

------------------------------------------------------------------------------------------------ data types
local function makeType(name)
	local t = {}
	t.__index = t
	t.__type = name
	return t
end

-- Vector3
local V3 = makeType("Vector3")
Vector3 = {}
local function v3(x, y, z)
	return setmetatable({ X = x or 0, Y = y or 0, Z = z or 0 }, V3)
end
Vector3.new = v3
Vector3.zero = v3(0, 0, 0)
Vector3.one = v3(1, 1, 1)
Vector3.xAxis = v3(1, 0, 0)
Vector3.yAxis = v3(0, 1, 0)
Vector3.zAxis = v3(0, 0, 1)
V3.__add = function(a, b)
	return v3(a.X + b.X, a.Y + b.Y, a.Z + b.Z)
end
V3.__sub = function(a, b)
	return v3(a.X - b.X, a.Y - b.Y, a.Z - b.Z)
end
V3.__mul = function(a, b)
	if type(a) == "number" then
		return v3(b.X * a, b.Y * a, b.Z * a)
	elseif type(b) == "number" then
		return v3(a.X * b, a.Y * b, a.Z * b)
	end
	return v3(a.X * b.X, a.Y * b.Y, a.Z * b.Z)
end
V3.__div = function(a, b)
	if type(b) == "number" then
		return v3(a.X / b, a.Y / b, a.Z / b)
	end
	return v3(a.X / b.X, a.Y / b.Y, a.Z / b.Z)
end
V3.__unm = function(a)
	return v3(-a.X, -a.Y, -a.Z)
end
V3.__eq = function(a, b)
	return a.X == b.X and a.Y == b.Y and a.Z == b.Z
end
V3.__tostring = function(a)
	return string.format("%g, %g, %g", a.X, a.Y, a.Z)
end
V3.__index = function(self, k)
	if k == "Magnitude" then
		return math.sqrt(self.X * self.X + self.Y * self.Y + self.Z * self.Z)
	elseif k == "Unit" then
		local m = math.sqrt(self.X * self.X + self.Y * self.Y + self.Z * self.Z)
		if m == 0 then
			return v3(0 / 0, 0 / 0, 0 / 0)
		end
		return v3(self.X / m, self.Y / m, self.Z / m)
	end
	return rawget(V3, k)
end
function V3.Dot(a, b)
	return a.X * b.X + a.Y * b.Y + a.Z * b.Z
end
function V3.Cross(a, b)
	return v3(a.Y * b.Z - a.Z * b.Y, a.Z * b.X - a.X * b.Z, a.X * b.Y - a.Y * b.X)
end
function V3.Lerp(a, b, t)
	return a + (b - a) * t
end
function V3.Min(a, b)
	return v3(math.min(a.X, b.X), math.min(a.Y, b.Y), math.min(a.Z, b.Z))
end
function V3.Max(a, b)
	return v3(math.max(a.X, b.X), math.max(a.Y, b.Y), math.max(a.Z, b.Z))
end
function V3.Abs(a)
	return v3(math.abs(a.X), math.abs(a.Y), math.abs(a.Z))
end
function V3.Floor(a)
	return v3(math.floor(a.X), math.floor(a.Y), math.floor(a.Z))
end
function V3.FuzzyEq(a, b, eps)
	eps = eps or 1e-5
	return math.abs(a.X - b.X) <= eps and math.abs(a.Y - b.Y) <= eps and math.abs(a.Z - b.Z) <= eps
end

-- Vector2
local V2 = makeType("Vector2")
Vector2 = {}
local function v2(x, y)
	return setmetatable({ X = x or 0, Y = y or 0 }, V2)
end
Vector2.new = v2
Vector2.zero = v2(0, 0)
Vector2.one = v2(1, 1)
V2.__add = function(a, b)
	return v2(a.X + b.X, a.Y + b.Y)
end
V2.__sub = function(a, b)
	return v2(a.X - b.X, a.Y - b.Y)
end
V2.__mul = function(a, b)
	if type(a) == "number" then
		return v2(b.X * a, b.Y * a)
	elseif type(b) == "number" then
		return v2(a.X * b, a.Y * b)
	end
	return v2(a.X * b.X, a.Y * b.Y)
end
V2.__div = function(a, b)
	if type(b) == "number" then
		return v2(a.X / b, a.Y / b)
	end
	return v2(a.X / b.X, a.Y / b.Y)
end
V2.__unm = function(a)
	return v2(-a.X, -a.Y)
end
V2.__eq = function(a, b)
	return a.X == b.X and a.Y == b.Y
end
V2.__index = function(self, k)
	if k == "Magnitude" then
		return math.sqrt(self.X * self.X + self.Y * self.Y)
	elseif k == "Unit" then
		local m = math.sqrt(self.X * self.X + self.Y * self.Y)
		return v2(self.X / m, self.Y / m)
	end
	return rawget(V2, k)
end
function V2.Dot(a, b)
	return a.X * b.X + a.Y * b.Y
end
function V2.Lerp(a, b, t)
	return a + (b - a) * t
end

-- CFrame (rotation matrix rows r00..r22, position x y z)
local CF = makeType("CFrame")
CFrame = {}
local function cf(x, y, z, r00, r01, r02, r10, r11, r12, r20, r21, r22)
	return setmetatable({
		x = x, y = y, z = z,
		r00 = r00 or 1, r01 = r01 or 0, r02 = r02 or 0,
		r10 = r10 or 0, r11 = r11 or 1, r12 = r12 or 0,
		r20 = r20 or 0, r21 = r21 or 0, r22 = r22 or 1,
	}, CF)
end
local function lookAtCF(eye, target, up)
	up = up or Vector3.yAxis
	local look = (target - eye).Unit
	local right = look:Cross(up)
	if right.Magnitude < 1e-6 then
		right = look:Cross(Vector3.zAxis)
	end
	right = right.Unit
	local upv = right:Cross(look).Unit
	-- columns: right, up, back (-look)
	return cf(eye.X, eye.Y, eye.Z, right.X, upv.X, -look.X, right.Y, upv.Y, -look.Y, right.Z, upv.Z, -look.Z)
end
function CFrame.new(a, b, c, ...)
	if a == nil then
		return cf(0, 0, 0)
	end
	if typeof(a) == "Vector3" then
		if b ~= nil and typeof(b) == "Vector3" then
			return lookAtCF(a, b)
		end
		return cf(a.X, a.Y, a.Z)
	end
	if select("#", ...) == 9 then
		return cf(a, b, c, ...)
	end
	return cf(a, b, c)
end
CFrame.identity = cf(0, 0, 0)
function CFrame.lookAt(eye, target, up)
	return lookAtCF(eye, target, up)
end
local function rotX(a)
	local c, s = math.cos(a), math.sin(a)
	return cf(0, 0, 0, 1, 0, 0, 0, c, -s, 0, s, c)
end
local function rotY(a)
	local c, s = math.cos(a), math.sin(a)
	return cf(0, 0, 0, c, 0, s, 0, 1, 0, -s, 0, c)
end
local function rotZ(a)
	local c, s = math.cos(a), math.sin(a)
	return cf(0, 0, 0, c, -s, 0, s, c, 0, 0, 0, 1)
end
function CFrame.Angles(rx, ry, rz)
	return rotX(rx) * rotY(ry) * rotZ(rz)
end
CFrame.fromEulerAnglesXYZ = CFrame.Angles
function CFrame.fromOrientation(rx, ry, rz)
	return rotY(ry) * rotX(rx) * rotZ(rz)
end
CFrame.fromEulerAnglesYXZ = CFrame.fromOrientation
function CFrame.fromAxisAngle(axis, angle)
	local u = axis.Unit
	local c, s, t = math.cos(angle), math.sin(angle), 1 - math.cos(angle)
	local x, y, z = u.X, u.Y, u.Z
	return cf(0, 0, 0,
		t * x * x + c, t * x * y - s * z, t * x * z + s * y,
		t * x * y + s * z, t * y * y + c, t * y * z - s * x,
		t * x * z - s * y, t * y * z + s * x, t * z * z + c)
end
function CFrame.fromMatrix(pos, vx, vy, vz)
	vz = vz or vx:Cross(vy).Unit
	return cf(pos.X, pos.Y, pos.Z, vx.X, vy.X, vz.X, vx.Y, vy.Y, vz.Y, vx.Z, vy.Z, vz.Z)
end
local function rotate(m, v)
	return v3(m.r00 * v.X + m.r01 * v.Y + m.r02 * v.Z,
		m.r10 * v.X + m.r11 * v.Y + m.r12 * v.Z,
		m.r20 * v.X + m.r21 * v.Y + m.r22 * v.Z)
end
CF.__mul = function(a, b)
	if typeof(b) == "Vector3" then
		local r = rotate(a, b)
		return v3(r.X + a.x, r.Y + a.y, r.Z + a.z)
	end
	local p = rotate(a, v3(b.x, b.y, b.z))
	return cf(p.X + a.x, p.Y + a.y, p.Z + a.z,
		a.r00 * b.r00 + a.r01 * b.r10 + a.r02 * b.r20, a.r00 * b.r01 + a.r01 * b.r11 + a.r02 * b.r21, a.r00 * b.r02 + a.r01 * b.r12 + a.r02 * b.r22,
		a.r10 * b.r00 + a.r11 * b.r10 + a.r12 * b.r20, a.r10 * b.r01 + a.r11 * b.r11 + a.r12 * b.r21, a.r10 * b.r02 + a.r11 * b.r12 + a.r12 * b.r22,
		a.r20 * b.r00 + a.r21 * b.r10 + a.r22 * b.r20, a.r20 * b.r01 + a.r21 * b.r11 + a.r22 * b.r21, a.r20 * b.r02 + a.r21 * b.r12 + a.r22 * b.r22)
end
CF.__add = function(a, b)
	return cf(a.x + b.X, a.y + b.Y, a.z + b.Z, a.r00, a.r01, a.r02, a.r10, a.r11, a.r12, a.r20, a.r21, a.r22)
end
CF.__sub = function(a, b)
	return cf(a.x - b.X, a.y - b.Y, a.z - b.Z, a.r00, a.r01, a.r02, a.r10, a.r11, a.r12, a.r20, a.r21, a.r22)
end
CF.__eq = function(a, b)
	for _, k in { "x", "y", "z", "r00", "r01", "r02", "r10", "r11", "r12", "r20", "r21", "r22" } do
		if a[k] ~= b[k] then
			return false
		end
	end
	return true
end
CF.__index = function(self, k)
	if k == "Position" or k == "p" then
		return v3(self.x, self.y, self.z)
	elseif k == "X" then
		return self.x
	elseif k == "Y" then
		return self.y
	elseif k == "Z" then
		return self.z
	elseif k == "LookVector" then
		return v3(-self.r02, -self.r12, -self.r22)
	elseif k == "RightVector" then
		return v3(self.r00, self.r10, self.r20)
	elseif k == "UpVector" then
		return v3(self.r01, self.r11, self.r21)
	elseif k == "Rotation" then
		return cf(0, 0, 0, self.r00, self.r01, self.r02, self.r10, self.r11, self.r12, self.r20, self.r21, self.r22)
	end
	return rawget(CF, k)
end
function CF.Inverse(m)
	-- transpose rotation, rotate negated position
	local r = cf(0, 0, 0, m.r00, m.r10, m.r20, m.r01, m.r11, m.r21, m.r02, m.r12, m.r22)
	local p = rotate(r, v3(-m.x, -m.y, -m.z))
	return cf(p.X, p.Y, p.Z, r.r00, r.r01, r.r02, r.r10, r.r11, r.r12, r.r20, r.r21, r.r22)
end
function CF.ToWorldSpace(a, b)
	return a * b
end
function CF.ToObjectSpace(a, b)
	return a:Inverse() * b
end
function CF.PointToWorldSpace(a, v)
	return a * v
end
function CF.PointToObjectSpace(a, v)
	return a:Inverse() * v
end
function CF.VectorToWorldSpace(a, v)
	return rotate(a, v)
end
function CF.VectorToObjectSpace(a, v)
	return rotate(a:Inverse(), v)
end
function CF.Lerp(a, b, t)
	-- position lerp; rotation snaps at t >= 0.5 (enough for tests that read positions)
	local p = a.Position:Lerp(b.Position, t)
	local r = t < 0.5 and a or b
	return cf(p.X, p.Y, p.Z, r.r00, r.r01, r.r02, r.r10, r.r11, r.r12, r.r20, r.r21, r.r22)
end
function CF.GetComponents(m)
	return m.x, m.y, m.z, m.r00, m.r01, m.r02, m.r10, m.r11, m.r12, m.r20, m.r21, m.r22
end
CF.components = CF.GetComponents
function CF.ToEulerAnglesXYZ(m)
	local ry = math.asin(math.clamp(m.r02, -1, 1))
	local rx = math.atan2(-m.r12, m.r22)
	local rz = math.atan2(-m.r01, m.r00)
	return rx, ry, rz
end
function CF.ToOrientation(m)
	local rx = math.asin(math.clamp(-m.r12, -1, 1))
	local ry = math.atan2(m.r02, m.r22)
	local rz = math.atan2(m.r10, m.r11)
	return rx, ry, rz
end

-- Color3
local C3 = makeType("Color3")
Color3 = {}
local function c3(r, g, b)
	return setmetatable({ R = r or 0, G = g or 0, B = b or 0 }, C3)
end
Color3.new = c3
function Color3.fromRGB(r, g, b)
	return c3((r or 0) / 255, (g or 0) / 255, (b or 0) / 255)
end
function Color3.fromHSV(h, s, v)
	local i = math.floor(h * 6)
	local f = h * 6 - i
	local p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
	i = i % 6
	if i == 0 then return c3(v, t, p) elseif i == 1 then return c3(q, v, p) elseif i == 2 then return c3(p, v, t)
	elseif i == 3 then return c3(p, q, v) elseif i == 4 then return c3(t, p, v) end
	return c3(v, p, q)
end
function Color3.fromHex(hex)
	hex = hex:gsub("#", "")
	return Color3.fromRGB(tonumber(hex:sub(1, 2), 16), tonumber(hex:sub(3, 4), 16), tonumber(hex:sub(5, 6), 16))
end
C3.__eq = function(a, b)
	return a.R == b.R and a.G == b.G and a.B == b.B
end
function C3.Lerp(a, b, t)
	return c3(a.R + (b.R - a.R) * t, a.G + (b.G - a.G) * t, a.B + (b.B - a.B) * t)
end
function C3.ToHSV(c)
	local mx, mn = math.max(c.R, c.G, c.B), math.min(c.R, c.G, c.B)
	local d = mx - mn
	local h = 0
	if d > 0 then
		if mx == c.R then h = ((c.G - c.B) / d) % 6 elseif mx == c.G then h = (c.B - c.R) / d + 2 else h = (c.R - c.G) / d + 4 end
		h /= 6
	end
	return h, mx == 0 and 0 or d / mx, mx
end
function C3.ToHex(c)
	return string.format("%02X%02X%02X", math.round(c.R * 255), math.round(c.G * 255), math.round(c.B * 255))
end

-- UDim / UDim2
local UD = makeType("UDim")
UDim = {}
function UDim.new(s, o)
	return setmetatable({ Scale = s or 0, Offset = o or 0 }, UD)
end
UD.__add = function(a, b)
	return UDim.new(a.Scale + b.Scale, a.Offset + b.Offset)
end
UD.__eq = function(a, b)
	return a.Scale == b.Scale and a.Offset == b.Offset
end
local UD2 = makeType("UDim2")
UDim2 = {}
function UDim2.new(xs, xo, ys, yo)
	if typeof(xs) == "UDim" then
		return setmetatable({ X = xs, Y = xo, Width = xs, Height = xo }, UD2)
	end
	local x, y = UDim.new(xs, xo), UDim.new(ys, yo)
	return setmetatable({ X = x, Y = y, Width = x, Height = y }, UD2)
end
function UDim2.fromScale(x, y)
	return UDim2.new(x, 0, y, 0)
end
function UDim2.fromOffset(x, y)
	return UDim2.new(0, x, 0, y)
end
UD2.__add = function(a, b)
	return UDim2.new(a.X + b.X, a.Y + b.Y)
end
UD2.__eq = function(a, b)
	return a.X == b.X and a.Y == b.Y
end
function UD2.Lerp(a, b, t)
	return UDim2.new(a.X.Scale + (b.X.Scale - a.X.Scale) * t, a.X.Offset + (b.X.Offset - a.X.Offset) * t,
		a.Y.Scale + (b.Y.Scale - a.Y.Scale) * t, a.Y.Offset + (b.Y.Offset - a.Y.Offset) * t)
end

-- Simple value types
local function record(name, fields)
	local t = makeType(name)
	return function(...)
		local args = { ... }
		local obj = {}
		for i, f in fields do
			obj[f] = args[i]
		end
		return setmetatable(obj, t)
	end
end
TweenInfo = { new = function(time, style, dir, repeatCount, reverses, delay)
	return setmetatable({ Time = time or 1, EasingStyle = style, EasingDirection = dir, RepeatCount = repeatCount or 0,
		Reverses = reverses or false, DelayTime = delay or 0 }, makeType("TweenInfo"))
end }
NumberRange = { new = function(a, b)
	return setmetatable({ Min = a, Max = b or a }, makeType("NumberRange"))
end }
local function sequence(typeName, kpType)
	local kp = makeType(kpType)
	local seqT = makeType(typeName)
	local keypoint = function(t, v, e)
		return setmetatable({ Time = t, Value = v, Envelope = e or 0 }, kp)
	end
	local new = function(a, b)
		if type(a) == "table" and getmetatable(a) == nil then
			return setmetatable({ Keypoints = a }, seqT)
		end
		return setmetatable({ Keypoints = { keypoint(0, a), keypoint(1, b == nil and a or b) } }, seqT)
	end
	return { new = new }, { new = keypoint }
end
NumberSequence, NumberSequenceKeypoint = sequence("NumberSequence", "NumberSequenceKeypoint")
ColorSequence, ColorSequenceKeypoint = sequence("ColorSequence", "ColorSequenceKeypoint")
Rect = { new = record("Rect", { "MinX", "MinY", "MaxX", "MaxY" }) }
PhysicalProperties = { new = record("PhysicalProperties", { "Density", "Friction", "Elasticity", "FrictionWeight", "ElasticityWeight" }) }
PathWaypoint = { new = function(pos, action, label)
	return setmetatable({ Position = pos, Action = action, Label = label or "" }, makeType("PathWaypoint"))
end }
BrickColor = { new = function(name)
	return setmetatable({ Name = tostring(name), Color = c3(0.5, 0.5, 0.5) }, makeType("BrickColor"))
end }
Font = { new = function(family, weight, style)
	return setmetatable({ Family = family, Weight = weight, Style = style }, makeType("Font"))
end, fromEnum = function(e)
	return setmetatable({ Family = tostring(e) }, makeType("Font"))
end, fromName = function(n)
	return setmetatable({ Family = n }, makeType("Font"))
end }
RaycastParams = { new = function()
	return setmetatable({ FilterDescendantsInstances = {}, FilterType = nil, IgnoreWater = false,
		CollisionGroup = "Default", RespectCanCollide = false }, makeType("RaycastParams"))
end }
OverlapParams = { new = function()
	return setmetatable({ FilterDescendantsInstances = {}, FilterType = nil, MaxParts = 0,
		CollisionGroup = "Default", RespectCanCollide = false }, makeType("OverlapParams"))
end }
DateTime = {
	now = function()
		local ms = (1700000000 + __now) * 1000
		return setmetatable({ UnixTimestamp = math.floor(ms / 1000), UnixTimestampMillis = math.floor(ms) },
			makeType("DateTime"))
	end,
	fromUnixTimestamp = function(s)
		return setmetatable({ UnixTimestamp = s, UnixTimestampMillis = s * 1000 }, makeType("DateTime"))
	end,
}

-- Random (deterministic LCG; same API shape)
local RandomT = makeType("Random")
Random = {}
function Random.new(seed)
	return setmetatable({ _s = math.floor(seed or 1) % 2147483647 + 1 }, RandomT)
end
local function nextRaw(r)
	r._s = (r._s * 48271) % 2147483647
	return r._s / 2147483647
end
function RandomT.NextNumber(r, a, b)
	local x = nextRaw(r)
	if a == nil then
		return x
	end
	return a + (b - a) * x
end
function RandomT.NextInteger(r, a, b)
	return a + math.floor(nextRaw(r) * (b - a + 1))
end
function RandomT.Shuffle(r, t)
	for i = #t, 2, -1 do
		local j = RandomT.NextInteger(r, 1, i)
		t[i], t[j] = t[j], t[i]
	end
end
function RandomT.NextUnitVector(r)
	return v3(nextRaw(r) - 0.5, nextRaw(r) - 0.5, nextRaw(r) - 0.5).Unit
end

-- Enum: Enum.Material.Plastic etc. are created on first use and compared by identity.
local EnumItemT = makeType("EnumItem")
EnumItemT.__tostring = function(e)
	return "Enum." .. e.EnumType .. "." .. e.Name
end
local EnumT = makeType("Enum")
local enumCache = {}
local enumCounters = {}
local function enumOf(typeName)
	local found = enumCache[typeName]
	if found then
		return found
	end
	local items = {}
	local enum = setmetatable({}, {
		__type = "Enum",
		__index = function(_, name)
			if name == "GetEnumItems" then
				return function()
					local out = {}
					for _, item in items do
						table.insert(out, item)
					end
					table.sort(out, function(a, b)
						return a.Value < b.Value
					end)
					return out
				end
			elseif name == "FromName" then
				return function(_, n)
					return items[n]
				end
			end
			local item = items[name]
			if not item then
				enumCounters[typeName] = (enumCounters[typeName] or -1) + 1
				item = setmetatable({ Name = name, EnumType = typeName, Value = enumCounters[typeName] }, EnumItemT)
				items[name] = item
			end
			return item
		end,
		__tostring = function()
			return typeName
		end,
	})
	enumCache[typeName] = enum
	return enum
end
Enum = setmetatable({}, { __index = function(_, k)
	return enumOf(k)
end })
local _ = EnumT

------------------------------------------------------------------------------------------------ Instances
local CLASS_PARENT = {
	Part = "BasePart", MeshPart = "BasePart", WedgePart = "BasePart", TrussPart = "BasePart", CornerWedgePart = "BasePart",
	SpawnLocation = "Part", Seat = "Part", VehicleSeat = "BasePart", UnionOperation = "BasePart", Terrain = "BasePart",
	BasePart = "PVInstance", Model = "PVInstance", Workspace = "Model", PVInstance = "Instance",
	Frame = "GuiObject", TextLabel = "GuiObject", TextButton = "GuiButton", ImageLabel = "GuiObject",
	ImageButton = "GuiButton", TextBox = "GuiObject", ScrollingFrame = "GuiObject", CanvasGroup = "GuiObject",
	ViewportFrame = "GuiObject", VideoFrame = "GuiObject",
	GuiButton = "GuiObject", GuiObject = "GuiBase2d", ScreenGui = "LayerCollector", SurfaceGui = "LayerCollector",
	BillboardGui = "LayerCollector", LayerCollector = "GuiBase2d", GuiBase2d = "Instance",
	UIListLayout = "UIGridStyleLayout", UIGridLayout = "UIGridStyleLayout", UIGridStyleLayout = "UIComponent",
	UIPadding = "UIComponent", UICorner = "UIComponent", UIStroke = "UIComponent", UIScale = "UIComponent",
	UIAspectRatioConstraint = "UIComponent", UISizeConstraint = "UIComponent", UITextSizeConstraint = "UIComponent",
	UIGradient = "UIComponent", UIFlexItem = "UIComponent", UIComponent = "Instance",
	IntValue = "ValueBase", NumberValue = "ValueBase", StringValue = "ValueBase", BoolValue = "ValueBase",
	ObjectValue = "ValueBase", CFrameValue = "ValueBase", Vector3Value = "ValueBase", Color3Value = "ValueBase",
	ValueBase = "Instance",
	Script = "BaseScript", LocalScript = "Script", BaseScript = "LuaSourceContainer", ModuleScript = "LuaSourceContainer",
	LuaSourceContainer = "Instance",
	PointLight = "Light", SpotLight = "Light", SurfaceLight = "Light", Light = "Instance",
	WeldConstraint = "Instance", Weld = "JointInstance", Motor6D = "JointInstance", JointInstance = "Instance",
	AlignPosition = "Constraint", AlignOrientation = "Constraint", LinearVelocity = "Constraint",
	AngularVelocity = "Constraint", VectorForce = "Constraint", RopeConstraint = "Constraint",
	HingeConstraint = "Constraint", SpringConstraint = "Constraint", RigidConstraint = "Constraint",
	BallSocketConstraint = "Constraint", PrismaticConstraint = "Constraint", Constraint = "Instance",
	Players = "Instance", Player = "Instance", Tool = "BackpackItem", BackpackItem = "Instance",
}
function __isA(className, wanted)
	local c = className
	while c do
		if c == wanted then
			return true
		end
		c = CLASS_PARENT[c]
	end
	return wanted == "Instance"
end

local EVENTS = {}
for _, name in {
	"Touched", "TouchEnded", "Changed", "ChildAdded", "ChildRemoved", "DescendantAdded", "DescendantRemoving",
	"AncestryChanged", "Destroying", "AttributeChanged", "Activated", "Deactivated", "Equipped", "Unequipped",
	"MouseButton1Click", "MouseButton1Down", "MouseButton1Up", "MouseButton2Click", "MouseEnter", "MouseLeave",
	"InputBegan", "InputEnded", "InputChanged", "FocusLost", "Focused", "SelectionGained", "SelectionLost",
	"Triggered", "TriggerEnded", "PromptShown", "PromptHidden", "PromptButtonHoldBegan", "PromptButtonHoldEnded",
	"Died", "HealthChanged", "Running", "StateChanged", "MoveToFinished", "Jumping", "FreeFalling",
	"OnServerEvent", "OnClientEvent", "Event", "CharacterAdded", "CharacterRemoving", "CharacterAppearanceLoaded",
	"PlayerAdded", "PlayerRemoving", "Heartbeat", "Stepped", "RenderStepped", "PreSimulation", "PostSimulation",
	"PreRender", "PreAnimation", "Completed", "Blocked", "Unblocked", "Ended", "Stopped", "DidLoop", "Played",
	"Paused", "Resumed", "Loaded", "KeyframeReached", "ReachedTarget", "TextChanged", "Chatted", "Idled",
	"MessageReceived", "SendingMessage", "Seated", "PromptTriggered", "PromptTriggerEnded", "TeleportInitFailed",
	"LocalPlayerArrivedFromTeleport", "PromptGamePassPurchaseFinished", "PromptProductPurchaseFinished",
	"PromptPurchaseFinished", "LastInputTypeChanged", "JumpRequest", "TouchTap", "WindowFocused",
} do
	EVENTS[name] = true
end

local InstanceT = { __type = "Instance" }
local METHODS = {}
local CLASS_METHODS = {}
local DEFAULTS = {
	BasePart = { Anchored = false, CanCollide = true, CanTouch = true, CanQuery = true, Transparency = 0,
		Size = v3(4, 1, 2), Massless = false, CollisionGroup = "Default" },
	Humanoid = { Health = 100, MaxHealth = 100, WalkSpeed = 16, JumpPower = 50, JumpHeight = 7.2, AutoRotate = true },
	GuiObject = { Visible = true, BackgroundTransparency = 0, ZIndex = 1, LayoutOrder = 0, Active = false },
	GuiButton = { AutoButtonColor = true, Active = true },
	ScreenGui = { Enabled = true, ResetOnSpawn = true, DisplayOrder = 0, IgnoreGuiInset = false },
	ParticleEmitter = { Enabled = true, Rate = 5 },
	Beam = { Enabled = true },
	Trail = { Enabled = true },
	Sound = { Volume = 0.5, Playing = false, Looped = false, TimeLength = 1, PlaybackSpeed = 1 },
	ProximityPrompt = { Enabled = true, HoldDuration = 0, MaxActivationDistance = 10, RequiresLineOfSight = true,
		ActionText = "Interact", ObjectText = "" },
	ValueBase = { Value = 0 },
	StringValue = { Value = "" },
	BoolValue = { Value = false },
	ObjectValue = {},
	Light = { Enabled = true, Brightness = 1, Range = 8 },
	Tool = { RequiresHandle = true, Enabled = true, CanBeDropped = true },
	Player = { UserId = 0, AccountAge = 30, MembershipType = nil },
	Model = {},
	Animation = { AnimationId = "" },
}

local function defaultsFor(className)
	local out = {}
	local chain = {}
	local c = className
	while c do
		table.insert(chain, 1, c)
		c = CLASS_PARENT[c]
	end
	for _, name in chain do
		for k, v in DEFAULTS[name] or {} do
			out[k] = v
		end
	end
	return out
end

local function fireChanged(self, prop)
	local d = rawget(self, "_d")
	local sigs = d.propSignals[prop]
	if sigs then
		sigs:Fire()
	end
	if d.events.Changed then
		d.events.Changed:Fire(prop)
	end
end

local function setParent(self, parent)
	local d = rawget(self, "_d")
	if d.destroyed and parent ~= nil then
		error("The Parent property of " .. tostring(d.props.Name) .. " is locked")
	end
	local old = d.parent
	if old == parent then
		return
	end
	if old then
		local od = rawget(old, "_d")
		for i, c in od.children do
			if c == self then
				table.remove(od.children, i)
				break
			end
		end
		if od.events.ChildRemoved then
			od.events.ChildRemoved:Fire(self)
		end
	end
	d.parent = parent
	if parent then
		local pd = rawget(parent, "_d")
		table.insert(pd.children, self)
		if pd.events.ChildAdded then
			pd.events.ChildAdded:Fire(self)
		end
		local a = parent
		while a do
			local ad = rawget(a, "_d")
			if ad.events.DescendantAdded then
				ad.events.DescendantAdded:Fire(self)
			end
			a = ad.parent
		end
	end
	if d.events.AncestryChanged then
		d.events.AncestryChanged:Fire(self, parent)
	end
	fireChanged(self, "Parent")
end

InstanceT.__index = function(self, key)
	local d = rawget(self, "_d")
	if key == "Parent" then
		return d.parent
	elseif key == "ClassName" then
		return d.className
	end
	local v = d.props[key]
	if v ~= nil then
		return v
	end
	local cm = CLASS_METHODS[d.className]
	if cm and cm[key] then
		return cm[key]
	end
	local c = CLASS_PARENT[d.className]
	while c do
		local m = CLASS_METHODS[c]
		if m and m[key] then
			return m[key]
		end
		c = CLASS_PARENT[c]
	end
	if METHODS[key] then
		return METHODS[key]
	end
	if EVENTS[key] then
		local s = d.events[key]
		if not s then
			s = newSignal()
			d.events[key] = s
		end
		return s
	end
	if d.getters[key] then
		return d.getters[key](self)
	end
	for _, child in d.children do
		if rawget(child, "_d").props.Name == key then
			return child
		end
	end
	return nil
end

InstanceT.__newindex = function(self, key, value)
	local d = rawget(self, "_d")
	if key == "Parent" then
		setParent(self, value)
		return
	end
	if d.setters[key] then
		d.setters[key](self, value)
	else
		d.props[key] = value
	end
	fireChanged(self, key)
end

InstanceT.__tostring = function(self)
	return tostring(rawget(self, "_d").props.Name)
end

local function partSetters(d)
	d.setters.CFrame = function(_, value)
		d.props.CFrame = value
		d.props.Position = value.Position
	end
	d.setters.Position = function(_, value)
		local old = d.props.CFrame or CFrame.identity
		d.props.CFrame = CFrame.new(value) * old.Rotation
		d.props.Position = value
	end
	d.props.CFrame = CFrame.identity
	d.props.Position = Vector3.zero
	d.props.AssemblyLinearVelocity = Vector3.zero
	d.props.AssemblyAngularVelocity = Vector3.zero
	d.props.Color = c3(0.64, 0.64, 0.64)
end

local function humanoidSetters(self, d)
	d.setters.Health = function(_, value)
		local old = d.props.Health
		local new = math.clamp(value, 0, d.props.MaxHealth)
		d.props.Health = new
		if new ~= old then
			self.HealthChanged:Fire(new)
		end
		if new <= 0 and old > 0 then
			self.Died:Fire()
		end
	end
end

local guidCounter = 0
local function newInstance(className, parent)
	local d = {
		className = className, props = defaultsFor(className), children = {}, events = {}, propSignals = {},
		attributes = {}, attrSignals = {}, tags = {}, setters = {}, getters = {}, parent = nil,
	}
	d.props.Name = className
	local self = setmetatable({ _d = d }, InstanceT)
	if __isA(className, "BasePart") then
		partSetters(d)
	elseif className == "Humanoid" then
		humanoidSetters(self, d)
	elseif className == "Model" then
		d.props.WorldPivot = CFrame.identity
	elseif __isA(className, "GuiObject") then
		d.props.Size = UDim2.new(0, 100, 0, 100)
		d.props.Position = UDim2.new(0, 0, 0, 0)
		d.props.AbsoluteSize = Vector2.new(100, 100)
		d.props.AbsolutePosition = Vector2.zero
	elseif className == "RemoteEvent" or className == "UnreliableRemoteEvent" or className == "RemoteFunction"
		or className == "BindableEvent" then
		d.props.__sent = {}
	end
	guidCounter += 1
	d.id = guidCounter
	if parent then
		setParent(self, parent)
	end
	return self
end

Instance = {}
function Instance.new(className, parent)
	assert(type(className) == "string", "Instance.new expects a class name")
	return newInstance(className, parent)
end
function Instance.fromExisting(other)
	return other:Clone()
end

function METHODS.GetChildren(self)
	return table.clone(rawget(self, "_d").children)
end
function METHODS.GetDescendants(self)
	local out = {}
	local function walk(inst)
		for _, c in rawget(inst, "_d").children do
			table.insert(out, c)
			walk(c)
		end
	end
	walk(self)
	return out
end
function METHODS.FindFirstChild(self, name, recursive)
	for _, c in rawget(self, "_d").children do
		if rawget(c, "_d").props.Name == name then
			return c
		end
	end
	if recursive then
		for _, c in rawget(self, "_d").children do
			local f = c:FindFirstChild(name, true)
			if f then
				return f
			end
		end
	end
	return nil
end
function METHODS.WaitForChild(self, name, timeout)
	local found = self:FindFirstChild(name)
	if found or not coroutine.isyieldable() then
		return found
	end
	local deadline = timeout and (__now + timeout)
	while not found do
		task.wait(0.03)
		found = self:FindFirstChild(name)
		if deadline and __now >= deadline then
			return nil
		end
	end
	return found
end
function METHODS.FindFirstChildOfClass(self, className)
	for _, c in rawget(self, "_d").children do
		if rawget(c, "_d").className == className then
			return c
		end
	end
	return nil
end
function METHODS.FindFirstChildWhichIsA(self, className, recursive)
	for _, c in rawget(self, "_d").children do
		if __isA(rawget(c, "_d").className, className) then
			return c
		end
	end
	if recursive then
		for _, c in rawget(self, "_d").children do
			local f = c:FindFirstChildWhichIsA(className, true)
			if f then
				return f
			end
		end
	end
	return nil
end
function METHODS.FindFirstAncestor(self, name)
	local a = rawget(self, "_d").parent
	while a do
		if rawget(a, "_d").props.Name == name then
			return a
		end
		a = rawget(a, "_d").parent
	end
	return nil
end
function METHODS.FindFirstAncestorOfClass(self, className)
	local a = rawget(self, "_d").parent
	while a do
		if rawget(a, "_d").className == className then
			return a
		end
		a = rawget(a, "_d").parent
	end
	return nil
end
function METHODS.FindFirstAncestorWhichIsA(self, className)
	local a = rawget(self, "_d").parent
	while a do
		if __isA(rawget(a, "_d").className, className) then
			return a
		end
		a = rawget(a, "_d").parent
	end
	return nil
end
function METHODS.IsA(self, className)
	return __isA(rawget(self, "_d").className, className)
end
function METHODS.IsDescendantOf(self, other)
	local a = rawget(self, "_d").parent
	while a do
		if a == other then
			return true
		end
		a = rawget(a, "_d").parent
	end
	return false
end
function METHODS.IsAncestorOf(self, other)
	return other:IsDescendantOf(self)
end
function METHODS.GetFullName(self)
	local names = {}
	local a = self
	while a and a ~= game do
		table.insert(names, 1, rawget(a, "_d").props.Name)
		a = rawget(a, "_d").parent
	end
	return table.concat(names, ".")
end
function METHODS.Destroy(self)
	local d = rawget(self, "_d")
	if d.destroyed then
		return
	end
	if d.events.Destroying then
		d.events.Destroying:Fire()
	end
	for _, c in table.clone(d.children) do
		c:Destroy()
	end
	setParent(self, nil)
	d.destroyed = true
	for _, s in d.events do
		for _, c in table.clone(s._list) do
			c:Disconnect()
		end
	end
end
function METHODS.ClearAllChildren(self)
	for _, c in table.clone(rawget(self, "_d").children) do
		c:Destroy()
	end
end
function METHODS.Clone(self)
	local d = rawget(self, "_d")
	local copy = newInstance(d.className)
	local cd = rawget(copy, "_d")
	for k, v in d.props do
		cd.props[k] = v
	end
	for k, v in d.attributes do
		cd.attributes[k] = v
	end
	for k in d.tags do
		cd.tags[k] = true
	end
	for _, c in d.children do
		c:Clone().Parent = copy
	end
	return copy
end
function METHODS.GetAttribute(self, name)
	return rawget(self, "_d").attributes[name]
end
function METHODS.SetAttribute(self, name, value)
	local d = rawget(self, "_d")
	local t = typeof(value)
	if value ~= nil and t ~= "string" and t ~= "number" and t ~= "boolean" and t ~= "Vector3" and t ~= "Vector2"
		and t ~= "Color3" and t ~= "UDim2" and t ~= "UDim" and t ~= "CFrame" and t ~= "NumberRange"
		and t ~= "BrickColor" and t ~= "EnumItem" and t ~= "NumberSequence" and t ~= "ColorSequence" and t ~= "Rect" then
		error("SetAttribute: unsupported attribute type " .. t)
	end
	if d.attributes[name] == value then
		return
	end
	d.attributes[name] = value
	if d.attrSignals[name] then
		d.attrSignals[name]:Fire()
	end
	if d.events.AttributeChanged then
		d.events.AttributeChanged:Fire(name)
	end
end
function METHODS.GetAttributes(self)
	return table.clone(rawget(self, "_d").attributes)
end
function METHODS.GetAttributeChangedSignal(self, name)
	local d = rawget(self, "_d")
	d.attrSignals[name] = d.attrSignals[name] or newSignal()
	return d.attrSignals[name]
end
function METHODS.GetPropertyChangedSignal(self, prop)
	local d = rawget(self, "_d")
	d.propSignals[prop] = d.propSignals[prop] or newSignal()
	return d.propSignals[prop]
end
local tagIndex = {} -- tag -> { [instance] = true }
local tagAdded, tagRemoved = {}, {}
local function tagSignal(map, tag)
	map[tag] = map[tag] or newSignal()
	return map[tag]
end
function METHODS.AddTag(self, tag)
	local d = rawget(self, "_d")
	if d.tags[tag] then
		return
	end
	d.tags[tag] = true
	tagIndex[tag] = tagIndex[tag] or {}
	tagIndex[tag][self] = true
	tagSignal(tagAdded, tag):Fire(self)
end
function METHODS.RemoveTag(self, tag)
	local d = rawget(self, "_d")
	if not d.tags[tag] then
		return
	end
	d.tags[tag] = nil
	tagIndex[tag][self] = nil
	tagSignal(tagRemoved, tag):Fire(self)
end
function METHODS.HasTag(self, tag)
	return rawget(self, "_d").tags[tag] == true
end
function METHODS.GetTags(self)
	local out = {}
	for t in rawget(self, "_d").tags do
		table.insert(out, t)
	end
	table.sort(out)
	return out
end
function METHODS.GetActor()
	return nil
end

-- PVInstance / parts / models
local function modelPivot(self)
	local d = rawget(self, "_d")
	if d.props.PrimaryPart then
		return d.props.PrimaryPart.CFrame
	end
	return d.props.WorldPivot or CFrame.identity
end
CLASS_METHODS.BasePart = {
	GetPivot = function(self)
		return self.CFrame
	end,
	PivotTo = function(self, target)
		self.CFrame = target
	end,
	GetMass = function(self)
		local s = self.Size
		return s.X * s.Y * s.Z * 0.7
	end,
	ApplyImpulse = function(self, impulse)
		local d = rawget(self, "_d")
		d.props.__impulses = d.props.__impulses or {}
		table.insert(d.props.__impulses, impulse)
	end,
	ApplyAngularImpulse = function() end,
	SetNetworkOwner = function(self, player)
		rawget(self, "_d").props.__owner = player or false
	end,
	GetNetworkOwner = function(self)
		local o = rawget(self, "_d").props.__owner
		return o or nil
	end,
	SetNetworkOwnershipAuto = function(self)
		rawget(self, "_d").props.__owner = nil
	end,
	CanSetNetworkOwnership = function()
		return true, nil
	end,
	GetTouchingParts = function()
		return {}
	end,
	GetConnectedParts = function()
		return {}
	end,
}
CLASS_METHODS.Model = {
	GetPivot = modelPivot,
	PivotTo = function(self, target)
		local d = rawget(self, "_d")
		local current = modelPivot(self)
		local delta = target * current:Inverse()
		for _, p in self:GetDescendants() do
			if p:IsA("BasePart") then
				p.CFrame = delta * p.CFrame
			end
		end
		d.props.WorldPivot = target
	end,
	GetBoundingBox = function(self)
		return modelPivot(self), self:GetExtentsSize()
	end,
	GetExtentsSize = function(self)
		local mn, mx
		for _, p in self:GetDescendants() do
			if p:IsA("BasePart") then
				local half = p.Size / 2
				local lo, hi = p.Position - half, p.Position + half
				mn = mn and mn:Min(lo) or lo
				mx = mx and mx:Max(hi) or hi
			end
		end
		if not mn then
			return Vector3.zero
		end
		return mx - mn
	end,
	ScaleTo = function(self, s)
		rawget(self, "_d").props.__scale = s
	end,
	GetScale = function(self)
		return rawget(self, "_d").props.__scale or 1
	end,
}

-- Humanoid / animation
local TrackT = { __type = "Instance" }
CLASS_METHODS.Humanoid = {
	TakeDamage = function(self, amount)
		if self:FindFirstChildOfClass("ForceField") == nil and self.Parent and self.Parent:FindFirstChildOfClass("ForceField") then
			return
		end
		self.Health = self.Health - amount
	end,
	MoveTo = function(self, pos, part)
		local d = rawget(self, "_d")
		d.props.__moveTo = pos
		d.props.__moveToPart = part
		d.props.__moves = (d.props.__moves or 0) + 1
	end,
	ChangeState = function(self, state)
		rawget(self, "_d").props.__state = state
	end,
	GetState = function(self)
		return rawget(self, "_d").props.__state or Enum.HumanoidStateType.Running
	end,
	SetStateEnabled = function(self, state, enabled)
		local d = rawget(self, "_d")
		d.props.__disabledStates = d.props.__disabledStates or {}
		d.props.__disabledStates[state] = not enabled
	end,
	GetStateEnabled = function(self, state)
		local s = rawget(self, "_d").props.__disabledStates
		return not (s and s[state])
	end,
	UnequipTools = function(self)
		local char = self.Parent
		if char then
			for _, t in char:GetChildren() do
				if t:IsA("Tool") then
					t.Parent = nil
				end
			end
		end
	end,
	EquipTool = function(self, tool)
		tool.Parent = self.Parent
	end,
	GetAppliedDescription = function()
		return Instance.new("HumanoidDescription")
	end,
	ApplyDescription = function() end,
}
local function newTrack(animation)
	local track = newInstance("AnimationTrack")
	local d = rawget(track, "_d")
	d.props.Animation = animation
	d.props.IsPlaying = false
	d.props.Length = 1
	d.props.Speed = 1
	d.props.WeightCurrent = 0
	d.props.TimePosition = 0
	d.props.Looped = false
	d.props.Priority = Enum.AnimationPriority.Core
	d.markers = {}
	return track
end
CLASS_METHODS.AnimationTrack = {
	Play = function(self, fadeTime, weight, speed)
		local d = rawget(self, "_d")
		d.props.IsPlaying = true
		d.props.__plays = (d.props.__plays or 0) + 1
		d.props.Speed = speed or d.props.Speed
		self.Played:Fire()
		if not d.props.Looped then
			task.delay(d.props.Length / math.max(d.props.Speed, 1e-3), function()
				if d.props.IsPlaying then
					d.props.IsPlaying = false
					self.Stopped:Fire()
					self.Ended:Fire()
				end
			end)
		end
	end,
	Stop = function(self)
		local d = rawget(self, "_d")
		if d.props.IsPlaying then
			d.props.IsPlaying = false
			self.Stopped:Fire()
			self.Ended:Fire()
		end
	end,
	AdjustSpeed = function(self, s)
		rawget(self, "_d").props.Speed = s
	end,
	AdjustWeight = function(self, w)
		rawget(self, "_d").props.WeightCurrent = w
	end,
	GetMarkerReachedSignal = function(self, name)
		local d = rawget(self, "_d")
		d.markers[name] = d.markers[name] or newSignal()
		return d.markers[name]
	end,
	GetTimeOfKeyframe = function()
		return 0
	end,
}
local _ = TrackT
local function loadAnimation(self, animation)
	assert(animation and animation:IsA("Animation"), "LoadAnimation needs an Animation")
	local track = newTrack(animation)
	local d = rawget(self, "_d")
	d.props.__tracks = d.props.__tracks or {}
	table.insert(d.props.__tracks, track)
	return track
end
CLASS_METHODS.Animator = {
	LoadAnimation = loadAnimation,
	GetPlayingAnimationTracks = function(self)
		local out = {}
		for _, t in rawget(self, "_d").props.__tracks or {} do
			if t.IsPlaying then
				table.insert(out, t)
			end
		end
		return out
	end,
}
CLASS_METHODS.AnimationController = {}

-- Remotes and bindables
local function sent(self, entry)
	table.insert(rawget(self, "_d").props.__sent, entry)
end
CLASS_METHODS.RemoteEvent = {
	FireClient = function(self, player, ...)
		assert(typeof(player) == "Instance" and player:IsA("Player"), "FireClient needs a Player")
		sent(self, { player, ... })
	end,
	FireAllClients = function(self, ...)
		sent(self, { "all", ... })
	end,
	FireServer = function(self, ...)
		sent(self, { "server", ... })
	end,
}
CLASS_METHODS.UnreliableRemoteEvent = CLASS_METHODS.RemoteEvent
CLASS_METHODS.RemoteFunction = {
	InvokeServer = function(self, ...)
		local f = rawget(self, "_d").props.OnServerInvoke
		assert(f, "OnServerInvoke is not set")
		return f(__localPlayer, ...)
	end,
	InvokeClient = function(self, player, ...)
		local f = rawget(self, "_d").props.OnClientInvoke
		assert(f, "OnClientInvoke is not set")
		return f(...)
	end,
}
CLASS_METHODS.BindableEvent = {
	Fire = function(self, ...)
		self.Event:Fire(...)
	end,
}
CLASS_METHODS.BindableFunction = {
	Invoke = function(self, ...)
		return rawget(self, "_d").props.OnInvoke(...)
	end,
}

-- Effects and sounds
CLASS_METHODS.ParticleEmitter = {
	Emit = function(self, n)
		local d = rawget(self, "_d")
		d.props.__emitted = (d.props.__emitted or 0) + (n or 16)
	end,
	Clear = function() end,
}
CLASS_METHODS.Sound = {
	Play = function(self)
		local d = rawget(self, "_d")
		d.props.Playing = true
		d.props.__plays = (d.props.__plays or 0) + 1
		self.Played:Fire(d.props.SoundId)
		if not d.props.Looped then
			task.delay(d.props.TimeLength / d.props.PlaybackSpeed, function()
				if d.props.Playing then
					d.props.Playing = false
					self.Ended:Fire(d.props.SoundId)
				end
			end)
		end
	end,
	Stop = function(self)
		rawget(self, "_d").props.Playing = false
		self.Stopped:Fire()
	end,
	Pause = function(self)
		rawget(self, "_d").props.Playing = false
	end,
	Resume = function(self)
		rawget(self, "_d").props.Playing = true
	end,
}

-- Players and characters
__players = {}
CLASS_METHODS.Player = {
	Kick = function(self, message)
		local d = rawget(self, "_d")
		d.props.__kicked = message or true
	end,
	LoadCharacter = function(self)
		__makeCharacter(self)
	end,
	GetMouse = function()
		return newInstance("Mouse")
	end,
	IsInGroup = function()
		return false
	end,
	GetRankInGroup = function()
		return 0
	end,
	DistanceFromCharacter = function(self, point)
		local c = self.Character
		local root = c and c:FindFirstChild("HumanoidRootPart")
		return root and (root.Position - point).Magnitude or 0
	end,
	GetNetworkPing = function()
		return 0.05
	end,
}

-- Tool
CLASS_METHODS.Tool = {
	Activate = function(self)
		self.Activated:Fire()
	end,
}

-- GUI
CLASS_METHODS.GuiObject = {
	TweenPosition = function(self, pos)
		self.Position = pos
		return true
	end,
	TweenSize = function(self, size)
		self.Size = size
		return true
	end,
}
CLASS_METHODS.TextBox = {
	CaptureFocus = function() end,
	ReleaseFocus = function(self, submitted)
		self.FocusLost:Fire(submitted == true)
	end,
	IsFocused = function()
		return false
	end,
}

------------------------------------------------------------------------------------------------ DataModel and services
game = newInstance("DataModel")
rawget(game, "_d").props.Name = "Game"
rawget(game, "_d").props.PlaceId = 1234
rawget(game, "_d").props.GameId = 5678
rawget(game, "_d").props.JobId = "00000000-job"
rawget(game, "_d").props.PrivateServerId = ""
rawget(game, "_d").props.PrivateServerOwnerId = 0
rawget(game, "_d").props.CreatorId = 1
local closeHandlers = {}
local services = {}

local KNOWN_SERVICES = {}
for _, n in {
	"Players", "ReplicatedStorage", "ServerStorage", "ServerScriptService", "ReplicatedFirst", "StarterGui",
	"StarterPack", "StarterPlayer", "Workspace", "Lighting", "SoundService", "RunService", "DataStoreService",
	"MemoryStoreService", "MessagingService", "HttpService", "TweenService", "CollectionService",
	"PathfindingService", "TextService", "TextChatService", "MarketplaceService", "BadgeService", "TeleportService",
	"Debris", "UserInputService", "ContextActionService", "GuiService", "Teams", "Chat", "LocalizationService",
	"PhysicsService", "ProximityPromptService", "ContentProvider", "PolicyService", "GroupService", "SocialService",
	"AnalyticsService", "HapticService", "VRService", "AssetService", "InsertService", "ScriptContext", "Stats",
	"LogService", "TestService", "SharedTableRegistry", "AvatarEditorService", "ExperienceNotificationService",
	"VoiceChatService", "StarterPlayerScripts", "MaterialService", "GamepadService", "ChangeHistoryService",
	"Selection", "UserService",
} do
	KNOWN_SERVICES[n] = true
end

function CLASS_METHODS.DataModel_GetService(self, name)
	return self:GetService(name)
end
local function getService(_, name)
	if services[name] then
		return services[name]
	end
	if not KNOWN_SERVICES[name] then
		error("'" .. tostring(name) .. "' is not a valid Service name")
	end
	local s
	if name == "Workspace" then
		s = workspace
	else
		s = newInstance(name, game)
		rawget(s, "_d").props.Name = name
	end
	services[name] = s
	return s
end
CLASS_METHODS.DataModel = {
	GetService = getService,
	FindService = function(self, name)
		return services[name]
	end,
	BindToClose = function(_, fn)
		table.insert(closeHandlers, fn)
	end,
	IsLoaded = function()
		return true
	end,
}
function __close()
	for _, fn in closeHandlers do
		task.spawn(fn)
	end
	__advance(30)
end

workspace = newInstance("Workspace", game)
rawget(workspace, "_d").props.Name = "Workspace"
rawget(workspace, "_d").props.Gravity = 196.2
rawget(workspace, "_d").props.StreamingEnabled = false
services.Workspace = workspace
local camera = newInstance("Camera", workspace)
rawget(camera, "_d").props.Name = "Camera"
rawget(camera, "_d").props.ViewportSize = Vector2.new(1280, 720)
rawget(camera, "_d").props.FieldOfView = 70
rawget(workspace, "_d").props.CurrentCamera = camera
rawget(game, "_d").getters = rawget(game, "_d").getters
rawget(game, "_d").getters.Workspace = function()
	return workspace
end
for _, n in { "Players", "ReplicatedStorage", "ServerStorage", "ServerScriptService", "Lighting", "StarterGui",
	"StarterPack", "StarterPlayer", "ReplicatedFirst", "Teams", "SoundService", "Chat" } do
	rawget(game, "_d").getters[n] = function()
		return getService(game, n)
	end
end

script = newInstance("Script", getService(game, "ServerScriptService"))

-- spatial queries over the parts in workspace (axis-aligned boxes; rotation ignored)
local function filtered(params, part)
	if not params then
		return true
	end
	local list = params.FilterDescendantsInstances or {}
	local inList = false
	for _, inst in list do
		if part == inst or part:IsDescendantOf(inst) then
			inList = true
			break
		end
	end
	if params.FilterType == Enum.RaycastFilterType.Include then
		return inList
	end
	return not inList
end
local function queryParts(params)
	local out = {}
	for _, p in workspace:GetDescendants() do
		if p:IsA("BasePart") and p.CanQuery ~= false and filtered(params, p) then
			table.insert(out, p)
		end
	end
	return out
end
local function rayBox(origin, dir, part)
	local half = part.Size / 2
	local lo, hi = part.Position - half, part.Position + half
	local tmin, tmax = -math.huge, math.huge
	local normal = Vector3.zero
	for _, axis in { "X", "Y", "Z" } do
		local o, dd = origin[axis], dir[axis]
		if math.abs(dd) < 1e-12 then
			if o < lo[axis] or o > hi[axis] then
				return nil
			end
		else
			local t1, t2 = (lo[axis] - o) / dd, (hi[axis] - o) / dd
			local n = -1
			if t1 > t2 then
				t1, t2 = t2, t1
				n = 1
			end
			if t1 > tmin then
				tmin = t1
				normal = Vector3.new(axis == "X" and n or 0, axis == "Y" and n or 0, axis == "Z" and n or 0)
			end
			tmax = math.min(tmax, t2)
			if tmin > tmax then
				return nil
			end
		end
	end
	if tmax < 0 or tmin > 1 then
		return nil
	end
	return math.max(tmin, 0), normal
end
local RaycastResultT = makeType("RaycastResult")
CLASS_METHODS.Workspace = {
	Raycast = function(_, origin, direction, params)
		local best, bestT, bestN = nil, math.huge, nil
		for _, p in queryParts(params) do
			local t, n = rayBox(origin, direction, p)
			if t and t < bestT then
				best, bestT, bestN = p, t, n
			end
		end
		if not best then
			return nil
		end
		local pos = origin + direction * bestT
		return setmetatable({ Instance = best, Position = pos, Normal = bestN, Distance = (direction * bestT).Magnitude,
			Material = best.Material or Enum.Material.Plastic }, RaycastResultT)
	end,
	Spherecast = function(self, origin, _radius, direction, params)
		return self:Raycast(origin, direction, params)
	end,
	Blockcast = function(self, cframe, _size, direction, params)
		return self:Raycast(cframe.Position, direction, params)
	end,
	GetPartBoundsInRadius = function(_, center, radius, params)
		local out = {}
		for _, p in queryParts(params) do
			local half = p.Size / 2
			local closest = p.Position + (center - p.Position):Max(-half):Min(half)
			if (closest - center).Magnitude <= radius then
				table.insert(out, p)
			end
		end
		return out
	end,
	GetPartBoundsInBox = function(_, cframe, size, params)
		local out = {}
		local c, h = cframe.Position, size / 2
		for _, p in queryParts(params) do
			local ph = p.Size / 2
			local d = (p.Position - c):Abs()
			if d.X <= h.X + ph.X and d.Y <= h.Y + ph.Y and d.Z <= h.Z + ph.Z then
				table.insert(out, p)
			end
		end
		return out
	end,
	GetPartsInPart = function(self, part, params)
		return self:GetPartBoundsInBox(part.CFrame, part.Size, params)
	end,
	GetServerTimeNow = function()
		return 1700000000 + __now
	end,
	BulkMoveTo = function(_, parts, cframes)
		for i, p in parts do
			p.CFrame = cframes[i]
		end
	end,
}

-- Players
local Players = getService(game, "Players")
rawget(Players, "_d").props.MaxPlayers = 20
local isClient = false
__localPlayer = nil
function __setClient(flag)
	isClient = flag
end
CLASS_METHODS.Players = {
	GetPlayers = function()
		return table.clone(__players)
	end,
	GetPlayerByUserId = function(_, id)
		for _, p in __players do
			if p.UserId == id then
				return p
			end
		end
		return nil
	end,
	GetPlayerFromCharacter = function(_, model)
		for _, p in __players do
			if p.Character == model and model ~= nil then
				return p
			end
		end
		return nil
	end,
	GetNameFromUserIdAsync = function(_, id)
		return "User" .. tostring(id)
	end,
	GetUserIdFromNameAsync = function()
		return 1
	end,
	GetUserThumbnailAsync = function(_, id)
		return "rbxthumb://type=AvatarHeadShot&id=" .. tostring(id) .. "&w=150&h=150", true
	end,
	CreateHumanoidModelFromDescription = function()
		return __buildRig()
	end,
}
function __buildRig(position)
	local model = Instance.new("Model")
	model.Name = "Rig"
	local root = Instance.new("Part")
	root.Name = "HumanoidRootPart"
	root.Size = Vector3.new(2, 2, 1)
	root.Position = position or Vector3.new(0, 3, 0)
	root.Parent = model
	local head = Instance.new("Part")
	head.Name = "Head"
	head.Size = Vector3.new(2, 1, 1)
	head.Position = root.Position + Vector3.new(0, 1.5, 0)
	head.Parent = model
	local rightHand = Instance.new("Part")
	rightHand.Name = "RightHand"
	rightHand.Size = Vector3.new(1, 0.3, 1)
	rightHand.Position = root.Position + Vector3.new(1.5, -1, 0)
	rightHand.Parent = model
	model.PrimaryPart = root
	local humanoid = Instance.new("Humanoid")
	humanoid.Parent = model
	local animator = Instance.new("Animator")
	animator.Parent = humanoid
	return model
end
function __makeCharacter(player, position)
	local old = player.Character
	if old then
		player.CharacterRemoving:Fire(old)
		old:Destroy()
	end
	local model = __buildRig(position)
	model.Name = player.Name
	player.Character = model
	model.Parent = workspace
	player.CharacterAdded:Fire(model)
	return model
end
function __makePlayer(userId, name)
	local p = newInstance("Player")
	local d = rawget(p, "_d")
	d.props.Name = name or ("Player" .. tostring(userId))
	d.props.DisplayName = d.props.Name
	d.props.UserId = userId
	local backpack = newInstance("Backpack", p)
	rawget(backpack, "_d").props.Name = "Backpack"
	local pg = newInstance("PlayerGui", p)
	rawget(pg, "_d").props.Name = "PlayerGui"
	table.insert(__players, p)
	setParent(p, Players)
	if isClient and __localPlayer == nil then
		__localPlayer = p
		rawget(Players, "_d").props.LocalPlayer = p
	end
	Players.PlayerAdded:Fire(p)
	return p
end
function __removePlayer(p)
	Players.PlayerRemoving:Fire(p)
	for i, q in __players do
		if q == p then
			table.remove(__players, i)
		end
	end
	if p.Character then
		p.Character:Destroy()
	end
	setParent(p, nil)
end

-- RunService
local RunService = getService(game, "RunService")
CLASS_METHODS.RunService = {
	IsServer = function()
		return not isClient
	end,
	IsClient = function()
		return isClient
	end,
	IsStudio = function()
		return false
	end,
	IsRunning = function()
		return true
	end,
	BindToRenderStep = function(_, name, _priority, fn)
		RunService.__render = RunService.__render or {}
		RunService.__render[name] = fn
	end,
	UnbindFromRenderStep = function(_, name)
		if RunService.__render then
			RunService.__render[name] = nil
		end
	end,
}
function __frames(n, dt)
	dt = dt or 1 / 60
	for _ = 1, n do
		__advance(dt)
		RunService.PreSimulation:Fire(dt)
		RunService.Stepped:Fire(__now, dt)
		RunService.Heartbeat:Fire(dt)
		RunService.PostSimulation:Fire(dt)
		if isClient then
			RunService.RenderStepped:Fire(dt)
			RunService.PreRender:Fire(dt)
			for _, fn in RunService.__render or {} do
				fn(dt)
			end
		end
	end
end

-- DataStoreService (in memory; values must be serialisable like the real service)
local DataStoreService = getService(game, "DataStoreService")
rawget(DataStoreService, "_d").props.__failNext = 0
rawget(DataStoreService, "_d").props.__calls = 0
local stores = {}
local function checkStorable(v, path, seen)
	local t = typeof(v)
	if t == "nil" or t == "boolean" or t == "string" then
		return
	elseif t == "number" then
		if v ~= v or v == math.huge or v == -math.huge then
			error("Cannot store NaN or inf at " .. path)
		end
		return
	elseif t == "table" then
		if seen[v] then
			error("Cannot store a cyclic table at " .. path)
		end
		seen[v] = true
		local n = #v
		local count = 0
		for k, val in v do
			count += 1
			if type(k) ~= "string" and not (type(k) == "number" and k >= 1 and k <= n and k % 1 == 0) then
				error("Cannot store a table with mixed or non-string keys at " .. path)
			end
			checkStorable(val, path .. "." .. tostring(k), seen)
		end
		if n > 0 and count ~= n then
			error("Cannot store a mixed array/dictionary at " .. path)
		end
		seen[v] = nil
		return
	end
	error("Cannot store " .. t .. " in a DataStore at " .. path)
end
local function deep(v)
	if type(v) ~= "table" then
		return v
	end
	local out = {}
	for k, x in v do
		out[k] = deep(x)
	end
	return out
end
local function dsCall()
	local d = rawget(DataStoreService, "_d")
	d.props.__calls += 1
	if d.props.__failNext > 0 then
		d.props.__failNext -= 1
		error("502: API Services rejected request (stub failure)")
	end
end
local KeyInfoT = makeType("DataStoreKeyInfo")
local function keyInfo(entry)
	return setmetatable({ Version = tostring(entry and entry.version or 0), CreatedTime = 0, UpdatedTime = 0,
		GetUserIds = function()
			return entry and entry.userIds or {}
		end,
		GetMetadata = function()
			return {}
		end }, KeyInfoT)
end
local function newStore(name, ordered)
	local data = {}
	local store = newInstance(ordered and "OrderedDataStore" or "DataStore")
	rawget(store, "_d").props.Name = name
	rawget(store, "_d").props.__data = data
	local m = {}
	function m.GetAsync(_, key)
		dsCall()
		local e = data[key]
		return deep(e and e.value), keyInfo(e)
	end
	function m.SetAsync(_, key, value, userIds)
		dsCall()
		checkStorable(value, "value", {})
		local e = data[key] or { version = 0 }
		e.value, e.version, e.userIds = deep(value), e.version + 1, userIds
		data[key] = e
		return tostring(e.version)
	end
	function m.UpdateAsync(_, key, fn)
		dsCall()
		local e = data[key]
		local new, userIds = fn(deep(e and e.value), keyInfo(e))
		if new == nil then
			return deep(e and e.value), keyInfo(e)
		end
		checkStorable(new, "value", {})
		e = e or { version = 0 }
		e.value, e.version, e.userIds = deep(new), e.version + 1, userIds
		data[key] = e
		return deep(new), keyInfo(e)
	end
	function m.IncrementAsync(_, key, delta)
		dsCall()
		local e = data[key] or { version = 0, value = 0 }
		assert(type(e.value) == "number", "IncrementAsync on a non-number")
		e.value += delta or 1
		e.version += 1
		data[key] = e
		return e.value
	end
	function m.RemoveAsync(_, key)
		dsCall()
		local e = data[key]
		data[key] = nil
		return deep(e and e.value), keyInfo(e)
	end
	function m.GetSortedAsync(_, ascending, pageSize, minValue, maxValue)
		dsCall()
		local rows = {}
		for k, e in data do
			local v = e.value
			if (minValue == nil or v >= minValue) and (maxValue == nil or v <= maxValue) then
				table.insert(rows, { key = k, value = v })
			end
		end
		table.sort(rows, function(a, b)
			if a.value == b.value then
				return a.key < b.key
			end
			if ascending then
				return a.value < b.value
			end
			return a.value > b.value
		end)
		local page = 1
		local pages = {}
		pages.IsFinished = #rows <= pageSize
		function pages.GetCurrentPage()
			local out = {}
			for i = (page - 1) * pageSize + 1, math.min(#rows, page * pageSize) do
				table.insert(out, rows[i])
			end
			return out
		end
		function pages.AdvanceToNextPageAsync()
			page += 1
			pages.IsFinished = #rows <= page * pageSize
		end
		return pages
	end
	-- per-store methods via a dedicated class name
	local cls = (ordered and "OrderedDataStore#" or "DataStore#") .. name
	rawget(store, "_d").className = cls
	CLASS_PARENT[cls] = ordered and "OrderedDataStore" or "DataStore"
	CLASS_METHODS[cls] = m
	return store
end
CLASS_METHODS.DataStoreService = {
	GetDataStore = function(_, name, scope)
		local key = "ds:" .. name .. ":" .. tostring(scope or "global")
		stores[key] = stores[key] or newStore(name, false)
		return stores[key]
	end,
	GetOrderedDataStore = function(_, name, scope)
		local key = "ods:" .. name .. ":" .. tostring(scope or "global")
		stores[key] = stores[key] or newStore(name, true)
		return stores[key]
	end,
	GetGlobalDataStore = function(self)
		return self:GetDataStore("__global")
	end,
	GetRequestBudgetForRequestType = function()
		return 100
	end,
}

-- MessagingService
local MessagingService = getService(game, "MessagingService")
local topics = {}
CLASS_METHODS.MessagingService = {
	PublishAsync = function(_, topic, message)
		assert(type(topic) == "string" and #topic <= 80, "bad topic")
		for _, fn in topics[topic] or {} do
			task.spawn(fn, { Data = deep(message), Sent = 1700000000 + __now })
		end
	end,
	SubscribeAsync = function(_, topic, fn)
		topics[topic] = topics[topic] or {}
		table.insert(topics[topic], fn)
		local conn = {}
		function conn.Disconnect()
			for i, f in topics[topic] do
				if f == fn then
					table.remove(topics[topic], i)
				end
			end
		end
		return conn
	end,
}
local _ = MessagingService

-- MemoryStoreService (sorted map + queue, in memory, no expiry handling beyond storage)
local MemoryStoreService = getService(game, "MemoryStoreService")
CLASS_METHODS.MemoryStoreService = {
	GetSortedMap = function(_, name)
		local data = {}
		local map = { Name = name }
		function map.GetAsync(_, key)
			local e = data[key]
			return e and deep(e.value), e and e.sortKey
		end
		function map.SetAsync(_, key, value, _exp, sortKey)
			data[key] = { value = deep(value), sortKey = sortKey }
			return true
		end
		function map.UpdateAsync(_, key, fn, _exp)
			local e = data[key]
			local new, sortKey = fn(e and deep(e.value), e and e.sortKey)
			if new == nil then
				return nil
			end
			data[key] = { value = deep(new), sortKey = sortKey }
			return deep(new)
		end
		function map.RemoveAsync(_, key)
			data[key] = nil
		end
		function map.GetRangeAsync(_, direction, count)
			local rows = {}
			for k, e in data do
				table.insert(rows, { key = k, value = deep(e.value), sortKey = e.sortKey })
			end
			table.sort(rows, function(a, b)
				if direction == Enum.SortDirection.Descending then
					return a.key > b.key
				end
				return a.key < b.key
			end)
			local out = {}
			for i = 1, math.min(count, #rows) do
				out[i] = rows[i]
			end
			return out
		end
		return map
	end,
	GetQueue = function(_, name)
		local items = {}
		local q = { Name = name }
		function q.AddAsync(_, value)
			table.insert(items, deep(value))
		end
		function q.ReadAsync(_, count)
			local out = {}
			for i = 1, math.min(count, #items) do
				out[i] = items[i]
			end
			return out, #out > 0 and tostring(#out) or nil
		end
		function q.RemoveAsync(_, id)
			for _ = 1, tonumber(id) or 0 do
				table.remove(items, 1)
			end
		end
		return q
	end,
}
local _ = MemoryStoreService

-- HttpService (JSON + GUIDs)
local HttpService = getService(game, "HttpService")
local function jsonEncode(v, out)
	local t = typeof(v)
	if t == "nil" then
		table.insert(out, "null")
	elseif t == "boolean" then
		table.insert(out, tostring(v))
	elseif t == "number" then
		if v ~= v or v == math.huge or v == -math.huge then
			error("JSONEncode: cannot encode NaN/inf")
		end
		table.insert(out, v % 1 == 0 and string.format("%d", v) or string.format("%.14g", v))
	elseif t == "string" then
		table.insert(out, '"' .. v:gsub('[%c"\\]', function(c)
			local map = { ['"'] = '\\"', ["\\"] = "\\\\", ["\n"] = "\\n", ["\r"] = "\\r", ["\t"] = "\\t" }
			return map[c] or string.format("\\u%04x", string.byte(c))
		end) .. '"')
	elseif t == "table" then
		if #v > 0 or next(v) == nil then
			table.insert(out, "[")
			for i, x in ipairs(v) do
				if i > 1 then
					table.insert(out, ",")
				end
				jsonEncode(x, out)
			end
			table.insert(out, "]")
		else
			local keys = {}
			for k in v do
				if type(k) ~= "string" then
					error("JSONEncode: object keys must be strings")
				end
				table.insert(keys, k)
			end
			table.sort(keys)
			table.insert(out, "{")
			for i, k in keys do
				if i > 1 then
					table.insert(out, ",")
				end
				jsonEncode(k, out)
				table.insert(out, ":")
				jsonEncode(v[k], out)
			end
			table.insert(out, "}")
		end
	else
		error("JSONEncode: cannot encode " .. t)
	end
end
local function jsonDecode(s)
	local i = 1
	local function ws()
		i = s:find("[^ \t\r\n]", i) or #s + 1
	end
	local value
	local function str()
		local out = {}
		i += 1
		while true do
			local c = s:sub(i, i)
			if c == "" then
				error("JSONDecode: unterminated string")
			elseif c == '"' then
				i += 1
				break
			elseif c == "\\" then
				local e = s:sub(i + 1, i + 1)
				local map = { n = "\n", r = "\r", t = "\t", b = "\b", f = "\f", ['"'] = '"', ["\\"] = "\\", ["/"] = "/" }
				if e == "u" then
					table.insert(out, utf8.char(tonumber(s:sub(i + 2, i + 5), 16)))
					i += 6
				else
					table.insert(out, map[e] or e)
					i += 2
				end
			else
				table.insert(out, c)
				i += 1
			end
		end
		return table.concat(out)
	end
	function value()
		ws()
		local c = s:sub(i, i)
		if c == "{" then
			local obj = {}
			i += 1
			ws()
			if s:sub(i, i) == "}" then
				i += 1
				return obj
			end
			while true do
				ws()
				local k = str()
				ws()
				assert(s:sub(i, i) == ":", "JSONDecode: expected ':'")
				i += 1
				obj[k] = value()
				ws()
				local d = s:sub(i, i)
				i += 1
				if d == "}" then
					return obj
				end
				assert(d == ",", "JSONDecode: expected ','")
			end
		elseif c == "[" then
			local arr = {}
			i += 1
			ws()
			if s:sub(i, i) == "]" then
				i += 1
				return arr
			end
			while true do
				table.insert(arr, value())
				ws()
				local d = s:sub(i, i)
				i += 1
				if d == "]" then
					return arr
				end
				assert(d == ",", "JSONDecode: expected ','")
			end
		elseif c == '"' then
			return str()
		elseif s:sub(i, i + 3) == "true" then
			i += 4
			return true
		elseif s:sub(i, i + 4) == "false" then
			i += 5
			return false
		elseif s:sub(i, i + 3) == "null" then
			i += 4
			return nil
		end
		local num = s:match("^-?%d+%.?%d*[eE]?[-+]?%d*", i)
		if not num or num == "" then
			error("JSONDecode: unexpected character at " .. i)
		end
		i += #num
		return tonumber(num)
	end
	local result = value()
	ws()
	if i <= #s then
		error("JSONDecode: trailing characters")
	end
	return result
end
local guid = 0
CLASS_METHODS.HttpService = {
	JSONEncode = function(_, v)
		local out = {}
		jsonEncode(v, out)
		return table.concat(out)
	end,
	JSONDecode = function(_, s)
		return jsonDecode(s)
	end,
	GenerateGUID = function(_, braces)
		guid += 1
		local g = string.format("00000000-0000-4000-8000-%012d", guid)
		return braces == false and g or "{" .. g .. "}"
	end,
	UrlEncode = function(_, s)
		return (s:gsub("[^%w%-_%.~]", function(c)
			return string.format("%%%02X", string.byte(c))
		end))
	end,
	GetAsync = function()
		error("HttpService requests are not available in the stubs")
	end,
	PostAsync = function()
		error("HttpService requests are not available in the stubs")
	end,
	RequestAsync = function()
		error("HttpService requests are not available in the stubs")
	end,
}
local _ = HttpService

-- TweenService: Play applies the goals after TweenInfo.Time of virtual time, then fires Completed.
CLASS_METHODS.TweenService = {
	Create = function(_, instance, info, goals)
		assert(typeof(instance) == "Instance", "TweenService:Create needs an Instance")
		assert(typeof(info) == "TweenInfo", "TweenService:Create needs a TweenInfo")
		local tween = newInstance("Tween")
		local d = rawget(tween, "_d")
		d.props.Instance = instance
		d.props.TweenInfo = info
		d.props.PlaybackState = Enum.PlaybackState.Begin
		d.props.__goals = goals
		return tween
	end,
	GetValue = function(_, alpha)
		return alpha
	end,
}
CLASS_METHODS.Tween = {
	Play = function(self)
		local d = rawget(self, "_d")
		d.props.PlaybackState = Enum.PlaybackState.Playing
		d.props.__plays = (d.props.__plays or 0) + 1
		local token = {}
		d.token = token
		local info = d.props.TweenInfo
		task.delay(info.Time + info.DelayTime, function()
			if d.token ~= token then
				return
			end
			for k, v in d.props.__goals do
				d.props.Instance[k] = v
			end
			d.props.PlaybackState = Enum.PlaybackState.Completed
			self.Completed:Fire(Enum.PlaybackState.Completed)
		end)
	end,
	Cancel = function(self)
		local d = rawget(self, "_d")
		d.token = nil
		d.props.PlaybackState = Enum.PlaybackState.Cancelled
		self.Completed:Fire(Enum.PlaybackState.Cancelled)
	end,
	Pause = function(self)
		local d = rawget(self, "_d")
		d.token = nil
		d.props.PlaybackState = Enum.PlaybackState.Paused
	end,
}

-- CollectionService
CLASS_METHODS.CollectionService = {
	AddTag = function(_, inst, tag)
		inst:AddTag(tag)
	end,
	RemoveTag = function(_, inst, tag)
		inst:RemoveTag(tag)
	end,
	HasTag = function(_, inst, tag)
		return inst:HasTag(tag)
	end,
	GetTags = function(_, inst)
		return inst:GetTags()
	end,
	GetTagged = function(_, tag)
		local out = {}
		for inst in tagIndex[tag] or {} do
			table.insert(out, inst)
		end
		table.sort(out, function(a, b)
			return rawget(a, "_d").id < rawget(b, "_d").id
		end)
		return out
	end,
	GetInstanceAddedSignal = function(_, tag)
		return tagSignal(tagAdded, tag)
	end,
	GetInstanceRemovedSignal = function(_, tag)
		return tagSignal(tagRemoved, tag)
	end,
	GetAllTags = function()
		local out = {}
		for t in tagIndex do
			table.insert(out, t)
		end
		return out
	end,
}

-- PathfindingService: straight-line paths split every 4 studs; status configurable.
local PathfindingService = getService(game, "PathfindingService")
rawget(PathfindingService, "_d").props.__status = nil
CLASS_METHODS.PathfindingService = {
	CreatePath = function(_, params)
		local path = newInstance("Path")
		local d = rawget(path, "_d")
		d.props.__params = params
		d.props.Status = Enum.PathStatus.NoPath
		d.props.__waypoints = {}
		return path
	end,
	FindPathAsync = function(self, a, b)
		local p = self:CreatePath()
		p:ComputeAsync(a, b)
		return p
	end,
}
CLASS_METHODS.Path = {
	ComputeAsync = function(self, start, goal)
		local d = rawget(self, "_d")
		local status = PathfindingService.__status or Enum.PathStatus.Success
		d.props.Status = status
		d.props.__waypoints = {}
		if status == Enum.PathStatus.Success then
			local dist = (goal - start).Magnitude
			local steps = math.max(1, math.ceil(dist / 4))
			for i = 0, steps do
				table.insert(d.props.__waypoints, PathWaypoint.new(start:Lerp(goal, i / steps), Enum.PathWaypointAction.Walk))
			end
		end
	end,
	GetWaypoints = function(self)
		return table.clone(rawget(self, "_d").props.__waypoints)
	end,
	CheckOcclusionAsync = function()
		return -1
	end,
}

-- TextService / TextChatService
CLASS_METHODS.TextService = {
	FilterStringAsync = function(_, text, userId)
		assert(type(text) == "string" and type(userId) == "number", "FilterStringAsync(text, userId)")
		local res = newInstance("TextFilterResult")
		local filteredText = text:gsub("[Bb]adword", "#######")
		local give = function()
			return filteredText
		end
		local props = rawget(res, "_d").props
		props.GetNonChatStringForBroadcastAsync = give
		props.GetNonChatStringForUserAsync = give
		props.GetChatForUserAsync = give
		return res
	end,
	GetTextSize = function(_, text, size)
		return Vector2.new(#text * size * 0.5, size)
	end,
}

-- MarketplaceService / BadgeService / TeleportService / Debris / misc
local MarketplaceService = getService(game, "MarketplaceService")
rawget(MarketplaceService, "_d").props.__owned = {}
rawget(MarketplaceService, "_d").props.__prompts = {}
CLASS_METHODS.MarketplaceService = {
	UserOwnsGamePassAsync = function(self, userId, passId)
		local owned = rawget(self, "_d").props.__owned[userId]
		return owned ~= nil and owned[passId] == true
	end,
	PlayerOwnsAsset = function()
		return false
	end,
	PromptGamePassPurchase = function(self, player, id)
		table.insert(rawget(self, "_d").props.__prompts, { player, "gamepass", id })
	end,
	PromptProductPurchase = function(self, player, id)
		table.insert(rawget(self, "_d").props.__prompts, { player, "product", id })
	end,
	PromptPurchase = function(self, player, id)
		table.insert(rawget(self, "_d").props.__prompts, { player, "asset", id })
	end,
	GetProductInfo = function(_, id)
		return { Name = "Product " .. tostring(id), PriceInRobux = 10, IsForSale = true }
	end,
}
local BadgeService = getService(game, "BadgeService")
rawget(BadgeService, "_d").props.__awarded = {}
CLASS_METHODS.BadgeService = {
	AwardBadge = function(self, userId, badgeId)
		local a = rawget(self, "_d").props.__awarded
		a[userId] = a[userId] or {}
		local already = a[userId][badgeId] == true
		a[userId][badgeId] = true
		return not already
	end,
	AwardBadgeAsync = function(self, userId, badgeId)
		local a = rawget(self, "_d").props.__awarded
		a[userId] = a[userId] or {}
		local already = a[userId][badgeId] == true
		a[userId][badgeId] = true
		return not already
	end,
	UserHasBadgeAsync = function(self, userId, badgeId)
		local a = rawget(self, "_d").props.__awarded[userId]
		return a ~= nil and a[badgeId] == true
	end,
	GetBadgeInfoAsync = function()
		return { IsEnabled = true, Name = "Badge" }
	end,
}
local TeleportService = getService(game, "TeleportService")
rawget(TeleportService, "_d").props.__teleports = {}
CLASS_METHODS.TeleportService = {
	TeleportAsync = function(self, placeId, players, options)
		table.insert(rawget(self, "_d").props.__teleports, { placeId, players, options })
		return { PrivateServerId = "", ReservedServerAccessCode = "" }
	end,
	ReserveServer = function()
		return "access-code", "private-id"
	end,
}
CLASS_METHODS.TeleportOptions = {
	SetTeleportData = function(self, data)
		rawget(self, "_d").props.__data = data
	end,
	GetTeleportData = function(self)
		return rawget(self, "_d").props.__data
	end,
}
CLASS_METHODS.Debris = {
	AddItem = function(_, inst, lifetime)
		task.delay(lifetime or 10, function()
			inst:Destroy()
		end)
	end,
}
CLASS_METHODS.UserInputService = {
	GetLastInputType = function()
		return Enum.UserInputType.MouseButton1
	end,
	IsKeyDown = function()
		return false
	end,
	GetMouseLocation = function()
		return Vector2.new(640, 360)
	end,
	GetFocusedTextBox = function()
		return nil
	end,
	IsGamepadButtonDown = function()
		return false
	end,
	GetConnectedGamepads = function()
		return {}
	end,
}
local ContextActionService = getService(game, "ContextActionService")
rawget(ContextActionService, "_d").props.__bound = {}
CLASS_METHODS.ContextActionService = {
	BindAction = function(self, name, fn, _touch, ...)
		rawget(self, "_d").props.__bound[name] = { fn = fn, inputs = { ... } }
	end,
	BindActionAtPriority = function(self, name, fn, _touch, _priority, ...)
		rawget(self, "_d").props.__bound[name] = { fn = fn, inputs = { ... } }
	end,
	UnbindAction = function(self, name)
		rawget(self, "_d").props.__bound[name] = nil
	end,
	SetTitle = function() end,
	SetPosition = function() end,
	GetButton = function()
		return nil
	end,
}
CLASS_METHODS.StarterGui = {
	SetCore = function() end,
	SetCoreGuiEnabled = function() end,
	GetCore = function()
		return nil
	end,
}
CLASS_METHODS.PhysicsService = {
	RegisterCollisionGroup = function(self, name)
		local d = rawget(self, "_d")
		d.props.__groups = d.props.__groups or {}
		d.props.__groups[name] = d.props.__groups[name] or {}
	end,
	CollisionGroupSetCollidable = function(self, a, b, collide)
		local d = rawget(self, "_d")
		d.props.__pairs = d.props.__pairs or {}
		d.props.__pairs[a .. "|" .. b] = collide
		d.props.__pairs[b .. "|" .. a] = collide
	end,
	CollisionGroupsAreCollidable = function(self, a, b)
		local p = rawget(self, "_d").props.__pairs
		if p and p[a .. "|" .. b] ~= nil then
			return p[a .. "|" .. b]
		end
		return true
	end,
	IsCollisionGroupRegistered = function(self, name)
		local g = rawget(self, "_d").props.__groups
		return name == "Default" or (g ~= nil and g[name] ~= nil)
	end,
}
CLASS_METHODS.GuiService = {
	GetGuiInset = function()
		return Vector2.new(0, 58), Vector2.zero
	end,
}
CLASS_METHODS.ReplicatedFirst = {
	RemoveDefaultLoadingScreen = function() end,
}
CLASS_METHODS.ContentProvider = {
	PreloadAsync = function() end,
}
CLASS_METHODS.LocalizationService = {
	GetTranslatorForPlayerAsync = function()
		return { Translate = function(_, _ctx, text)
			return text
		end, FormatByKey = function(_, key)
			return key
		end }
	end,
}
CLASS_METHODS.PolicyService = {
	GetPolicyInfoForPlayerAsync = function()
		return { ArePaidRandomItemsRestricted = false, AllowedExternalLinkReferences = {}, IsSubjectToChinaPolicies = false }
	end,
}
CLASS_METHODS.GroupService = {
	GetGroupsAsync = function()
		return {}
	end,
}
CLASS_METHODS.AnalyticsService = {
	LogEconomyEvent = function() end,
	LogCustomEvent = function() end,
	LogProgressionEvent = function() end,
	LogOnboardingFunnelStepEvent = function() end,
	LogFunnelStepEvent = function() end,
}
CLASS_METHODS.SoundService = {
	PlayLocalSound = function(_, sound)
		sound:Play()
	end,
}
CLASS_METHODS.Teams = {
	GetTeams = function(self)
		local out = {}
		for _, c in self:GetChildren() do
			if c:IsA("Team") then
				table.insert(out, c)
			end
		end
		return out
	end,
}
CLASS_METHODS.Team = {
	GetPlayers = function(self)
		local out = {}
		for _, p in __players do
			if p.Team == self then
				table.insert(out, p)
			end
		end
		return out
	end,
}
CLASS_METHODS.ScriptContext = {}

-- leaderstats-style helpers some tests use
function __leaderstat(player, name)
	local ls = player:FindFirstChild("leaderstats")
	local v = ls and ls:FindFirstChild(name)
	return v and v.Value
end
