---
id: gb-data-session-lock-updateasync
category: datastore-safety
topics: DataStore, session lock, UpdateAsync, JobId, item duplication
source: original
---
# Request
Players dupe items by rejoining fast: the new server loads their data before the old server has saved it. How do I add session locking so only one server can own a player's data at a time?

# Answer
Store a lock (`JobId` + timestamp) inside the same record as the data and take it with `UpdateAsync`, so the check and the claim are one atomic step. A server only saves while it still holds the lock, and a lock older than a timeout is treated as left behind by a crashed server.

```lua
--!strict
-- ModuleScript: ServerScriptService.SessionLock
local DataStoreService = game:GetService("DataStoreService")

local store = DataStoreService:GetDataStore("PlayerData")
local LOCK_TIMEOUT = 300 -- seconds; autosave refreshes the lock well before this

type Data = { [string]: any }
type Record = { data: Data?, lock: { jobId: string, at: number }? }

local SessionLock = {}

local function keyFor(userId: number): string
	return "player_" .. userId
end

local function deepCopy(value: any): any
	if type(value) ~= "table" then
		return value
	end
	local out = {}
	for k, v in value do
		out[k] = deepCopy(v)
	end
	return out
end

-- Returns the data when this server now owns the session, otherwise nil and "locked" or an error text.
function SessionLock.acquire(userId: number, defaults: Data): (Data?, string?)
	local jobId: string = game.JobId
	local data: Data? = nil
	local reason: string? = nil
	local ok, err = pcall(function()
		store:UpdateAsync(keyFor(userId), function(old: Record?): Record?
			local record: Record = old or {}
			local now = os.time()
			local lock = record.lock
			if lock and lock.jobId ~= jobId and now - lock.at < LOCK_TIMEOUT then
				reason, data = "locked", nil
				return nil -- cancel the write; another live server owns this player
			end
			record.lock = { jobId = jobId, at = now }
			record.data = record.data or deepCopy(defaults)
			reason, data = nil, record.data
			return record
		end)
	end)
	if not ok then
		return nil, tostring(err)
	end
	return data, reason
end

-- Writes data only while this server holds the lock. release = true on leave or shutdown.
function SessionLock.save(userId: number, data: Data, release: boolean): boolean
	local jobId: string = game.JobId
	local written = false
	local ok = pcall(function()
		store:UpdateAsync(keyFor(userId), function(old: Record?): Record?
			local lock = old and old.lock
			if lock == nil or lock.jobId ~= jobId then
				written = false
				return nil -- we lost the session; never overwrite the new owner's data
			end
			written = true
			return { data = data, lock = if release then nil else { jobId = jobId, at = os.time() } }
		end)
	end)
	return ok and written
end

-- The old server usually releases within a few seconds, so wait and retry before giving up.
function SessionLock.acquireWithRetry(userId: number, defaults: Data, attempts: number): (Data?, string?)
	local data, reason = nil, nil
	for attempt = 1, attempts do
		data, reason = SessionLock.acquire(userId, defaults)
		if data then
			return data, nil
		end
		if attempt < attempts then
			task.wait(2 ^ attempt)
		end
	end
	return nil, reason
end

return SessionLock
```

- The transform function can run more than once, so it resets `data` and `reason` on every run instead of accumulating.
- If `acquireWithRetry` still fails, kick the player with "Your data is still saving, rejoin in a moment" rather than letting them play on defaults.
- Call `save(userId, data, false)` from the autosave loop to refresh the lock timestamp, and `save(..., true)` on `PlayerRemoving` and in `BindToClose`.

# Test
```lua
game.JobId = "server-A"
local data, reason = item.acquire(10, { coins = 0 })
check("first server takes the session", data ~= nil and reason == nil and data.coins == 0)

game.JobId = "server-B"
local blocked, why = item.acquire(10, { coins = 0 })
check("second server is refused while the lock is fresh", blocked == nil and why == "locked")

game.JobId = "server-A"
local saved = item.save(10, { coins = 50 }, true)
check("owner saves and releases", saved)

game.JobId = "server-B"
local loaded = item.acquire(10, { coins = 0 })
check("released lock lets the next server load the saved data", loaded ~= nil and loaded.coins == 50)

game.JobId = "server-A"
check("old server can no longer overwrite", item.save(10, { coins = 1 }, true) == false)

game.JobId = "server-C"
__advance(301)
local stolen = item.acquire(10, { coins = 0 })
check("stale lock from a crashed server can be taken", stolen ~= nil and stolen.coins == 50)

game:GetService("DataStoreService").__failNext = 1
local none, err = item.acquire(11, {})
check("data store errors are reported, not thrown", none == nil and type(err) == "string")
```
