---
id: gb-data-ordered-leaderboard-pages
category: datastore-safety
topics: OrderedDataStore, leaderboard, GetSortedAsync, pages, high score
source: original
---
# Request
I want an all-time high score leaderboard showing the top 150 players. GetSortedAsync only gives me 100 at a time. How do I read several pages, and how should I submit scores so a worse run never lowers someone's best?

# Answer
Submit with `UpdateAsync` on the OrderedDataStore and return `nil` when the new score is not higher, which cancels the write. Read the top N by walking the pages until you have enough rows or the pages run out, with every call in `pcall`.

```lua
--!strict
-- ModuleScript: ServerScriptService.HighScores
local DataStoreService = game:GetService("DataStoreService")

local board = DataStoreService:GetOrderedDataStore("HighScores")
local PAGE_SIZE = 100

export type Row = { userId: number, score: number, rank: number }

local HighScores = {}

-- Ordered stores hold integers only; keep the best score per player.
function HighScores.submit(userId: number, score: number): boolean
	if score ~= score or score == math.huge or score < 0 then
		return false
	end
	local value = math.floor(score)
	local ok = pcall(function()
		board:UpdateAsync(tostring(userId), function(old: number?): number?
			if old and old >= value then
				return nil -- not a new best: cancel the write
			end
			return value
		end)
	end)
	return ok
end

function HighScores.top(count: number): { Row }
	local rows: { Row } = {}
	local ok, pages = pcall(function()
		return board:GetSortedAsync(false, math.min(count, PAGE_SIZE))
	end)
	if not ok then
		return rows
	end
	while #rows < count do
		for _, entry in pages:GetCurrentPage() do
			local userId = tonumber(entry.key)
			if userId and #rows < count then
				table.insert(rows, { userId = userId, score = entry.value, rank = #rows + 1 })
			end
		end
		if pages.IsFinished or #rows >= count then
			break
		end
		local advanced = pcall(function()
			pages:AdvanceToNextPageAsync()
		end)
		if not advanced then
			break -- show what we have rather than nothing
		end
	end
	return rows
end

return HighScores
```

- Refresh the board on a timer (every 60-120 seconds) and cache the rows; every viewer reading the store directly would burn the sorted-read budget.
- Keys are plain UserIds, so `tonumber(entry.key)` recovers the player; resolve names with `Players:GetNameFromUserIdAsync` in a `pcall` and cache them.
- For a weekly board, put the week number in the store name (`"HighScores_W" .. week`) and the old weeks simply stop being read.

# Test
```lua
for i = 1, 160 do
	item.submit(i, i * 10)
end
local rows = item.top(150)
check("reads past the first page", #rows == 150)
check("sorted best first", rows[1].userId == 160 and rows[1].score == 1600 and rows[150].userId == 11)
check("ranks are sequential", rows[1].rank == 1 and rows[150].rank == 150)

item.submit(160, 5)
check("a worse score does not lower the best", item.top(1)[1].score == 1600)

item.submit(1, 99999.7)
check("a new best moves up and is stored as an integer", item.top(1)[1].userId == 1 and item.top(1)[1].score == 99999)

check("NaN and negative scores are refused", not item.submit(2, 0 / 0) and not item.submit(3, -5))

game:GetService("DataStoreService").__failNext = 1
check("store outage returns an empty board, no error", #item.top(10) == 0)
```
