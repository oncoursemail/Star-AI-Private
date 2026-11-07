---
id: gb-eng-iter-metamethod-collection
category: luau-syntax
topics: generalized iteration, __iter, pairs ipairs, custom collection, sorted iteration
source: original
---
# Request
I see code like `for k, v in someTable do` with no `pairs` or `ipairs`. How does that work, and can I make my own leaderboard class iterable that way so `for rank, entry in board do` gives entries sorted by score?

# Answer
Luau's generalized iteration calls the `__iter` metamethod if the value has one, otherwise it iterates the table like `pairs` (array part in order first). Give the class an `__iter` that returns a stateless iterator over a sorted snapshot.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Leaderboard
export type Entry = { name: string, score: number }

local Leaderboard = {}
Leaderboard.__index = Leaderboard

type Fields = { _scores: { [string]: number } }
export type Leaderboard = typeof(setmetatable({} :: Fields, Leaderboard))

function Leaderboard.new(): Leaderboard
	return setmetatable({ _scores = {} } :: Fields, Leaderboard)
end

function Leaderboard.add(self: Leaderboard, name: string, points: number): ()
	self._scores[name] = (self._scores[name] or 0) + points
end

function Leaderboard.sorted(self: Leaderboard): { Entry }
	local list: { Entry } = {}
	for name, score in self._scores do
		table.insert(list, { name = name, score = score })
	end
	table.sort(list, function(a: Entry, b: Entry): boolean
		if a.score ~= b.score then
			return a.score > b.score
		end
		return a.name < b.name
	end)
	return list
end

function Leaderboard.__iter(self: Leaderboard)
	local list = Leaderboard.sorted(self)
	local function step(entries: { Entry }, rank: number): (number?, Entry?)
		local nextRank = rank + 1
		local entry = entries[nextRank]
		if entry == nil then
			return nil, nil
		end
		return nextRank, entry
	end
	return step, list, 0
end

return Leaderboard
```

- `for rank, entry in board do` now yields `1, {name, score}`, `2, ...` in score order; ties break by name so the order is stable between refreshes.
- Plain tables need no `pairs`/`ipairs`: `for i, v in list do` walks the array part in order, then the hash part.
- `__iter` builds a snapshot, so adding scores during the loop does not disturb the iteration.

# Test
```lua
local board = item.new()
board:add("Bo", 10)
board:add("Ana", 25)
board:add("Cy", 10)
board:add("Bo", 5)
local order = {}
for rank, entry in board do
	order[rank] = entry.name .. "=" .. entry.score
end
check("sorted by score", order[1] == "Ana=25" and order[2] == "Bo=15")
check("third place", order[3] == "Cy=10")
check("exactly three entries", #order == 3)
local empty = item.new()
local count = 0
for _ in empty do
	count += 1
end
check("empty board iterates zero times", count == 0)
```
