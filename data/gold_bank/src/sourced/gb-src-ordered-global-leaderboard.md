---
id: gb-src-ordered-global-leaderboard
category: datastore-safety
topics: OrderedDataStore, GetSortedAsync, pages, global leaderboard, pcall, refresh interval
source: adapted
source_id: creator-docs
source_path: content/en-us/cloud-services/data-stores/index.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I want an all-time "Top 10 Wins" board in my lobby that shows players from every server. I store wins per player in a normal data store. How do I build a global top list?

# Answer
Mirror each player's wins into an `OrderedDataStore` (integer values only) when they change, and read the top entries with `GetSortedAsync(false, 10)`, which returns pages sorted highest first. Refresh the board on a timer, not per player, and wrap both calls in `pcall`.

```lua
--!strict
local DataStoreService = game:GetService("DataStoreService")

local winsStore = DataStoreService:GetOrderedDataStore("AllTimeWins")

local Leaderboard = {}

export type Row = { rank: number, userId: number, wins: number }

function Leaderboard.recordWins(userId: number, wins: number): boolean
	local ok, err = pcall(function()
		winsStore:SetAsync(tostring(userId), math.floor(wins))
	end)
	if not ok then
		warn("Could not record wins:", err)
	end
	return ok
end

function Leaderboard.fetchTop(count: number): { Row }?
	local ok, pages = pcall(function()
		return winsStore:GetSortedAsync(false, count)
	end)
	if not ok then
		warn("Could not read leaderboard:", pages)
		return nil
	end
	local rows: { Row } = {}
	for rank, entry in pages:GetCurrentPage() do
		table.insert(rows, { rank = rank, userId = tonumber(entry.key) or 0, wins = entry.value })
	end
	return rows
end

return Leaderboard
```

Lobby script: `while true do local rows = Leaderboard.fetchTop(10) if rows then renderBoard(rows) end task.wait(60) end`.

- Ordered data stores only sort integers; `math.floor` makes sure a stray fraction does not make the write fail.
- `fetchTop` returns nil on failure so the board keeps showing the last good data instead of going blank.
- Sorted reads have their own budget; one refresh per minute per server is plenty for an all-time board.
- Look up names with `Players:GetNameFromUserIdAsync` (in `pcall`, cached) when rendering.

# Test
```lua
local DataStoreService = game:GetService("DataStoreService")
check("records wins", item.recordWins(1, 50) and item.recordWins(2, 75.9) and item.recordWins(3, 10))
local rows = item.fetchTop(2)
check("top rows sorted highest first", rows ~= nil and #rows == 2 and rows[1].userId == 2 and rows[1].wins == 75)
check("ranks numbered", rows ~= nil and rows[2].rank == 2 and rows[2].userId == 1)
DataStoreService.__failNext = 1
check("failure returns nil", item.fetchTop(10) == nil)
```
