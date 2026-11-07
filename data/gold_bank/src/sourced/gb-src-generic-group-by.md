---
id: gb-src-generic-group-by
category: luau-typing
topics: generics, type parameters, higher-order functions, groupBy, inference, utility module
source: adapted
source_id: luau-site
source_path: src/content/docs/types/generics.md
source_commit: 41db794d9ee6e56a17b399f8a4520b92301fee59
---
# Request
I keep writing the same loops to group things: players by team, items by rarity, enemies by zone. I want one `groupBy` helper and a `maxBy` helper that stay fully typed, so the result for players is a table of player lists, not `any`. How do I write these with Luau generics?

# Answer
Declare type parameters on the function: `groupBy<T, K>` takes a list of `T` and a key function `T -> K`, and returns `{ [K]: { T } }`. Luau infers `T` and `K` at each call site, so the results keep their element types.

```lua
--!strict
local Collections = {}

function Collections.groupBy<T, K>(list: { T }, keyOf: (T) -> K): { [K]: { T } }
	local groups: { [K]: { T } } = {}
	for _, value in list do
		local key = keyOf(value)
		local bucket = groups[key]
		if bucket == nil then
			bucket = {}
			groups[key] = bucket
		end
		table.insert(bucket, value)
	end
	return groups
end

function Collections.maxBy<T>(list: { T }, score: (T) -> number): (T?, number)
	local best: T? = nil
	local bestScore = -math.huge
	for _, value in list do
		local s = score(value)
		if s > bestScore then
			best, bestScore = value, s
		end
	end
	return best, bestScore
end

return Collections
```

Usage:

```lua
--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Collections = require(ReplicatedStorage:WaitForChild("Collections"))

type Loot = { name: string, rarity: string, value: number }

local loot: { Loot } = {
	{ name = "Stick", rarity = "Common", value = 1 },
	{ name = "Crown", rarity = "Legendary", value = 500 },
	{ name = "Rock", rarity = "Common", value = 2 },
}

local byRarity = Collections.groupBy(loot, function(entry: Loot): string
	return entry.rarity
end)
local best = Collections.maxBy(loot, function(entry: Loot): number
	return entry.value
end)
print(#byRarity.Common, if best then best.name else "none")

local byTeam = Collections.groupBy(Players:GetPlayers(), function(player: Player): string
	return if player.Team then player.Team.Name else "Neutral"
end)
print(byTeam)
```

- The key function's parameter type comes from the list, so a typo like `entry.rarty` is a type error at the call.
- `maxBy` returns `T?` because an empty list has no maximum; callers must handle nil.
- The key function must never return nil (a table index cannot be nil), which is why players without a team map to `"Neutral"`.
- Both helpers are O(n) and allocate one table per group.

# Test
```lua
local words = { "apple", "avocado", "banana", "blueberry", "cherry" }
local groups = item.groupBy(words, function(w)
	return string.sub(w, 1, 1)
end)
check("grouped by first letter", #groups.a == 2 and #groups.b == 2 and #groups.c == 1)
check("order kept inside a group", groups.b[1] == "banana")
local longest, len = item.maxBy(words, function(w)
	return #w
end)
check("maxBy finds the longest", longest == "blueberry" and len == 9)
local none = item.maxBy({}, function()
	return 0
end)
check("empty list gives nil", none == nil)
```
