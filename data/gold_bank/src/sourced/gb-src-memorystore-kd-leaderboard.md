---
id: gb-src-memorystore-kd-leaderboard
category: messaging
topics: MemoryStoreService, sorted map, UpdateAsync, sort key, GetRangeAsync, cross-server leaderboard
source: adapted
source_id: creator-docs
source_path: content/en-us/cloud-services/memory-stores/sorted-map.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I want a live cross-server leaderboard of kill/death ratio for the current event. It doesn't need to be saved forever. How do I do that with MemoryStore?

# Answer
Use a memory store sorted map: each entry's value holds the raw kills and deaths, and the sort key is the ratio, so `GetRangeAsync` with `Descending` returns the top players directly. `UpdateAsync` makes concurrent updates from different servers safe.

```lua
--!strict
local MemoryStoreService = game:GetService("MemoryStoreService")

local EXPIRATION_SECONDS = 60 * 60
local leaderboard = MemoryStoreService:GetSortedMap("EventKD")

type Stats = { kills: number, deaths: number }

local function addStats(userId: number, kills: number, deaths: number): boolean
	local ok, err = pcall(function()
		leaderboard:UpdateAsync(tostring(userId), function(old: Stats?, _oldSortKey: number?)
			local stats: Stats = old or { kills = 0, deaths = 0 }
			stats.kills += kills
			stats.deaths += deaths
			return stats, stats.kills / math.max(stats.deaths, 1)
		end, EXPIRATION_SECONDS)
	end)
	if not ok then
		warn("Leaderboard update failed:", err)
	end
	return ok
end

local function getTop(count: number): { { userId: number, ratio: number } }
	local ok, items = pcall(function()
		return leaderboard:GetRangeAsync(Enum.SortDirection.Descending, count)
	end)
	local top = {}
	if ok then
		for _, item in items do
			table.insert(top, { userId = tonumber(item.key) or 0, ratio = item.sortKey })
		end
	end
	return top
end

return { addStats = addStats, getTop = getTop }
```

- The transform returns `value, sortKey`; the map keeps entries ordered by the sort key across all servers.
- The expiration refreshes on each update, so the board clears itself an hour after the event ends.
- Poll `getTop` every few seconds per server, not per player, to stay inside the request quota.
