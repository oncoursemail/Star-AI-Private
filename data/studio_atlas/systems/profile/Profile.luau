--!strict
-- Session-locked DataStore profiles. The lock is a field of the stored record and is only taken, refreshed or
-- cleared inside UpdateAsync, so two servers can never both believe they own a key.

export type Data = { [string]: any }
export type Record = { Data: Data, SchemaVersion: number, Lock: { JobId: string, Time: number }? }
export type Store = { UpdateAsync: (self: Store, key: string, transform: (Record?) -> Record?) -> any }
export type Config = {
	store: Store,
	jobId: string,
	now: () -> number, -- os.time
	wait: (seconds: number) -> (), -- task.wait
	spawn: (fn: () -> ()) -> (), -- task.spawn
	defaults: Data,
	schemaVersion: number,
	migrations: { [number]: (Data) -> Data }, -- migrations[n] turns schema n into schema n + 1
	lockTimeout: number?, -- a lock older than this belongs to a crashed server (default 300; autosave refreshes it)
	attempts: number?, -- tries per operation, backoff 1, 2, 4... seconds (default 6)
}
export type Profile = {
	Key: string,
	Data: Data,
	Active: boolean,
	Save: (self: Profile) -> boolean,
	Release: (self: Profile) -> boolean, -- final save + unlock; the profile is dead afterwards
}
export type Manager = {
	Load: (self: Manager, key: string) -> (Profile?, string?),
	AutosaveAll: (self: Manager) -> (),
	ReleaseAll: (self: Manager) -> (),
	BindToClose: (self: Manager, game: any) -> (),
}

local Profiles = {}

local function deepCopy(v: any): any
	if type(v) ~= "table" then
		return v
	end
	local out = {}
	for k, x in v do
		out[k] = deepCopy(x)
	end
	return out
end

-- Adds missing keys from the defaults without touching what the player already has.
local function reconcile(data: Data, defaults: Data)
	for k, v in defaults do
		if data[k] == nil then
			data[k] = deepCopy(v)
		elseif type(v) == "table" and type(data[k]) == "table" then
			reconcile(data[k], v)
		end
	end
end

function Profiles.new(cfg: Config): Manager
	for v = 1, cfg.schemaVersion - 1 do
		assert(cfg.migrations[v], `missing migration {v} -> {v + 1}`)
	end
	local lockTimeout = cfg.lockTimeout or 300
	local attempts = cfg.attempts or 6
	local active: { [Profile]: boolean } = {}

	-- fn returns "done" | "locked" | "error" | anything else (fatal). Locked and error are retried with backoff.
	local function retry(tries: number, fn: () -> string): string
		local status = "error"
		for i = 1, tries do
			status = fn()
			if status ~= "locked" and status ~= "error" then
				return status
			end
			if i < tries then
				cfg.wait(2 ^ (i - 1))
			end
		end
		return status
	end

	local function persist(profile: Profile, release: boolean, tries: number): boolean
		if not profile.Active then
			return false
		end
		local snapshot = deepCopy(profile.Data)
		local conflict = false
		local status = retry(tries, function()
			conflict = false
			local ok = pcall(function()
				cfg.store:UpdateAsync(profile.Key, function(old)
					if old and old.Lock and old.Lock.JobId ~= cfg.jobId then
						conflict = true
						return nil -- cancel: another server owns the key now
					end
					return {
						Data = snapshot,
						SchemaVersion = cfg.schemaVersion,
						Lock = if release then nil else { JobId = cfg.jobId, Time = cfg.now() },
					}
				end)
			end)
			if not ok then
				return "error"
			end
			return if conflict then "lost" else "done"
		end)
		if status == "lost" or release then
			profile.Active = false
			active[profile] = nil
		end
		return status == "done"
	end

	local manager = {} :: Manager

	function manager.Load(_self, key)
		local data: Data? = nil
		local failure = "datastore"
		local status = retry(attempts, function()
			local ok = pcall(function()
				cfg.store:UpdateAsync(key, function(old)
					data = nil
					if old and old.Lock and old.Lock.JobId ~= cfg.jobId and cfg.now() - old.Lock.Time < lockTimeout then
						failure = "locked"
						return nil
					end
					if old and old.SchemaVersion > cfg.schemaVersion then
						failure = "newer"
						return nil -- written by a newer game version; never downgrade it
					end
					local loaded: Data = if old then deepCopy(old.Data) else {}
					for v = if old then old.SchemaVersion else cfg.schemaVersion, cfg.schemaVersion - 1 do
						loaded = cfg.migrations[v](loaded)
					end
					reconcile(loaded, cfg.defaults)
					data = loaded
					return {
						Data = deepCopy(loaded),
						SchemaVersion = cfg.schemaVersion,
						Lock = { JobId = cfg.jobId, Time = cfg.now() },
					}
				end)
			end)
			if not ok then
				failure = "datastore"
				return "error"
			end
			if data == nil then
				return if failure == "locked" then "locked" else "fatal"
			end
			return "done"
		end)
		local loaded = data
		if status ~= "done" or loaded == nil then
			return nil, failure
		end
		local profile: Profile = {
			Key = key,
			Data = loaded,
			Active = true,
			Save = function(self)
				return persist(self, false, attempts)
			end,
			Release = function(self)
				return persist(self, true, attempts)
			end,
		}
		active[profile] = true
		return profile, nil
	end

	function manager.AutosaveAll(_self)
		for profile in table.clone(active) do
			cfg.spawn(function()
				profile:Save()
			end)
		end
	end

	function manager.ReleaseAll(_self)
		local pending = 0
		for profile in table.clone(active) do
			pending += 1
			cfg.spawn(function()
				persist(profile, true, 3) -- shutdown has about 30 s in total: fewer retries
				pending -= 1
			end)
		end
		while pending > 0 do
			cfg.wait(0.1)
		end
	end

	function manager.BindToClose(self, game)
		game:BindToClose(function()
			self:ReleaseAll()
		end)
	end

	return manager
end

return Profiles
