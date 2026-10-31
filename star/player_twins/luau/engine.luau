-- Player Twins engine doubles: a deliberately small, deterministic stand-in for the Roblox server
-- engine, enough to run a game's server-side Luau headless. NOT Roblox: no physics, replication,
-- rendering or real DataStores. Unknown classes, services and members fail loudly.
local Engine = {}

local WAIT = {} -- yield marker for task.wait / Signal:Wait

---------------------------------------------------------------- deep copy for DataStore / network
local function deepCopy(v, depth)
	depth = depth or 0
	if type(v) ~= "table" then
		return v
	end
	if depth > 32 then
		error("value nests too deeply", 0)
	end
	local out = {}
	for k, x in v do
		out[deepCopy(k, depth + 1)] = deepCopy(x, depth + 1)
	end
	return out
end

local function storable(v, depth)
	local t = type(v)
	if t == "function" or t == "thread" or t == "userdata" then
		return false, "cannot store " .. t
	end
	if t == "table" then
		if rawget(v, "__d") then
			return false, "cannot store Instance"
		end
		if (depth or 0) > 32 then
			return false, "nests too deeply"
		end
		for k, x in v do
			local ok, why = storable(x, (depth or 0) + 1)
			if not ok then
				return false, why
			end
			if type(k) ~= "string" and type(k) ~= "number" then
				return false, "table key of type " .. type(k)
			end
		end
	end
	if t == "number" and v ~= v then
		return false, "NaN"
	end
	return true
end

---------------------------------------------------------------- PRNG (Roblox Random double)
local function newRandomClass()
	local Random = {}
	Random.__index = Random
	function Random.new(seed)
		local s = math.floor(tonumber(seed) or 1) % 2147483647
		if s <= 0 then
			s = s + 2147483646
		end
		return setmetatable({ s = s }, Random)
	end
	function Random:_next()
		self.s = (self.s * 48271) % 2147483647
		return self.s / 2147483647
	end
	function Random:NextNumber(a, b)
		a, b = a or 0, b or 1
		return a + (b - a) * self:_next()
	end
	function Random:NextInteger(a, b)
		return math.floor(a + (b - a + 1) * self:_next())
	end
	return Random
end

---------------------------------------------------------------- small datatypes
local Vector3 = {}
Vector3.__index = Vector3
Vector3.__type = "Vector3"
function Vector3.new(x, y, z)
	return setmetatable({ X = x or 0, Y = y or 0, Z = z or 0 }, Vector3)
end
Vector3.__add = function(a, b)
	return Vector3.new(a.X + b.X, a.Y + b.Y, a.Z + b.Z)
end
Vector3.__sub = function(a, b)
	return Vector3.new(a.X - b.X, a.Y - b.Y, a.Z - b.Z)
end
Vector3.__mul = function(a, b)
	if type(a) == "number" then
		a, b = b, a
	end
	if type(b) == "number" then
		return Vector3.new(a.X * b, a.Y * b, a.Z * b)
	end
	return Vector3.new(a.X * b.X, a.Y * b.Y, a.Z * b.Z)
end
Vector3.__eq = function(a, b)
	return a.X == b.X and a.Y == b.Y and a.Z == b.Z
end
Vector3.__index = function(v, k)
	if k == "Magnitude" then
		return math.sqrt(v.X * v.X + v.Y * v.Y + v.Z * v.Z)
	elseif k == "Unit" then
		local m = math.sqrt(v.X * v.X + v.Y * v.Y + v.Z * v.Z)
		return Vector3.new(v.X / m, v.Y / m, v.Z / m)
	end
	return rawget(Vector3, k)
end
Vector3.zero = Vector3.new(0, 0, 0)
Vector3.one = Vector3.new(1, 1, 1)

local CFrame = {}
CFrame.__index = CFrame
CFrame.__type = "CFrame"
function CFrame.new(x, y, z)
	if type(x) == "table" then
		return setmetatable({ Position = x }, CFrame)
	end
	return setmetatable({ Position = Vector3.new(x, y, z) }, CFrame)
end

local Color3 = { __type = "Color3" }
Color3.__index = Color3
function Color3.new(r, g, b)
	return setmetatable({ R = r or 0, G = g or 0, B = b or 0 }, Color3)
end
function Color3.fromRGB(r, g, b)
	return Color3.new((r or 0) / 255, (g or 0) / 255, (b or 0) / 255)
end

local UDim2 = { __type = "UDim2" }
UDim2.__index = UDim2
function UDim2.new(a, b, c, d)
	return setmetatable({ X = { Scale = a, Offset = b }, Y = { Scale = c, Offset = d } }, UDim2)
end
function UDim2.fromScale(a, b)
	return UDim2.new(a, 0, b, 0)
end
function UDim2.fromOffset(a, b)
	return UDim2.new(0, a, 0, b)
end

local Vector2 = { __type = "Vector2" }
Vector2.__index = Vector2
function Vector2.new(x, y)
	return setmetatable({ X = x or 0, Y = y or 0 }, Vector2)
end

local Enum = setmetatable({}, {
	__index = function(_, group)
		return setmetatable({}, {
			__index = function(_, item)
				return { __type = "EnumItem", EnumType = group, Name = item, Value = 0 }
			end,
		})
	end,
})

---------------------------------------------------------------- class table
local SUPER = {
	Instance = nil,
	Folder = "Instance",
	Model = "PVInstance",
	PVInstance = "Instance",
	BasePart = "PVInstance",
	Part = "BasePart",
	ValueBase = "Instance",
	IntValue = "ValueBase",
	NumberValue = "ValueBase",
	StringValue = "ValueBase",
	BoolValue = "ValueBase",
	ObjectValue = "ValueBase",
	RemoteEvent = "BaseRemoteEvent",
	UnreliableRemoteEvent = "BaseRemoteEvent",
	BaseRemoteEvent = "Instance",
	RemoteFunction = "Instance",
	BindableEvent = "Instance",
	BindableFunction = "Instance",
	Configuration = "Instance",
	LuaSourceContainer = "Instance",
	BaseScript = "LuaSourceContainer",
	Script = "BaseScript",
	ModuleScript = "LuaSourceContainer",
	Player = "Instance",
	Players = "Instance",
	DataModel = "ServiceProvider",
	ServiceProvider = "Instance",
	Workspace = "WorldRoot",
	WorldRoot = "Model",
	ReplicatedStorage = "Instance",
	ServerScriptService = "Instance",
	ServerStorage = "Instance",
	RunService = "Instance",
	DataStoreService = "Instance",
	TweenService = "Instance",
	HttpService = "Instance",
	Lighting = "Instance",
	StarterGui = "Instance",
	StarterPlayer = "Instance",
	Tween = "TweenBase",
	TweenBase = "Instance",
}

local CREATABLE = {
	Folder = true, Model = true, Part = true, IntValue = true, NumberValue = true, StringValue = true,
	BoolValue = true, ObjectValue = true, RemoteEvent = true, UnreliableRemoteEvent = true,
	RemoteFunction = true, BindableEvent = true, BindableFunction = true, Configuration = true,
}

local COMMON_PROPS = { Name = true, Parent = true, Archivable = true }
local CLASS_PROPS = {
	ValueBase = { Value = true },
	BasePart = { Position = true, Size = true, Anchored = true, CanCollide = true, CanTouch = true,
		Transparency = true, Color = true, Material = true, CFrame = true },
	Player = { UserId = true, DisplayName = true, Character = true, AccountAge = true, Team = true },
	Players = { MaxPlayers = true, LocalPlayer = true },
	RemoteFunction = { OnServerInvoke = true, OnClientInvoke = true },
	BindableFunction = { OnInvoke = true },
	BaseScript = { Disabled = true, Enabled = true },
	DataModel = { PlaceId = true, JobId = true, CreatorId = true, GameId = true, PlaceVersion = true },
	Model = { PrimaryPart = true },
	Tween = { PlaybackState = true },
}
local CLASS_EVENTS = {
	Instance = { ChildAdded = true, ChildRemoved = true, Changed = true, AncestryChanged = true,
		Destroying = true, AttributeChanged = true, DescendantAdded = true, DescendantRemoving = true },
	BaseRemoteEvent = { OnServerEvent = true, OnClientEvent = true },
	BindableEvent = { Event = true },
	Players = { PlayerAdded = true, PlayerRemoving = true },
	Player = { CharacterAdded = true, CharacterRemoving = true, Chatted = true },
	RunService = { Heartbeat = true, Stepped = true, PostSimulation = true, PreSimulation = true,
		RenderStepped = true },
	BasePart = { Touched = true, TouchEnded = true },
	Tween = { Completed = true },
}

local function lineage(className)
	local list = {}
	local c = className
	while c do
		table.insert(list, c)
		c = SUPER[c]
		if c == nil and list[#list] ~= "Instance" then
			table.insert(list, "Instance")
		end
	end
	return list
end

local LINEAGE = setmetatable({}, {
	__index = function(t, k)
		local l = lineage(k)
		rawset(t, k, l)
		return l
	end,
})

local function classHas(className, tbl, key)
	for _, c in LINEAGE[className] do
		local set = tbl[c]
		if set and set[key] then
			return true
		end
	end
	return false
end

---------------------------------------------------------------- world
function Engine.newWorld(opts)
	opts = opts or {}
	local W = {
		now = 0,
		tickDt = opts.tickDt or 1,
		errors = {}, -- message -> {count, first}
		errorCount = 0,
		warnings = {},
		waiting = {},
		deferred = {},
		modules = {},
		closeHooks = {},
		clients = {},
		services = {},
		dsBackend = opts.dsBackend or {},
		dsFailRate = opts.dsFailRate or 0,
		dsCalls = 0,
		dsFailures = 0,
		steps = 0, -- engine steps (Heartbeats) simulated
		rand = opts.rand or math.random,
		epoch = opts.epoch or 1790000000,
		G = {},
		shared = {},
	}

	local function recordError(msg)
		msg = tostring(msg)
		W.errorCount += 1
		local e = W.errors[msg]
		if e then
			e.count += 1
		else
			W.errors[msg] = { count = 1, t = W.now }
		end
	end
	W.recordError = recordError

	local function warnOnce(kind, msg)
		local key = kind .. ": " .. msg
		local w = W.warnings[key]
		if w then
			w.count += 1
		else
			W.warnings[key] = { count = 1, t = W.now }
		end
	end
	W.warn = warnOnce

	---------------------------------------------------------------- scheduler
	local function resume(co, ...)
		local ok, a, b = coroutine.resume(co, ...)
		if not ok then
			recordError(debug.traceback(co, tostring(a)))
			return
		end
		if coroutine.status(co) == "dead" then
			return
		end
		if a == WAIT then
			if type(b) == "table" then -- signal wait
				table.insert(b, co)
			else
				table.insert(W.waiting, { co = co, at = W.now + math.max(b or 0, 0), from = W.now })
			end
		end
		-- other yields belong to coroutines the game created itself
	end
	W.resume = resume

	local function spawnThread(fn, ...)
		local co = type(fn) == "thread" and fn or coroutine.create(fn)
		resume(co, ...)
		return co
	end
	W.spawn = spawnThread

	local task = {}
	function task.wait(t)
		if not coroutine.isyieldable() then
			error("task.wait called outside a scheduler thread (mock)", 2)
		end
		local start = W.now
		coroutine.yield(WAIT, t or 0)
		return W.now - start
	end
	function task.spawn(fn, ...)
		return spawnThread(fn, ...)
	end
	function task.defer(fn, ...)
		local co = type(fn) == "thread" and fn or coroutine.create(fn)
		table.insert(W.deferred, { co = co, args = table.pack(...) })
		return co
	end
	function task.delay(t, fn, ...)
		local co = type(fn) == "thread" and fn or coroutine.create(fn)
		local args = table.pack(...)
		table.insert(W.waiting, { co = co, at = W.now + (t or 0), args = args, fresh = true })
		return co
	end
	function task.cancel(co)
		for i = #W.waiting, 1, -1 do
			if W.waiting[i].co == co then
				table.remove(W.waiting, i)
			end
		end
		pcall(coroutine.close, co)
	end
	task.synchronize = function() end
	task.desynchronize = function() end
	W.task = task

	local function runDeferred()
		local guard = 0
		while #W.deferred > 0 do
			guard += 1
			if guard > 10000 then
				recordError("task.defer re-entrancy limit exceeded (mock)")
				W.deferred = {}
				return
			end
			local d = table.remove(W.deferred, 1)
			resume(d.co, table.unpack(d.args, 1, d.args.n))
		end
	end
	W.runDeferred = runDeferred

	local function runDue()
		local again = true
		local guard = 0
		while again do
			again = false
			guard += 1
			if guard > 1000 then
				recordError("scheduler wake-up loop limit exceeded (mock)")
				return
			end
			local due = {}
			for i = #W.waiting, 1, -1 do
				local w = W.waiting[i]
				if w.at <= W.now + 1e-9 then
					table.insert(due, w)
					table.remove(W.waiting, i)
				end
			end
			if #due > 0 then
				again = true
				table.sort(due, function(x, y)
					return x.at < y.at
				end)
				for _, w in due do
					if w.fresh then
						resume(w.co, table.unpack(w.args, 1, w.args.n))
					else
						resume(w.co, W.now - (w.from or W.now))
					end
				end
			end
		end
		runDeferred()
	end
	W.runDue = runDue

	---------------------------------------------------------------- signals
	local Signal = {}
	Signal.__index = Signal
	local function newSignal(name)
		return setmetatable({ name = name, conns = {}, waiters = {} }, Signal)
	end
	W.newSignal = newSignal
	function Signal:Connect(fn)
		if type(fn) ~= "function" then
			error("Attempt to connect failed: Passed value is not a function", 2)
		end
		local c = { Connected = true, fn = fn }
		local sig = self
		function c.Disconnect(conn)
			conn = conn or c
			conn.Connected = false
			for i, x in sig.conns do
				if x == conn then
					table.remove(sig.conns, i)
					break
				end
			end
		end
		table.insert(self.conns, c)
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
		if not coroutine.isyieldable() then
			error("Signal:Wait called outside a scheduler thread (mock)", 2)
		end
		return coroutine.yield(WAIT, self.waiters)
	end
	function Signal:ConnectParallel(fn)
		return self:Connect(fn)
	end
	function Signal:_fire(...)
		if #self.conns > 0 then
			local list = table.clone(self.conns)
			for _, c in list do
				if c.Connected then
					spawnThread(c.fn, ...)
				end
			end
		end
		if #self.waiters > 0 then
			local ws = self.waiters
			self.waiters = {}
			for _, co in ws do
				resume(co, ...)
			end
		end
	end

	---------------------------------------------------------------- instances
	local Methods = {}
	local InstanceMT = {}
	W.InstanceMT = InstanceMT

	local function isInstance(v)
		return type(v) == "table" and getmetatable(v) == InstanceMT
	end
	W.isInstance = isInstance

	local function newInstance(className, props)
		local d = {
			ClassName = className,
			props = { Name = className, Archivable = true },
			children = {},
			attrs = {},
			events = {},
			propSignals = {},
			attrSignals = {},
			destroyed = false,
		}
		if classHas(className, CLASS_PROPS, "Value") then
			if className == "StringValue" then
				d.props.Value = ""
			elseif className == "BoolValue" then
				d.props.Value = false
			elseif className ~= "ObjectValue" then
				d.props.Value = 0
			end
		end
		local inst = setmetatable({ __d = d }, InstanceMT)
		if props then
			for k, v in props do
				d.props[k] = v
			end
		end
		return inst
	end
	W.newInstance = newInstance

	local function event(inst, name)
		local d = rawget(inst, "__d")
		local s = d.events[name]
		if not s then
			s = newSignal(name)
			d.events[name] = s
		end
		return s
	end
	W.event = event

	local function fireEvent(inst, name, ...)
		local s = rawget(inst, "__d").events[name]
		if s then
			s:_fire(...)
		end
	end
	W.fireEvent = fireEvent

	local function setParent(inst, parent)
		local d = rawget(inst, "__d")
		if d.destroyed then
			error("The Parent property of " .. tostring(d.props.Name) .. " is locked", 3)
		end
		if parent ~= nil and not isInstance(parent) then
			error("Parent must be an Instance or nil", 3)
		end
		local old = d.props.Parent
		if old == parent then
			return
		end
		local p = parent
		while p do
			if p == inst then
				error("Attempt to set parent of " .. d.props.Name .. " to itself or a descendant", 3)
			end
			p = rawget(p, "__d").props.Parent
		end
		if old then
			local oc = rawget(old, "__d").children
			for i, c in oc do
				if c == inst then
					table.remove(oc, i)
					break
				end
			end
		end
		d.props.Parent = parent
		if parent then
			table.insert(rawget(parent, "__d").children, inst)
		end
		if old then
			fireEvent(old, "ChildRemoved", inst)
		end
		if parent then
			fireEvent(parent, "ChildAdded", inst)
			local a = parent
			while a do
				fireEvent(a, "DescendantAdded", inst)
				a = rawget(a, "__d").props.Parent
			end
		end
		fireEvent(inst, "AncestryChanged", inst, parent)
	end

	local function coerceValue(className, v)
		if className == "IntValue" then
			if type(v) ~= "number" then
				error("IntValue.Value expects a number, got " .. type(v), 3)
			end
			if v ~= v then
				return 0
			end
			if v >= 9.2233720368547758e18 then
				return 9.2233720368547758e18
			elseif v <= -9.2233720368547758e18 then
				return -9.2233720368547758e18
			end
			return v >= 0 and math.floor(v) or math.ceil(v)
		elseif className == "NumberValue" then
			if type(v) ~= "number" then
				error("NumberValue.Value expects a number, got " .. type(v), 3)
			end
		elseif className == "StringValue" then
			return tostring(v)
		elseif className == "BoolValue" then
			return v and true or false
		end
		return v
	end

	InstanceMT.__index = function(self, k)
		local d = rawget(self, "__d")
		local v = d.props[k]
		if v ~= nil then
			return v
		end
		if k == "ClassName" then
			return d.ClassName
		end
		local m = Methods[d.ClassName .. "." .. k] or Methods[k]
		if m then
			return m
		end
		for _, c in LINEAGE[d.ClassName] do
			local cm = Methods[c .. "." .. k]
			if cm then
				return cm
			end
		end
		if classHas(d.ClassName, CLASS_EVENTS, k) then
			return event(self, k)
		end
		for _, c in d.children do
			if rawget(c, "__d").props.Name == k then
				return c
			end
		end
		if COMMON_PROPS[k] or classHas(d.ClassName, CLASS_PROPS, k) then
			return nil
		end
		error(tostring(k) .. " is not a valid member of " .. d.ClassName .. ' "' .. tostring(d.props.Name) .. '"', 2)
	end

	InstanceMT.__newindex = function(self, k, v)
		local d = rawget(self, "__d")
		if k == "Parent" then
			setParent(self, v)
			return
		end
		if not (COMMON_PROPS[k] or classHas(d.ClassName, CLASS_PROPS, k)) then
			error(tostring(k) .. " is not a valid member of " .. d.ClassName .. " (or not supported by the mock)", 2)
		end
		if k == "Value" then
			v = coerceValue(d.ClassName, v)
		end
		if d.props[k] == v then
			return
		end
		d.props[k] = v
		if k == "Value" then
			fireEvent(self, "Changed", v)
		else
			fireEvent(self, "Changed", k)
		end
		local ps = d.propSignals[k]
		if ps then
			ps:_fire()
		end
	end

	InstanceMT.__tostring = function(self)
		return tostring(rawget(self, "__d").props.Name)
	end

	function Methods.IsA(self, name)
		for _, c in LINEAGE[rawget(self, "__d").ClassName] do
			if c == name then
				return true
			end
		end
		return false
	end
	function Methods.GetChildren(self)
		return table.clone(rawget(self, "__d").children)
	end
	function Methods.GetDescendants(self)
		local out = {}
		local function walk(i)
			for _, c in rawget(i, "__d").children do
				table.insert(out, c)
				walk(c)
			end
		end
		walk(self)
		return out
	end
	function Methods.FindFirstChild(self, name, recursive)
		for _, c in rawget(self, "__d").children do
			if rawget(c, "__d").props.Name == name then
				return c
			end
		end
		if recursive then
			for _, c in rawget(self, "__d").children do
				local f = Methods.FindFirstChild(c, name, true)
				if f then
					return f
				end
			end
		end
		return nil
	end
	function Methods.FindFirstChildOfClass(self, cls)
		for _, c in rawget(self, "__d").children do
			if rawget(c, "__d").ClassName == cls then
				return c
			end
		end
		return nil
	end
	function Methods.FindFirstChildWhichIsA(self, cls, recursive)
		for _, c in (recursive and Methods.GetDescendants(self) or rawget(self, "__d").children) do
			if Methods.IsA(c, cls) then
				return c
			end
		end
		return nil
	end
	function Methods.FindFirstAncestor(self, name)
		local p = rawget(self, "__d").props.Parent
		while p do
			if rawget(p, "__d").props.Name == name then
				return p
			end
			p = rawget(p, "__d").props.Parent
		end
		return nil
	end
	function Methods.FindFirstAncestorWhichIsA(self, cls)
		local p = rawget(self, "__d").props.Parent
		while p do
			if Methods.IsA(p, cls) then
				return p
			end
			p = rawget(p, "__d").props.Parent
		end
		return nil
	end
	function Methods.IsDescendantOf(self, other)
		local p = rawget(self, "__d").props.Parent
		while p do
			if p == other then
				return true
			end
			p = rawget(p, "__d").props.Parent
		end
		return false
	end
	function Methods.IsAncestorOf(self, other)
		return Methods.IsDescendantOf(other, self)
	end
	function Methods.WaitForChild(self, name, timeout)
		local found = Methods.FindFirstChild(self, name)
		if found then
			return found
		end
		if not coroutine.isyieldable() then
			error("WaitForChild(" .. tostring(name) .. ") would yield outside a scheduler thread (mock)", 2)
		end
		local limit = timeout or 5
		local waited = 0
		while waited < limit do
			waited += task.wait(W.tickDt)
			found = Methods.FindFirstChild(self, name)
			if found then
				return found
			end
		end
		if not timeout then
			warnOnce("WaitForChild", "infinite yield possible on " .. Methods.GetFullName(self) .. ":WaitForChild(\"" .. tostring(name) .. "\")")
			while true do
				task.wait(W.tickDt * 5)
				found = Methods.FindFirstChild(self, name)
				if found then
					return found
				end
			end
		end
		return nil
	end
	function Methods.GetFullName(self)
		local parts = {}
		local i = self
		while i and rawget(i, "__d").ClassName ~= "DataModel" do
			table.insert(parts, 1, rawget(i, "__d").props.Name)
			i = rawget(i, "__d").props.Parent
		end
		return table.concat(parts, ".")
	end
	function Methods.Destroy(self)
		local d = rawget(self, "__d")
		if d.destroyed then
			return
		end
		fireEvent(self, "Destroying")
		for _, c in table.clone(d.children) do
			Methods.Destroy(c)
		end
		if d.props.Parent then
			setParent(self, nil)
		end
		d.destroyed = true
		for _, s in d.events do
			for _, c in table.clone(s.conns) do
				c.Connected = false
			end
			s.conns = {}
		end
	end
	function Methods.ClearAllChildren(self)
		for _, c in table.clone(rawget(self, "__d").children) do
			Methods.Destroy(c)
		end
	end
	function Methods.Clone(self)
		local d = rawget(self, "__d")
		if not d.props.Archivable then
			return nil
		end
		local props = table.clone(d.props)
		props.Parent = nil
		local c = newInstance(d.ClassName, props)
		rawget(c, "__d").attrs = table.clone(d.attrs)
		for _, ch in d.children do
			local cc = Methods.Clone(ch)
			if cc then
				setParent(cc, c)
			end
		end
		return c
	end
	function Methods.GetAttribute(self, name)
		return rawget(self, "__d").attrs[name]
	end
	function Methods.GetAttributes(self)
		return table.clone(rawget(self, "__d").attrs)
	end
	function Methods.SetAttribute(self, name, value)
		local t = type(value)
		if t == "table" and not (getmetatable(value) and getmetatable(value).__type) then
			error("SetAttribute: tables are not a supported attribute type", 2)
		end
		if t == "function" or t == "thread" then
			error("SetAttribute: " .. t .. " is not a supported attribute type", 2)
		end
		local d = rawget(self, "__d")
		if d.attrs[name] == value then
			return
		end
		d.attrs[name] = value
		fireEvent(self, "AttributeChanged", name)
		local s = d.attrSignals[name]
		if s then
			s:_fire()
		end
	end
	function Methods.GetAttributeChangedSignal(self, name)
		local d = rawget(self, "__d")
		d.attrSignals[name] = d.attrSignals[name] or newSignal("AttributeChanged:" .. name)
		return d.attrSignals[name]
	end
	function Methods.GetPropertyChangedSignal(self, name)
		local d = rawget(self, "__d")
		if not (COMMON_PROPS[name] or classHas(d.ClassName, CLASS_PROPS, name)) then
			error(tostring(name) .. " is not a valid property name.", 2)
		end
		d.propSignals[name] = d.propSignals[name] or newSignal("Changed:" .. name)
		return d.propSignals[name]
	end

	-- remotes
	local function netCopy(...)
		local n = select("#", ...)
		local out = table.pack(...)
		for i = 1, n do
			local v = out[i]
			if type(v) == "table" and not isInstance(v) then
				out[i] = deepCopy(v)
			elseif type(v) == "function" or type(v) == "thread" then
				out[i] = nil
			end
		end
		return out
	end
	W.netCopy = netCopy

	Methods["BaseRemoteEvent.FireClient"] = function(self, player, ...)
		if not isInstance(player) or not Methods.IsA(player, "Player") then
			error("FireClient: player argument must be a Player", 2)
		end
		local cl = W.clients[rawget(player, "__d").props.UserId]
		if cl then
			table.insert(cl.inbox, { remote = Methods.GetFullName(self), args = netCopy(...), t = W.now })
			if #cl.inbox > 200 then
				table.remove(cl.inbox, 1)
			end
		end
	end
	Methods["BaseRemoteEvent.FireAllClients"] = function(self, ...)
		for _, p in Methods.GetChildren(W.services.Players) do
			Methods["BaseRemoteEvent.FireClient"](self, p, ...)
		end
	end
	Methods["BaseRemoteEvent.FireServer"] = function()
		error("FireServer can only be called from the client", 2)
	end
	Methods["RemoteFunction.InvokeClient"] = function()
		error("InvokeClient is not supported by the mock (server must not trust clients anyway)", 2)
	end
	Methods["BindableEvent.Fire"] = function(self, ...)
		fireEvent(self, "Event", ...)
	end
	Methods["BindableFunction.Invoke"] = function(self, ...)
		local cb = rawget(self, "__d").props.OnInvoke
		if not cb then
			error("BindableFunction has no OnInvoke", 2)
		end
		return cb(...)
	end
	Methods["Player.Kick"] = function(self, msg)
		local cl = W.clients[rawget(self, "__d").props.UserId]
		if cl then
			cl.kicked = tostring(msg or "")
		end
		W.removePlayer(self)
	end
	Methods["Player.LoadCharacter"] = function() end

	---------------------------------------------------------------- services
	local game = newInstance("DataModel", { Name = "Game", PlaceId = 0, JobId = "twin", CreatorId = 0, GameId = 0 })
	W.game = game
	local function service(className, name)
		local s = newInstance(className, { Name = name or className })
		setParent(s, game)
		W.services[className] = s
		return s
	end
	local workspace = service("Workspace")
	local Players = service("Players")
	rawget(Players, "__d").props.MaxPlayers = 50
	service("ReplicatedStorage")
	service("ServerScriptService")
	service("ServerStorage")
	service("Lighting")
	service("StarterGui")
	service("StarterPlayer")
	local RunService = service("RunService", "Run Service")
	service("DataStoreService")
	service("TweenService")
	service("HttpService")
	W.workspace = workspace

	Methods["DataModel.GetService"] = function(self, name)
		local s = W.services[name]
		if not s then
			error("UNSUPPORTED service in twin mock: " .. tostring(name), 2)
		end
		return s
	end
	Methods["DataModel.FindService"] = function(self, name)
		return W.services[name]
	end
	Methods["DataModel.BindToClose"] = function(self, fn)
		table.insert(W.closeHooks, fn)
	end
	Methods["DataModel.IsLoaded"] = function()
		return true
	end
	rawget(game, "__d").props.Workspace = workspace

	Methods["RunService.IsServer"] = function()
		return true
	end
	Methods["RunService.IsClient"] = function()
		return false
	end
	Methods["RunService.IsStudio"] = function()
		return false
	end
	Methods["RunService.IsRunning"] = function()
		return true
	end

	Methods["Players.GetPlayers"] = function(self)
		return Methods.GetChildren(self)
	end
	Methods["Players.GetPlayerByUserId"] = function(self, id)
		for _, p in Methods.GetChildren(self) do
			if rawget(p, "__d").props.UserId == id then
				return p
			end
		end
		return nil
	end
	Methods["Players.GetPlayerFromCharacter"] = function(self, ch)
		for _, p in Methods.GetChildren(self) do
			if ch ~= nil and rawget(p, "__d").props.Character == ch then
				return p
			end
		end
		return nil
	end
	Methods["Players.GetNameFromUserIdAsync"] = function(self, id)
		return "Twin" .. tostring(id)
	end

	-- DataStores: in-memory, shared across sessions through opts.dsBackend; injected failures.
	local dsBudget = { window = -1, count = 0 }
	local lastWrite = {}
	local function dsCall(kind, storeKey, key)
		W.dsCalls += 1
		local minute = math.floor(W.now / 60)
		if dsBudget.window ~= minute then
			dsBudget.window = minute
			dsBudget.count = 0
		end
		dsBudget.count += 1
		local limit = 60 + 10 * #Methods.GetChildren(Players)
		if dsBudget.count > limit then
			warnOnce("DataStore", "request budget exceeded (" .. limit .. "/min); live Roblox would queue/throttle")
		end
		if kind == "write" then
			local wk = storeKey .. "/" .. tostring(key)
			if lastWrite[wk] and W.now - lastWrite[wk] < 6 then
				warnOnce("DataStore", "writes to the same key within 6 s (live Roblox throttles)")
			end
			lastWrite[wk] = W.now
		end
		if W.dsFailRate > 0 and W.rand() < W.dsFailRate then
			W.dsFailures += 1
			error("502: API Services rejected request (injected DataStore failure)", 3)
		end
	end
	local function checkKey(key)
		if type(key) ~= "string" and type(key) ~= "number" then
			error("DataStore key must be a string", 3)
		end
		if #tostring(key) > 50 then
			error("DataStore key is longer than 50 characters", 3)
		end
	end
	Methods["DataStoreService.GetDataStore"] = function(self, name, scope)
		local storeKey = tostring(name) .. "/" .. tostring(scope or "global")
		W.dsBackend[storeKey] = W.dsBackend[storeKey] or {}
		local data = W.dsBackend[storeKey]
		local store = {}
		function store.GetAsync(_, key)
			checkKey(key)
			dsCall("read", storeKey, key)
			return deepCopy(data[tostring(key)])
		end
		function store.SetAsync(_, key, value)
			checkKey(key)
			local ok, why = storable(value)
			if not ok then
				error("SetAsync: " .. why, 2)
			end
			dsCall("write", storeKey, key)
			data[tostring(key)] = deepCopy(value)
		end
		function store.UpdateAsync(_, key, fn)
			checkKey(key)
			dsCall("write", storeKey, key)
			local nv = fn(deepCopy(data[tostring(key)]))
			if nv ~= nil then
				local ok, why = storable(nv)
				if not ok then
					error("UpdateAsync: " .. why, 2)
				end
				data[tostring(key)] = deepCopy(nv)
			end
			return deepCopy(nv)
		end
		function store.RemoveAsync(_, key)
			checkKey(key)
			dsCall("write", storeKey, key)
			local old = data[tostring(key)]
			data[tostring(key)] = nil
			return old
		end
		function store.IncrementAsync(_, key, delta)
			checkKey(key)
			dsCall("write", storeKey, key)
			local v = (data[tostring(key)] or 0) + (delta or 1)
			data[tostring(key)] = v
			return v
		end
		return store
	end
	Methods["DataStoreService.GetRequestBudgetForRequestType"] = function()
		return math.max(0, 60 + 10 * #Methods.GetChildren(Players) - dsBudget.count)
	end

	Methods["Tween.Play"] = function(t)
		local td = rawget(t, "__d")
		td.props.PlaybackState = "Playing"
		local dur = (type(td.info) == "table" and td.info.Time) or 1
		td.timer = task.delay(dur, function()
			for k, v in td.goal do
				td.target[k] = v
			end
			td.props.PlaybackState = "Completed"
			fireEvent(t, "Completed", "Completed")
		end)
	end
	Methods["Tween.Cancel"] = function(t)
		local td = rawget(t, "__d")
		if td.timer then
			task.cancel(td.timer)
			td.timer = nil
		end
		td.props.PlaybackState = "Cancelled"
		fireEvent(t, "Completed", "Cancelled")
	end
	Methods["Tween.Pause"] = Methods["Tween.Cancel"]
	Methods["TweenService.Create"] = function(self, inst, info, goal)
		local tw = newInstance("Tween", { PlaybackState = "Begin" })
		local td = rawget(tw, "__d")
		td.target, td.info, td.goal = inst, info, goal
		return tw
	end

	local httpGuid = 0
	Methods["HttpService.GenerateGUID"] = function(self, braces)
		httpGuid += 1
		local g = string.format("%08x-0000-4000-8000-%012x", httpGuid, math.floor(W.now * 1000))
		return braces == false and g or "{" .. g .. "}"
	end
	Methods["HttpService.JSONEncode"] = function(self, v)
		return W.json.encode(v)
	end
	Methods["HttpService.JSONDecode"] = function()
		error("UNSUPPORTED: HttpService:JSONDecode in twin mock", 2)
	end

	---------------------------------------------------------------- globals given to game code
	local Instance = {}
	function Instance.new(className, parent)
		if not CREATABLE[className] then
			error("UNSUPPORTED class in twin mock Instance.new: " .. tostring(className), 2)
		end
		local inst = newInstance(className)
		if parent then
			setParent(inst, parent)
		end
		return inst
	end

	local realTypeof = typeof
	local function mockTypeof(v)
		if isInstance(v) then
			return "Instance"
		end
		local mt = type(v) == "table" and getmetatable(v)
		if type(mt) == "table" and rawget(mt, "__type") then
			return rawget(mt, "__type")
		end
		if type(v) == "table" and rawget(v, "__type") then
			return rawget(v, "__type")
		end
		return realTypeof(v)
	end

	local fakeOs = setmetatable({
		time = function(t)
			if t then
				return os.time(t)
			end
			return W.epoch + math.floor(W.now)
		end,
		clock = function()
			return W.now
		end,
		date = function(fmt, t)
			return os.date(fmt, t or (W.epoch + math.floor(W.now)))
		end,
	}, { __index = os })

	local function mockRequire(mod)
		if not isInstance(mod) or not Methods.IsA(mod, "ModuleScript") then
			error("UNSUPPORTED require target in twin mock: " .. tostring(mod) .. " (only ModuleScript instances)", 2)
		end
		local cached = W.modules[mod]
		if cached then
			if cached.loading then
				error("Requested module was required recursively", 2)
			end
			return cached.value
		end
		local factory = rawget(mod, "__d").factory
		if not factory then
			error("ModuleScript " .. Methods.GetFullName(mod) .. " has no source", 2)
		end
		local entry = { loading = true }
		W.modules[mod] = entry
		local ok, result = pcall(factory, W.envFor(mod))
		if not ok then
			W.modules[mod] = nil
			recordError(tostring(result))
			error("Requested module experienced an error while loading: " .. Methods.GetFullName(mod), 2)
		end
		entry.loading = false
		entry.value = result
		return result
	end

	local RandomClass = newRandomClass()
	local function gameWarn(...)
		local parts = {}
		for i = 1, select("#", ...) do
			parts[i] = tostring((select(i, ...)))
		end
		warnOnce("warn", table.concat(parts, " "))
	end
	local function gamePrint() end

	function W.envFor(scriptInst)
		return scriptInst, game, workspace, mockRequire, task, Instance, Enum, Vector3, Vector2, CFrame,
			Color3, UDim2, RandomClass, mockTypeof, function()
				return W.epoch + W.now
			end, function()
				return W.now
			end, task.wait, task.delay, task.spawn, fakeOs, gameWarn, gamePrint, W.G, W.shared
	end

	---------------------------------------------------------------- world API used by the driver
	-- files: list of {path={"ServerScriptService","Main"}, kind="Script"|"ModuleScript", factory=fn}
	function W.load(files)
		for _, f in files do
			local parent = game
			for i = 1, #f.path - 1 do
				local seg = f.path[i]
				local nextp = Methods.FindFirstChild(parent, seg)
				if not nextp then
					if parent == game then
						error("UNSUPPORTED top-level service folder in game dir: " .. seg, 0)
					end
					nextp = newInstance("Folder", { Name = seg })
					setParent(nextp, parent)
				end
				parent = nextp
			end
			local name = f.path[#f.path]
			local existing = Methods.FindFirstChild(parent, name)
			local inst
			if existing and rawget(existing, "__d").ClassName == "Folder" then
				-- init.luau style: a folder becomes the script, keeping its children
				inst = newInstance(f.kind, { Name = name })
				for _, ch in Methods.GetChildren(existing) do
					setParent(ch, inst)
				end
				Methods.Destroy(existing)
			else
				inst = newInstance(f.kind, { Name = name })
			end
			rawget(inst, "__d").factory = f.factory
			setParent(inst, parent)
		end
	end

	function W.start()
		for _, root in { W.services.ServerScriptService, workspace } do
			for _, s in Methods.GetDescendants(root) do
				local d = rawget(s, "__d")
				if d.ClassName == "Script" and d.factory and not d.props.Disabled then
					spawnThread(function()
						d.factory(W.envFor(s))
					end)
				end
			end
		end
		runDue()
	end

	function W.advance(dt)
		local target = W.now + dt
		while W.now + 1e-9 < target do
			local step = math.min(W.tickDt, target - W.now)
			W.now += step
			W.steps += 1
			runDue()
			local hb = rawget(RunService, "__d").events
			if hb.Stepped then
				hb.Stepped:_fire(W.now, step)
			end
			if hb.Heartbeat then
				hb.Heartbeat:_fire(step)
			end
			if hb.PostSimulation then
				hb.PostSimulation:_fire(step)
			end
			runDeferred()
		end
		runDue()
	end

	function W.addPlayer(userId, name)
		local p = newInstance("Player", { Name = name, DisplayName = name, UserId = userId, AccountAge = 30 })
		W.clients[userId] = { player = p, inbox = {}, kicked = nil }
		setParent(p, Players)
		fireEvent(Players, "PlayerAdded", p)
		runDue()
		return p
	end

	function W.removePlayer(p)
		local d = rawget(p, "__d")
		if d.props.Parent ~= Players then
			return
		end
		fireEvent(Players, "PlayerRemoving", p)
		runDue()
		if d.props.Parent == Players then
			setParent(p, nil)
		end
		runDue()
	end

	function W.close()
		for _, fn in W.closeHooks do
			local co = coroutine.create(fn)
			resume(co)
		end
		-- BindToClose gets up to 30 s of game time to finish yields
		local waited = 0
		while #W.waiting > 0 and waited < 30 do
			W.advance(W.tickDt)
			waited += W.tickDt
		end
	end

	-- Client-side network: what a real client can do, nothing more.
	function W.clientFire(player, remote, ...)
		if not isInstance(remote) or not Methods.IsA(remote, "BaseRemoteEvent") then
			error("clientFire: not a RemoteEvent", 2)
		end
		local args = netCopy(...)
		fireEvent(remote, "OnServerEvent", player, table.unpack(args, 1, args.n))
		runDue()
	end

	function W.clientInvoke(player, remote, ...)
		if not isInstance(remote) or not Methods.IsA(remote, "RemoteFunction") then
			error("clientInvoke: not a RemoteFunction", 2)
		end
		local cb = rawget(remote, "__d").props.OnServerInvoke
		if not cb then
			return false, "no OnServerInvoke (client would yield forever)"
		end
		local args = netCopy(...)
		local result
		local co = coroutine.create(function()
			result = table.pack(pcall(cb, player, table.unpack(args, 1, args.n)))
		end)
		resume(co)
		local waited = 0
		while result == nil and waited < 30 do
			W.advance(W.tickDt)
			waited += W.tickDt
		end
		if result == nil then
			return false, "OnServerInvoke did not return within 30 s"
		end
		if not result[1] then
			recordError(tostring(result[2]))
			return false, tostring(result[2])
		end
		local out = netCopy(table.unpack(result, 2, result.n))
		return true, table.unpack(out, 1, out.n)
	end

	return W
end

Engine.deepCopy = deepCopy
return Engine
