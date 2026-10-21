Reference fix.

```lua
-- Leaderboard: end-of-round table for the paintball scoreboard GUI.
-- entries = { { name = "Alex", kills = 7, deaths = 2 }, ... }
local Leaderboard = {}

function Leaderboard.kdr(entry)
	if entry.deaths == 0 then
		return entry.kills
	end
	return entry.kills / entry.deaths
end

function Leaderboard.rank(entries)
	local list = {}
	for i, entry in ipairs(entries) do
		list[i] = table.clone(entry)
	end
	table.sort(list, function(a, b)
		if a.kills ~= b.kills then
			return a.kills > b.kills
		end
		if a.deaths ~= b.deaths then
			return a.deaths < b.deaths
		end
		return a.name < b.name
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
	local lines = {}
	for _, entry in ipairs(Leaderboard.rank(entries)) do
		table.insert(lines, Leaderboard.format(entry))
	end
	return lines
end

function Leaderboard.mvp(entries)
	local ranked = Leaderboard.rank(entries)
	return ranked[1] and ranked[1].name or nil
end

return Leaderboard
```
