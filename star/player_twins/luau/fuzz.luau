-- Exploiter persona (P5): fuzzes every remote the client can reach with bad arguments and spam,
-- and reports each request that changed the player's stats more than any legitimate call did.
local Fuzz = {}

local function describe(v)
	local t = type(v)
	if t == "string" then
		if #v > 24 then
			return string.format("string(len %d)", #v)
		end
		return string.format("%q", v)
	elseif t == "number" then
		if v ~= v then
			return "NaN"
		end
		return tostring(v)
	elseif t == "table" then
		return "{table}"
	end
	return tostring(v)
end

function Fuzz.describeArgs(args)
	local parts = {}
	for i = 1, args.n do
		parts[i] = describe(args[i])
	end
	return "(" .. table.concat(parts, ", ") .. ")"
end

local function swapArg(base, i, value)
	local out = table.clone(base)
	out[i] = value
	out.n = math.max(base.n, i)
	return out
end

-- Mutations of a legitimate argument tuple. Offsets skip +1 so "next valid value" is not tested.
function Fuzz.mutations(base)
	local list = {}
	local function add(t)
		table.insert(list, t)
	end
	add(table.pack())
	add(swapArg(base, base.n + 1, 1e9))
	for i = 1, base.n do
		local v = base[i]
		if type(v) == "number" then
			for _, x in { v + 2, v + 10, v + 1000, 1e9, -1, -1e9, 0, v + 0.5, math.huge, -math.huge, 0 / 0 } do
				add(swapArg(base, i, x))
			end
			add(swapArg(base, i, tostring(v)))
		elseif type(v) == "string" then
			for _, x in { "", v .. "_x", string.rep("A", 5000), "../" .. v, "nil" } do
				add(swapArg(base, i, x))
			end
			add(swapArg(base, i, 123))
		end
		add(swapArg(base, i, true))
		add(swapArg(base, i, {}))
		add(swapArg(base, i, { [1] = v, hack = true }))
	end
	if base.n == 0 then
		for _, x in { 1e9, -1, "x", {} } do
			add(table.pack(x))
		end
	end
	return list
end

-- ctx: world, player, client, legit = {[remoteName] = {args = packed, maxDelta = {stat = n}}}
-- Findings of kind invalid_args_accepted carry `replay` (remote + args) so the exploiter can reuse them.
function Fuzz.run(ctx)
	local W, client = ctx.world, ctx.client
	local findings, tested = {}, {}
	local seen = {}
	local remotes = {}
	for _, inst in W.services.ReplicatedStorage:GetDescendants() do
		if inst:IsA("RemoteEvent") or inst:IsA("RemoteFunction") then
			table.insert(remotes, inst)
		end
	end
	table.sort(remotes, function(a, b)
		return a:GetFullName() < b:GetFullName()
	end)

	local function call(remote, args)
		if remote:IsA("RemoteEvent") then
			W.clientFire(ctx.player, remote, table.unpack(args, 1, args.n))
		else
			W.clientInvoke(ctx.player, remote, table.unpack(args, 1, args.n))
		end
	end

	local function add(remoteName, kind, detail, replay)
		local key = remoteName .. "|" .. kind
		local f = seen[key]
		if f then
			f.count += 1
			if #f.examples < 3 then
				table.insert(f.examples, detail)
			end
			return
		end
		f = { remote = remoteName, kind = kind, count = 1, examples = { detail }, replay = replay }
		seen[key] = f
		table.insert(findings, f)
	end

	for _, remote in remotes do
		local name = remote:GetFullName()
		local legit = ctx.legit[name]
		local base = legit and legit.args or table.pack()
		local maxDelta = legit and legit.maxDelta or {}
		local entry = { remote = name, legitSample = legit ~= nil, mutations = 0, spam = false }
		table.insert(tested, entry)
		for _, args in Fuzz.mutations(base) do
			entry.mutations += 1
			W.advance(1) -- an exploiter paces requests so per-request cooldowns do not hide a bug
			local before = client:Stats()
			local errs = W.errorCount
			call(remote, args)
			local after = client:Stats()
			for stat, v in after do
				local delta = v - (before[stat] or 0)
				local allowed = maxDelta[stat] or 0
				if delta > 0 and delta > allowed * 1.0001 then
					add(name, "invalid_args_accepted", { args = Fuzz.describeArgs(args), stat = stat, delta = delta, legitMax = allowed },
						{ remote = remote, args = args })
				end
			end
			if W.errorCount > errs then
				add(name, "server_error_on_bad_input", { args = Fuzz.describeArgs(args) })
			end
		end
		-- Spam: 60 legitimate-looking requests inside one server tick; humans manage about 12/s.
		if remote:IsA("RemoteEvent") and legit then
			local gainStat, gain = nil, 0
			for stat, d in maxDelta do
				if d > gain then
					gainStat, gain = stat, d
				end
			end
			if gainStat then
				entry.spam = true
				W.advance(1)
				local before = client:Stats()
				for _ = 1, 60 do
					call(remote, base)
				end
				local delta = (client:Stats()[gainStat] or 0) - (before[gainStat] or 0)
				if delta > gain * 15 then
					add(name, "no_rate_limit", { args = Fuzz.describeArgs(base), stat = gainStat, delta = delta, legitMax = gain, calls = 60 })
				end
			end
		end
	end
	return findings, tested
end

return Fuzz
