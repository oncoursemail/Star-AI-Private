---
id: gb-src-datastore-retry-backoff
category: datastore-safety
topics: DataStoreService, UpdateAsync, retry, exponential backoff, jitter, pcall
source: adapted
source_id: creator-docs
source_path: content/en-us/cloud-services/data-stores/player-data-purchasing.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
My data store saves sometimes fail with throttling errors and players lose progress. How do I retry a save properly instead of just calling SetAsync once?

# Answer
Call the data store through `pcall` and retry a few times with exponential backoff plus random jitter, so many servers that failed at the same moment do not all retry in lockstep. Use `UpdateAsync` for the write: the transform receives the stored record, so it changes only the fields you own and keeps the rest.

```lua
--!strict
local DataStoreService = game:GetService("DataStoreService")

local MAX_ATTEMPTS = 5
local BASE_DELAY = 2
local MAX_DELAY = 32

local playerStore = DataStoreService:GetDataStore("PlayerData")

local function retryUpdateAsync(store: any, key: string, transform: (any) -> any): (boolean, any)
	local lastError: any = nil
	for attempt = 1, MAX_ATTEMPTS do
		local ok, result = pcall(store.UpdateAsync, store, key, transform)
		if ok then
			return true, result
		end
		lastError = result
		if attempt < MAX_ATTEMPTS then
			local backoff = math.min(MAX_DELAY, BASE_DELAY * 2 ^ (attempt - 1))
			task.wait(math.min(MAX_DELAY, backoff + math.random() * backoff))
		end
	end
	return false, lastError
end

local function saveCoins(userId: number, coins: number): boolean
	local ok, err = retryUpdateAsync(playerStore, "Player_" .. userId, function(old: { coins: number }?)
		local data = old or { coins = 0 }
		data.coins = coins
		return data
	end)
	if not ok then
		warn("Save failed for " .. userId .. ": " .. tostring(err))
	end
	return ok
end

return { retryUpdateAsync = retryUpdateAsync, saveCoins = saveCoins }
```

- Backoff doubles from 2 s up to a 32 s cap; jitter spreads out retries from many servers.
- `UpdateAsync` reads the current value inside the transform, so this save sets `coins` without wiping other fields of the record. It does not stop two servers from both writing the same player (fast server hops); that needs session locking, for example ProfileStore.
- The function reports whether the save succeeded, so the caller can keep the session dirty and try again on the next autosave.

# Test
```lua
local DataStoreService = game:GetService("DataStoreService")
local first, second
DataStoreService.__failNext = 2
task.spawn(function()
	first = item.saveCoins(1, 50)
end)
__advance(1)
check("still retrying after 1 s", first == nil)
__advance(200)
check("succeeds after two failures", first == true)
local ok, value = pcall(function()
	return DataStoreService:GetDataStore("PlayerData"):GetAsync("Player_1")
end)
check("value saved", ok and value ~= nil and value.coins == 50)
DataStoreService.__failNext = 5
task.spawn(function()
	second = item.saveCoins(2, 10)
end)
__advance(500)
check("gives up after five attempts", second == false)
```
