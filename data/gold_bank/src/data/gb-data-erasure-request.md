---
id: gb-data-erasure-request
category: datastore-safety
topics: DataStore, right to erasure, RemoveAsync, privacy, OrderedDataStore
source: original
---
# Request
I got a "Right to Erasure" request from Roblox for a UserId. My game keeps data in a few stores: PlayerData, Settings, and an ordered Wins leaderboard. How do I delete everything for that user reliably and know whether it worked?

# Answer
List every store and key pattern your game writes for a user in one place, then remove each key with `RemoveAsync` and retries, and return a report per key. Run it from a server-side admin command or the command bar in a live server, and rerun it until every key reports removed.

```lua
--!strict
-- ModuleScript: ServerScriptService.Erasure
local DataStoreService = game:GetService("DataStoreService")

type Target = { store: GlobalDataStore, key: (userId: number) -> string, label: string }

-- Every place the game stores data for a user. Update this list whenever you add a store.
local TARGETS: { Target } = {
	{ store = DataStoreService:GetDataStore("PlayerData"), label = "PlayerData", key = function(id: number): string
		return "player_" .. id
	end },
	{ store = DataStoreService:GetDataStore("Settings"), label = "Settings", key = function(id: number): string
		return tostring(id)
	end },
	{ store = DataStoreService:GetOrderedDataStore("Wins"), label = "Wins", key = function(id: number): string
		return tostring(id)
	end },
}

export type Report = { [string]: boolean }

local Erasure = {}

local function removeWithRetry(store: GlobalDataStore, key: string): boolean
	for attempt = 1, 4 do
		local ok = pcall(function()
			store:RemoveAsync(key)
		end)
		if ok then
			return true
		end
		task.wait(2 ^ attempt)
	end
	return false
end

function Erasure.eraseUser(userId: number): (boolean, Report)
	assert(type(userId) == "number" and userId > 0 and userId % 1 == 0, "eraseUser needs a positive integer UserId")
	local report: Report = {}
	local allOk = true
	for _, target in TARGETS do
		local removed = removeWithRetry(target.store, target.key(userId))
		report[target.label] = removed
		allOk = allOk and removed
	end
	return allOk, report
end

return Erasure
```

- `RemoveAsync` marks the key deleted; older versions expire on Roblox's side after the retention window, so you do not need to delete versions by hand.
- Data kept under someone else's key (a trade log mentioning this user, a guild member list) also counts: strip the UserId from those records with `UpdateAsync`.
- Passing `{ userId }` as the user-ids argument on every `SetAsync`/`UpdateAsync` keeps these keys tagged to the player, which makes future requests easier to audit.

# Test
```lua
local ds = game:GetService("DataStoreService")
ds:GetDataStore("PlayerData"):SetAsync("player_77", { coins = 5 })
ds:GetDataStore("Settings"):SetAsync("77", { music = false })
ds:GetOrderedDataStore("Wins"):SetAsync("77", 12)
ds:GetDataStore("PlayerData"):SetAsync("player_78", { coins = 9 })

local ok, report = nil, nil
task.spawn(function()
	ok, report = item.eraseUser(77)
end)
__advance(0)
check("all stores report removed", ok == true and report.PlayerData and report.Settings and report.Wins)
check("player data is gone", ds:GetDataStore("PlayerData"):GetAsync("player_77") == nil)
check("leaderboard entry is gone", ds:GetOrderedDataStore("Wins"):GetAsync("77") == nil)
check("other users are untouched", ds:GetDataStore("PlayerData"):GetAsync("player_78").coins == 9)

ds.__failNext = 2
local ok2, report2 = nil, nil
task.spawn(function()
	ok2, report2 = item.eraseUser(78)
end)
__advance(60)
check("transient failures are retried", ok2 == true and report2.PlayerData == true)

check("rejects a bad UserId", not pcall(item.eraseUser, -1))
```
