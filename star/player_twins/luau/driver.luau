-- Player Twins driver: plays every twin in __CONFIG.twins against fresh engine worlds and prints one
-- "@@TWIN <json>" line per session. Python builds the bundle that defines __CONFIG, __FILES,
-- __ADAPTER, Engine, Json, Human and Fuzz above this file.
local S = __CONFIG.settings
local PERSONAS = __CONFIG.personas

local function newClient(W, player)
	local C = { player = player, currency = nil, legit = {}, econ = { earned = 0, sunk = 0, last = nil }, missing = {} }

	local function resolve(path)
		local inst = W.services.ReplicatedStorage
		for seg in string.gmatch(path, "[^%.]+") do
			inst = inst:FindFirstChild(seg)
			if not inst then
				return nil
			end
		end
		return inst
	end

	function C:Stat(name)
		local ls = player:FindFirstChild("leaderstats")
		local v = ls and ls:FindFirstChild(name)
		return v and v.Value
	end

	function C:Stats()
		local out = {}
		local ls = player:FindFirstChild("leaderstats")
		if ls then
			for _, v in ls:GetChildren() do
				if type(v.Value) == "number" then
					out[v.Name] = v.Value
				end
			end
		end
		return out
	end

	function C:Sync()
		local cash = (self.currency and self:Stat(self.currency)) or 0
		local e = self.econ
		if e.last then
			local d = cash - e.last
			if d > 0 then
				e.earned += d
			elseif d < 0 then
				e.sunk -= d
			end
		end
		e.last = cash
		return cash
	end

	local function record(name, args, before, after)
		local l = C.legit[name]
		if not l then
			l = { args = args, maxDelta = {} }
			C.legit[name] = l
		end
		l.args = args
		for stat, v in after do
			local d = v - (before[stat] or 0)
			if d > (l.maxDelta[stat] or 0) then
				l.maxDelta[stat] = d
			end
		end
	end

	function C:Fire(path, ...)
		local r = resolve(path)
		if not r then
			self.missing[path] = true
			return
		end
		self:Sync()
		local before = self:Stats()
		W.clientFire(player, r, ...)
		self:Sync()
		record(r:GetFullName(), table.pack(...), before, self:Stats())
	end

	function C:Invoke(path, ...)
		local r = resolve(path)
		if not r then
			self.missing[path] = true
			return false, "missing remote " .. path
		end
		if not self.legit[r:GetFullName()] then
			self.legit[r:GetFullName()] = { args = table.pack(...), maxDelta = {} }
		end
		return W.clientInvoke(player, r, ...)
	end

	function C:Inbox()
		return W.clients[player.UserId].inbox
	end

	return C
end

local function listOf(map, limit)
	local out = {}
	for msg, e in map do
		table.insert(out, { msg = msg, count = e.count, t = e.t })
	end
	table.sort(out, function(a, b)
		return a.count > b.count
	end)
	while #out > limit do
		table.remove(out)
	end
	return out
end

local function runSession(twin, day, mem)
	local persona = PERSONAS[twin.persona]
	math.randomseed((twin.seed * 7919 + day) % 2147483647) -- randomseed takes a 32-bit int
	local r = math.random
	local W = Engine.newWorld({ tickDt = S.tickDt, dsBackend = mem.ds, dsFailRate = S.dsFailRate, rand = r })
	W.json = Json
	W.load(__FILES)
	W.start()
	local player = W.addPlayer(twin.userId, "Twin" .. twin.id)
	W.advance(2)
	local client = newClient(W, player)
	local A = __ADAPTER(client)
	client.currency = A.currency
	local function cashNow()
		return client:Stat(A.currency) or 0
	end

	local H = Human.new(persona, mem.human, r)
	local t0 = W.now
	local function now()
		return W.now - t0
	end
	local cap = S.capMin * 60
	local res = {
		twin = twin.id, persona = twin.persona, day = day, seed = twin.seed,
		milestones = {}, newMilestones = {}, actions = {}, timeline = {}, findings = {}, fuzzTests = {},
		prevEndCash = mem.endCash, playTimeBefore = mem.playTime or 0,
	}
	local startCash = client:Sync()
	res.startCash = startCash
	local nextSample = 0
	local function sample()
		while now() >= nextSample do
			client:Sync()
			table.insert(res.timeline, { math.floor(nextSample), client.econ.last or 0, client.econ.earned, client.econ.sunk })
			nextSample += S.sampleSec
		end
	end
	sample()
	local sunkSeen = 0
	local function perceive()
		local cash = client:Sync()
		H:perceive(now(), cash, client.econ.sunk - sunkSeen)
		sunkSeen = client.econ.sunk
	end

	-- Very short waits (click to click) are batched until half a tick has built up: far fewer engine
	-- steps, and clicks inside one batch still land in the same server second as they would live.
	local owed = 0
	local function pass(dt)
		owed += dt
		if owed < S.tickDt * 0.5 then
			return nil
		end
		local remaining = owed
		owed = 0
		while remaining > 1e-9 do
			local step = math.min(remaining, 5)
			W.advance(step)
			remaining -= step
			if W.clients[twin.userId].kicked then
				return "kicked"
			end
			perceive()
			sample()
			local q = H:tick(step, now())
			if q then
				return q
			end
			if now() >= cap then
				return "cap"
			end
		end
		return nil
	end

	local function count(id)
		res.actions[id] = (res.actions[id] or 0) + 1
	end

	local fuzzAt = (persona.fuzz and day == 1) and (S.fuzzMin + (S.fuzzMax - S.fuzzMin) * r()) or nil
	local replay = nil
	local quit
	local harness = nil
	while not quit do
		local ok, obs = pcall(A.observe)
		if not ok then
			harness = "adapter.observe failed: " .. tostring(obs)
			quit = "harness_error"
			break
		end
		perceive()
		local okM, reached = pcall(A.milestones, obs)
		if okM then
			for _, id in reached do
				if not res.milestones[id] then
					res.milestones[id] = math.floor(now())
					H:novelty()
				end
				if not mem.milestones[id] then
					mem.milestones[id] = true
					res.newMilestones[id] = math.floor(res.playTimeBefore + now())
				end
			end
		end
		local okA, actions = pcall(A.actions, obs)
		if not okA then
			harness = "adapter.actions failed: " .. tostring(actions)
			quit = "harness_error"
			break
		end

		if fuzzAt and now() >= fuzzAt then
			fuzzAt = nil
			local before = W.now
			local findings, tested = Fuzz.run({ world = W, player = player, client = client, legit = client.legit })
			for _, f in findings do
				if f.replay and not replay then
					replay = f.replay
				end
				f.replay = nil
				table.insert(res.findings, f)
			end
			res.fuzzTests = tested
			res.fuzzSeconds = W.now - before
			client:Sync()
			sunkSeen = client.econ.sunk
			quit = H:tick(W.now - before, now())
			if quit then
				break
			end
			continue
		end
		if replay and r() < 0.2 then
			count("exploit")
			W.clientFire(player, replay.remote, table.unpack(replay.args, 1, replay.args.n))
		end

		local plan = H:decide(actions)
		if plan.kind == "idle" then
			count("idle")
			quit = pass(plan.wait)
		else
			quit = pass(plan.think)
			if quit then
				break
			end
			local a = plan.action
			if plan.kind == "earn" then
				count(a.id)
				for _ = 1, plan.clicks do
					local dt, hit = H:repeatClickTime(a.ui or { w = 100, d = 0 })
					if hit then
						H.clicks += 1
						a.run()
					end
					quit = pass(dt)
					if quit then
						break
					end
				end
			elseif plan.kind == "challenge" then
				count(a.id)
				local success, duration = H:attempt(a)
				quit = pass(duration)
				if not quit and success then
					a.run()
				end
			else
				count(a.id)
				local before = cashNow()
				a.run()
				if cashNow() ~= before then
					H:novelty()
				end
			end
		end
	end

	res.quit = quit
	res.harnessError = harness
	res.duration = math.floor(now())
	res.quitInfo = {
		goal = H.goal and H.goal.id, cost = H.goal and H.goal.cost, cash = cashNow(),
		rate = H.rate, wait = H:expectedWait(), frustration = H.frust, boredom = H.boredom,
		patience = H.patience, frustTol = H.frustTol, sessionLen = H.sessionLen,
		challenge = H.lastChallenge, consecFails = H.consecFails,
	}
	res.endCash = client:Sync()
	res.earned = client.econ.earned
	res.sunk = client.econ.sunk
	res.maxPrice = H.maxPrice
	res.zone = H.zone
	res.clicks, res.misclicks, res.misreads = H.clicks, H.misclicks, H.misreads
	res.attempts, res.fails, res.skill = H.attempts, H.fails, H.mem.skill
	res.challenges = H.challenges
	res.kicked = W.clients[twin.userId].kicked
	local missing = {}
	for path in client.missing do
		table.insert(missing, path)
	end
	res.missingRemotes = missing
	res.returnChance = H:returnChance(quit)
	res.mainline = A.mainline

	W.removePlayer(player)
	W.advance(2)
	W.close()
	res.errors = listOf(W.errors, 20)
	res.errorCount = W.errorCount
	res.warnings = listOf(W.warnings, 20)
	res.dsCalls, res.dsFailures = W.dsCalls, W.dsFailures
	res.steps = W.steps

	mem.endCash = res.endCash
	mem.playTime = (mem.playTime or 0) + res.duration
	-- the mainline index reached so far (lifetime, because prestige resets owned items)
	local idx = 0
	for i, id in A.mainline or {} do
		if mem.milestones[id] then
			idx = i
		end
	end
	res.mainlineIndex = idx
	return res
end

local clock0 = os.clock()
local sessions = 0
for _, twin in __CONFIG.twins do
	local mem = { ds = {}, human = {}, milestones = {} }
	for day = 1, twin.days do
		local ok, res = pcall(runSession, twin, day, mem)
		if not ok then
			res = { twin = twin.id, persona = twin.persona, day = day, quit = "harness_error", harnessError = tostring(res) }
		end
		sessions += 1
		-- the return roll happens on the last day too: it separates churned twins from active ones
		local returns = false
		if ok then
			math.randomseed((twin.seed * 104729 + day) % 2147483647)
			returns = math.random() < (res.returnChance or 0)
		end
		res.returns = returns
		print("@@TWIN " .. Json.encode(res))
		if not returns then
			break
		end
	end
end
print("@@DONE " .. Json.encode({ sessions = sessions, cpu = os.clock() - clock0 }))
