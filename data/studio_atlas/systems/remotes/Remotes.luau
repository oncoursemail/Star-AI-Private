--!strict
-- Secure RemoteEvent / RemoteFunction layer. The client is untrusted: every argument is validated against a
-- schema, every remote has a per-player token bucket, and the handler only ever sees cleaned values.

export type Validator = (value: any) -> (boolean, any) -- ok, cleaned value (or the error message)
export type Spec = {
	kind: "event" | "function",
	args: { Validator },
	rate: { perSecond: number, burst: number },
	handler: (player: any, ...any) -> any,
}
export type Config = {
	now: () -> number, -- os.clock
	onReject: ((player: any, remote: string, reason: string) -> ())?, -- log, count strikes, kick repeat offenders
}
export type Remotes = {
	Bind: (self: Remotes, name: string, remote: any, spec: Spec) -> (),
	Dispatch: (self: Remotes, name: string, player: any, ...any) -> (boolean, any),
	Forget: (self: Remotes, player: any) -> (), -- call from PlayerRemoving
}

local t = {}

function t.number(min: number?, max: number?, integer: boolean?): Validator
	return function(v)
		if type(v) ~= "number" or v ~= v or v == math.huge or v == -math.huge then
			return false, "number expected"
		end
		if integer == true and v % 1 ~= 0 then
			return false, "integer expected"
		end
		if (min ~= nil and v < min) or (max ~= nil and v > max) then
			return false, "number out of range"
		end
		return true, v
	end
end

function t.string(maxLength: number, pattern: string?): Validator
	return function(v)
		if type(v) ~= "string" or #v > maxLength then
			return false, "string expected"
		end
		if pattern ~= nil and not string.match(v, pattern) then
			return false, "string has the wrong shape"
		end
		return true, v
	end
end

t.boolean = function(v: any): (boolean, any)
	return type(v) == "boolean", v
end

function t.oneOf(allowed: { any }): Validator
	return function(v)
		return table.find(allowed, v) ~= nil, v
	end
end

function t.optional(inner: Validator): Validator
	return function(v)
		if v == nil then
			return true, nil
		end
		return inner(v)
	end
end

-- A plain table with exactly these keys; unknown keys are rejected so the client cannot smuggle extra fields.
function t.shape(fields: { [string]: Validator }): Validator
	return function(v)
		if type(v) ~= "table" then
			return false, "table expected"
		end
		local out = {}
		for key in v do
			if type(key) ~= "string" or fields[key] == nil then
				return false, "unexpected field"
			end
		end
		for key, validate in fields do
			local ok, cleaned = validate(v[key])
			if not ok then
				return false, `{key}: {cleaned}`
			end
			out[key] = cleaned
		end
		return true, out
	end
end

local Layer = {}

function Layer.new(cfg: Config): Remotes
	local specs: { [string]: Spec } = {}
	local buckets: { [any]: { [string]: { tokens: number, last: number } } } = {}
	local layer = {} :: Remotes

	local function reject(player: any, name: string, reason: string)
		if cfg.onReject then
			cfg.onReject(player, name, reason)
		end
	end

	local function take(player: any, name: string, spec: Spec): boolean
		local perPlayer = buckets[player]
		if perPlayer == nil then
			perPlayer = {}
			buckets[player] = perPlayer
		end
		local now = cfg.now()
		local bucket = perPlayer[name]
		if bucket == nil then
			bucket = { tokens = spec.rate.burst, last = now }
			perPlayer[name] = bucket
		end
		bucket.tokens = math.min(spec.rate.burst, bucket.tokens + (now - bucket.last) * spec.rate.perSecond)
		bucket.last = now
		if bucket.tokens < 1 then
			return false
		end
		bucket.tokens -= 1
		return true
	end

	function layer.Dispatch(_self, name, player, ...)
		local spec = specs[name]
		if spec == nil then
			return false, "unknown remote"
		end
		if not take(player, name, spec) then
			reject(player, name, "rate limit")
			return false, "rate limit"
		end
		local count = select("#", ...)
		if count > #spec.args then
			reject(player, name, "too many arguments")
			return false, "too many arguments"
		end
		local raw = { ... }
		local clean = table.create(#spec.args)
		for i, validate in spec.args do
			local ok, value = validate(raw[i])
			if not ok then
				reject(player, name, `argument {i}: {value}`)
				return false, `argument {i}: {value}`
			end
			clean[i] = value
		end
		local ok, result = pcall(spec.handler, player, table.unpack(clean, 1, #spec.args))
		if not ok then
			reject(player, name, "handler error") -- a bug on our side, not a violation: log, do not punish
			return false, "handler error"
		end
		return true, result
	end

	function layer.Bind(self, name, remote, spec)
		specs[name] = spec
		if spec.kind == "event" then
			remote.OnServerEvent:Connect(function(player: any, ...)
				self:Dispatch(name, player, ...)
			end)
		else
			remote.OnServerInvoke = function(player: any, ...)
				local ok, result = self:Dispatch(name, player, ...)
				if ok then
					return result
				end
				return nil
			end
		end
	end

	function layer.Forget(_self, player)
		buckets[player] = nil
	end

	return layer
end

return { new = Layer.new, t = t }
