The original code, unchanged.

```lua
-- Leaderboard: end-of-round table for the paintball scoreboard GUI.
-- entries = { { name = "Alex", kills = 7, deaths = 2 }, ... }
local Leaderboard = {}

function Leaderboard.kdr(entry)
	return entry.kills / entry.deaths
end

function Leaderboard.rank(entries)
	local list = table.clone(entries)
	table.sort(list, function(a, b)
		return a.kills < b.kills
	end)
	for i, entry in ipairs(list) do
		entry.rank = i
	end
	return list
end

function Leaderboard.top(entries, n)
	local ranked = Leaderboard.rank(entries)
	local out = {}
	for i = 1, math.min(n, #ranked) do
		out[i] = ranked[i]
	end
	return out
end

function Leaderboard.format(entry)
	return string.format("%d. %s  %d/%d  (%.2f)", entry.rank, entry.name, entry.kills, entry.deaths,
		Leaderboard.kdr(entry))
end

function Leaderboard.lines(entries)
	local rows = {}
	for _, entry in ipairs(Leaderboard.rank(entries)) do
		table.insert(rows, Leaderboard.format(entry))
	end
	return rows
end

function Leaderboard.mvp(entries)
	local ranked = Leaderboard.rank(entries)
	return ranked[1] and ranked[1].name or nil
end

return Leaderboard
```
