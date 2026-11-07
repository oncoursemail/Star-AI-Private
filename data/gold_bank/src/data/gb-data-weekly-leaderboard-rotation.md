---
id: gb-data-weekly-leaderboard-rotation
category: datastore-safety
topics: OrderedDataStore, weekly leaderboard, reset, IncrementAsync, store naming
source: original
---
# Request
I want a weekly kills leaderboard that resets every Monday, plus showing last week's winners. Do I need to delete everyone's entries at the reset?

# Answer
No deletion needed: put the week number in the OrderedDataStore name. Every server computes the same week index from UTC time, so on Monday they all start writing to a fresh store automatically, and "last week" is just the previous index. Kills are added with `IncrementAsync`, batched per player so a busy fight is not one write per kill.

```lua
--!strict
-- ModuleScript: ServerScriptService.WeeklyKills
local DataStoreService = game:GetService("DataStoreService")

local WEEK = 7 * 24 * 3600
local EPOCH_MONDAY = 345600 -- 1970-01-05 00:00 UTC, the first Monday after the Unix epoch

local WeeklyKills = {}
local pending: { [number]: number } = {}

function WeeklyKills.weekIndex(now: number): number
	return (now - EPOCH_MONDAY) // WEEK
end

local function boardFor(week: number): OrderedDataStore
	return DataStoreService:GetOrderedDataStore("WeeklyKills_" .. week)
end

function WeeklyKills.addKill(userId: number)
	pending[userId] = (pending[userId] or 0) + 1
end

-- Called every 30-60 seconds and on leave/shutdown. Failed increments stay pending.
function WeeklyKills.flush(now: number)
	local board = boardFor(WeeklyKills.weekIndex(now))
	local batch = pending
	pending = {} -- kills during the flush go into the fresh table
	for userId, count in batch do
		local ok = pcall(function()
			board:IncrementAsync(tostring(userId), count)
		end)
		if not ok then
			pending[userId] = (pending[userId] or 0) + count
		end
	end
end

function WeeklyKills.top(now: number, weeksAgo: number, count: number): { { userId: number, kills: number } }
	local rows = {}
	local ok, pages = pcall(function()
		return boardFor(WeeklyKills.weekIndex(now) - weeksAgo):GetSortedAsync(false, count)
	end)
	if ok then
		for _, entry in pages:GetCurrentPage() do
			table.insert(rows, { userId = tonumber(entry.key) or 0, kills = entry.value })
		end
	end
	return rows
end

return WeeklyKills
```

- Old weekly stores simply stop being read; there is no reset job to fail halfway through.
- Kills earned just before midnight Sunday and flushed just after land in the new week; flush often enough (30 s) that this edge does not matter for your game.
- Swapping `pending` for a fresh table before the loop means kills recorded while a flush yields, and failed increments put back, never modify the table being iterated.

# Test
```lua
local monday = 1_700_438_400 -- 2023-11-20 00:00 UTC, a Monday
check("Sunday night and Monday morning are different weeks", item.weekIndex(monday - 1) + 1 == item.weekIndex(monday))
check("the whole week shares an index", item.weekIndex(monday) == item.weekIndex(monday + 6 * 86400 + 86399))

item.addKill(1)
item.addKill(1)
item.addKill(2)
item.flush(monday - 100)
local lastWeek = item.top(monday + 10, 1, 10)
check("kills land in the week they were flushed", #lastWeek == 2 and lastWeek[1].userId == 1 and lastWeek[1].kills == 2)
check("the new week starts empty", #item.top(monday + 10, 0, 10) == 0)

item.addKill(2)
game:GetService("DataStoreService").__failNext = 1
item.flush(monday + 20)
check("a failed flush keeps the kill pending", #item.top(monday + 20, 0, 10) == 0)
item.flush(monday + 40)
local thisWeek = item.top(monday + 40, 0, 10)
check("and the next flush writes it", #thisWeek == 1 and thisWeek[1].userId == 2 and thisWeek[1].kills == 1)
```
