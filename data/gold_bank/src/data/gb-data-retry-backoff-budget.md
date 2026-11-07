---
id: gb-data-retry-backoff-budget
category: datastore-safety
topics: DataStore, retry, exponential backoff, jitter, request budget
source: original
---
# Request
My data store calls fail now and then with 502/503 errors and players lose progress. Can you write a small helper that retries DataStore calls with exponential backoff and respects the request budget, so I can use it for GetAsync, UpdateAsync and the rest?

# Answer
Wrap the call the same way `pcall` does (function plus arguments), wait for budget before each attempt, and back off exponentially with jitter between failures. Return `ok, result` so the caller decides what a final failure means.

```lua
--!strict
-- ModuleScript: ServerScriptService.DataRetry
local DataStoreService = game:GetService("DataStoreService")

export type Options = {
	attempts: number?,
	baseDelay: number?,
	maxDelay: number?,
	requestType: EnumItem?, -- e.g. Enum.DataStoreRequestType.UpdateAsync
}

local random = Random.new()
local DataRetry = {}

local function waitForBudget(requestType: EnumItem, maxWait: number)
	local waited = 0
	while DataStoreService:GetRequestBudgetForRequestType(requestType) < 1 and waited < maxWait do
		waited += task.wait(0.5)
	end
end

-- Usage mirrors pcall: DataRetry.call(options, store.GetAsync, store, key)
function DataRetry.call(options: Options, fn: (...any) -> ...any, ...: any): (boolean, any)
	local attempts = options.attempts or 5
	local baseDelay = options.baseDelay or 1
	local maxDelay = options.maxDelay or 16
	local lastError: any = nil
	for attempt = 1, attempts do
		if options.requestType then
			waitForBudget(options.requestType, maxDelay)
		end
		local ok, result = pcall(fn, ...)
		if ok then
			return true, result
		end
		lastError = result
		if attempt < attempts then
			local delay = math.min(maxDelay, baseDelay * 2 ^ (attempt - 1))
			-- jitter keeps many servers from retrying in lockstep after an outage
			task.wait(delay * random:NextNumber(0.75, 1.25))
		end
	end
	return false, lastError
end

return DataRetry
```

Usage:

```lua
--!strict
local DataStoreService = game:GetService("DataStoreService")
local ServerScriptService = game:GetService("ServerScriptService")
local DataRetry = require(ServerScriptService.DataRetry)

local store = DataStoreService:GetDataStore("PlayerData")
local GET = { requestType = Enum.DataStoreRequestType.GetAsync }

local function load(userId: number): { [string]: any }?
	local ok, data = DataRetry.call(GET, store.GetAsync, store, "player_" .. userId)
	if not ok then
		warn("load failed for", userId, data)
		return nil
	end
	return data or { coins = 0 }
end

return load
```

- Passing `store.GetAsync, store, key` instead of a closure keeps the call itself inside `pcall`, so an error never escapes.
- Return `nil` on a final load failure and refuse to save that session; saving defaults over real data is how progress gets wiped.
- Keep total wait short for joins (3-4 attempts) and longer for saves on leave, where a few extra seconds cost nothing.

# Test
```lua
local ds = game:GetService("DataStoreService")
local store = ds:GetDataStore("RetryTest")
store:SetAsync("k", 5)

ds.__failNext = 2
local before = ds.__calls
local ok, value, finishedAt = nil, nil, nil
task.spawn(function()
	ok, value = item.call({}, store.GetAsync, store, "k")
	finishedAt = os.clock()
end)
check("still waiting after the first backoff", ok == nil)
__advance(20)
check("succeeds on the third attempt", ok and value == 5)
check("made exactly three calls", ds.__calls - before == 3)
check("backed off between attempts", finishedAt ~= nil and finishedAt >= 0.75 + 1.5)

ds.__failNext = 10
local ok2, err = nil, nil
task.spawn(function()
	ok2, err = item.call({ attempts = 3, requestType = Enum.DataStoreRequestType.GetAsync }, store.GetAsync, store, "k")
end)
__advance(30)
check("gives up after the attempt limit and returns the error", ok2 == false and string.find(tostring(err), "502") ~= nil)
ds.__failNext = 0

local ok3 = item.call({}, store.SetAsync, store, "k2", { coins = 1 })
local stored = store:GetAsync("k2")
check("works for writes too", ok3 and stored.coins == 1)
```
