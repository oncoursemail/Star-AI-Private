-- Human model for logic twins: reaction time, Fitts'-law pointing, misreads, attention, learning,
-- and a flow-based quit model (frustration from repeated failure, boredom from waiting/no content).
local Human = {}
Human.__index = Human

-- Fitts' law MT = a + b*log2(D/W + 1) in seconds; noise scales the endpoint spread (touch is the
-- "fat finger" case). Values are typical published ranges, not fitted to Roblox players.
local DEVICES = {
	mouse = { a = 0.12, b = 0.13, noise = 1.0 },
	touch = { a = 0.16, b = 0.18, noise = 2.6 },
	gamepad = { a = 0.30, b = 0.28, noise = 1.6 },
}
Human.DEVICES = DEVICES

local function log2(x)
	return math.log(x) / math.log(2)
end

function Human.randn(r)
	local u1 = math.max(r(), 1e-12)
	local u2 = r()
	return math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
end

function Human.lognormal(r, median, sigma)
	return median * math.exp(sigma * Human.randn(r))
end

local function uniform(r, lo, hi)
	return lo + (hi - lo) * r()
end

function Human.new(p, memory, r)
	memory.skill = memory.skill or p.skill0
	memory.sessions = (memory.sessions or 0) + 1
	local self = setmetatable({
		p = p,
		mem = memory,
		r = r,
		dev = DEVICES[p.device] or DEVICES.mouse,
		boredom = 0,
		frust = 0,
		consecFails = 0,
		patience = Human.lognormal(r, p.patience, 0.4),
		frustTol = Human.lognormal(r, p.frustTol, 0.3),
		sessionLen = Human.lognormal(r, p.sessionMin * 60, 0.5),
		rate = 0,
		lastCash = nil,
		lastT = nil,
		zone = { flow = 0, anxiety = 0, boredom = 0 },
		clicks = 0,
		misclicks = 0,
		misreads = 0,
		attempts = 0,
		fails = 0,
		goal = nil,
		maxPrice = 0,
		seen = {},
		challenges = {}, -- id -> {attempts, fails}
		hasChallenge = false,
		hasPrestige = false,
		cash = 0,
	}, Human)
	return self
end

-- Seconds from stimulus to the start of a response (log-normal, right-skewed like real RTs).
function Human:reactionTime()
	return math.clamp(Human.lognormal(self.r, self.p.rt, self.p.rtSigma), 0.1, 3)
end

-- Time to point at and press a UI target, with misses that need a corrective movement.
function Human:pointTime(ui)
	local w, d = ui.w, ui.d
	local dev = self.dev
	local t = dev.a + dev.b * log2(d / w + 1)
	local sigma = dev.noise * self.p.motor * (2 + 0.03 * d)
	local misses = 0
	while math.abs(Human.randn(self.r) * sigma) > w / 2 and misses < 5 do
		misses += 1
		t += dev.a + dev.b * log2(2 * sigma / w + 1)
	end
	self.misclicks += misses
	return t, misses
end

function Human:decisionTime()
	local familiarity = 1 + 0.6 / self.mem.sessions
	return Human.lognormal(self.r, self.p.decision * familiarity, 0.4)
end

-- Perceived income: what the player can infer from their cash going up, excluding own spending.
function Human:perceive(now, cash, sunkSince)
	if self.lastT then
		local dt = now - self.lastT
		if dt > 0 then
			local gained = math.max(0, cash - self.lastCash + (sunkSince or 0))
			local inst = gained / dt
			local alpha = 1 - math.exp(-dt / 30)
			self.rate += alpha * (inst - self.rate)
		end
	end
	self.lastT, self.lastCash, self.cash = now, cash, cash
end

function Human:chooseGoal(purchases)
	local strategy = self.p.strategy
	local best
	for _, a in purchases do
		self.maxPrice = math.max(self.maxPrice, a.cost)
	end
	if #purchases == 0 then
		return nil
	end
	if strategy == "random" then
		if self.goal then
			for _, a in purchases do
				if a.id == self.goal.id then
					return a
				end
			end
		end
		return purchases[math.floor(self.r() * #purchases) + 1]
	end
	if strategy == "roi" then
		for _, a in purchases do
			if (a.value or 0) > 0 and (not best or a.value / a.cost > best.value / best.cost) then
				best = a
			end
		end
		if best then
			return best
		end
	end
	for _, a in purchases do
		if not best or a.cost < best.cost then
			best = a
		end
	end
	return best
end

function Human:expectedWait()
	if not self.goal then
		return 0
	end
	local need = self.goal.cost - self.cash
	if need <= 0 then
		return 0
	end
	return need / math.max(self.rate, 1e-6)
end

-- Players go back to a challenge less often while it keeps beating them.
function Human:challengeAppetite()
	local appetite = self.p.challengePref * math.max(0.1, 1 - self.frust / self.frustTol)
	if self.consecFails >= 3 then
		appetite *= 0.3
	end
	return appetite
end

function Human:novelty()
	self.boredom *= 0.5
end

-- Pick the next thing to do. Returns a plan: {kind, action?, think, wait?, clicks?}
function Human:decide(actions)
	local p, r = self.p, self.r
	local purchases, challenge, prestige, earn = {}, nil, nil, nil
	for _, a in actions do
		if not self.seen[a.id] then
			self.seen[a.id] = true
			self:novelty()
		end
		if a.kind == "purchase" then
			table.insert(purchases, a)
		elseif a.kind == "challenge" then
			challenge = a
		elseif a.kind == "prestige" then
			prestige = a
		elseif a.kind == "earn" then
			earn = a
		end
	end
	self.hasChallenge = challenge ~= nil
	self.goal = self:chooseGoal(purchases)
	-- a prestige the player cannot afford yet is something to save for, not an action
	if prestige and (prestige.cost or 0) > self.cash then
		self.goal = self.goal or prestige
		prestige = nil
	end
	self.hasPrestige = prestige ~= nil or (self.goal ~= nil and self.goal.kind == "prestige")

	if r() < p.idleProb then
		return { kind = "idle", wait = uniform(r, p.idleMin, p.idleMax) }
	end

	local chosen
	if prestige and r() < p.prestige then
		chosen = prestige
	elseif self.goal and self.goal.cost <= self.cash then
		chosen = self.goal
	elseif challenge and r() < self:challengeAppetite() then
		chosen = challenge
	elseif earn and p.clickMax > 0 then
		chosen = earn
	end
	if not chosen then
		return { kind = "idle", wait = uniform(r, 2, 8) }
	end
	-- UI misread: the player presses a different button than intended.
	if #actions > 1 and r() < p.misread / self.mem.sessions then
		local other = actions[math.floor(r() * #actions) + 1]
		if other ~= chosen then
			self.misreads += 1
			chosen = other
		end
	end
	local think = self:decisionTime() + self:reactionTime()
	local move = self:pointTime(chosen.ui or { w = 100, d = 300 })
	local plan = { kind = chosen.kind, action = chosen, think = think + move }
	if chosen.kind == "earn" then
		plan.clicks = math.floor(uniform(r, p.clickMin, p.clickMax + 1))
	end
	return plan
end

-- Seconds between two presses on the same button during a click burst.
function Human:repeatClickTime(ui)
	local dev = self.dev
	local t = dev.a + self.p.clickGap * math.exp(0.3 * Human.randn(self.r))
	local sigma = dev.noise * self.p.motor * 2
	if math.abs(Human.randn(self.r) * sigma) > ui.w / 2 then
		self.misclicks += 1
		return t * 2, false
	end
	return t, true
end

-- A challenge attempt: success chance from skill vs difficulty; practice raises skill.
function Human:attempt(a)
	local p, r = self.p, self.r
	self.attempts += 1
	self.lastChallenge = a.id
	local d = a.difficulty or 1
	local chance = 1 / (1 + math.exp(-1.8 * (self.mem.skill - d)))
	local ok = r() < chance
	local cs = self.challenges[a.id] or { attempts = 0, fails = 0 }
	self.challenges[a.id] = cs
	cs.attempts += 1
	if not ok then
		cs.fails += 1
	end
	self.mem.skill = math.min(10, self.mem.skill + p.learn * 0.25 * math.max(0.1, d + 0.5 - self.mem.skill))
	if ok then
		self.consecFails = 0
		self.frust = math.max(0, self.frust - 1.5)
		self:novelty()
	else
		self.fails += 1
		self.consecFails += 1
		self.frust += 1 + 0.3 * (self.consecFails - 1)
	end
	local duration = (a.duration or 10) * Human.lognormal(r, 1, 0.2)
	return ok, duration
end

-- Advance the player's mood by dt seconds; returns a quit reason or nil.
function Human:tick(dt, now)
	self.frust = math.max(0, self.frust - dt * 0.03) -- calms down over a minute or two
	local outOfContent = not self.goal and not self.hasChallenge and not self.hasPrestige
	local wait = self:expectedWait()
	if outOfContent then
		self.boredom += 2 * dt / self.patience
		self.zone.boredom += dt
	elseif wait > self.p.acceptableWait then
		-- graded: a wait 10x longer than the player accepts bores at the full rate
		local excess = math.clamp(math.log10(wait / self.p.acceptableWait), 0.1, 1)
		self.boredom += excess * dt / self.patience
		self.zone.boredom += dt
	elseif self.frust > 0.5 * self.frustTol then
		self.zone.anxiety += dt
	else
		self.boredom = math.max(0, self.boredom - dt / (2 * self.patience))
		self.zone.flow += dt
	end
	if self.frust >= self.frustTol then
		return "frustrated"
	end
	if self.boredom >= 1 then
		return outOfContent and "out_of_content" or "bored"
	end
	if now >= self.sessionLen then
		return "time_up"
	end
	return nil
end

-- Chance the twin comes back for another session (P8 retention, simple model).
function Human:returnChance(reason)
	local total = self.zone.flow + self.zone.anxiety + self.zone.boredom
	local flowFrac = total > 0 and self.zone.flow / total or 0.5
	local mod = ({ frustrated = 0.5, bored = 0.6, out_of_content = 0.4, kicked = 0 })[reason] or 1
	return math.clamp(self.p.returnBase * (0.5 + flowFrac) * mod, 0, 0.95)
end

return Human
