---
id: gb-eng-tdd-matchmaking-buckets
category: engineering-test-first
topics: test-first, matchmaking, rating buckets, grouping, fairness
source: original
test_block: 2
---
# Request
Test-first: I need a function that takes the queued players with a skill rating and splits them into matches of exactly `size` players, keeping ratings in each match close. Leftover players (not enough for a full match) stay in the queue. A match is not allowed if its rating spread is more than `maxSpread`, unless the oldest player in it has waited longer than `relaxAfter` seconds.

# Answer
Specify the behaviour as examples first: exact-size matches, leftovers, spread limit, and the wait-time relaxation. The implementation sorts by rating and slides a window of `size` players, taking the tightest valid windows first.

```lua
--!strict
-- Script: ServerScriptService.Tests.MatchmakerSpec
local Matchmaker = require(game:GetService("ServerScriptService").Matchmaker)

local failures = 0
local function test(name: string, fn: () -> ())
	local ok, err = pcall(fn)
	if not ok then
		failures += 1
		warn(`FAIL {name}: {err}`)
	end
end

local function q(id: number, rating: number, waited: number?)
	return { id = id, rating = rating, waited = waited or 0 }
end

test("groups close ratings into full matches", function()
	local matches, rest = Matchmaker.form({ q(1, 1000), q(2, 1500), q(3, 1010), q(4, 1490) }, 2, 100, 30)
	assert(#matches == 2 and #rest == 0)
end)
test("leftovers stay queued", function()
	local matches, rest = Matchmaker.form({ q(1, 1000), q(2, 1005), q(3, 1010) }, 2, 100, 30)
	assert(#matches == 1 and #rest == 1)
end)
test("spread limit blocks unfair matches", function()
	local matches = Matchmaker.form({ q(1, 1000), q(2, 1800) }, 2, 100, 30)
	assert(#matches == 0)
end)
test("long wait relaxes the limit", function()
	local matches = Matchmaker.form({ q(1, 1000, 45), q(2, 1800) }, 2, 100, 30)
	assert(#matches == 1)
end)
test("waiting exactly relaxAfter is not longer than it", function()
	local matches = Matchmaker.form({ q(1, 1000, 30), q(2, 1800) }, 2, 100, 30)
	assert(#matches == 0)
end)

print(`Matchmaker spec: {failures} failure(s)`)
```

```lua
--!strict
-- ModuleScript: ServerScriptService.Matchmaker
export type Queued = { id: number, rating: number, waited: number }

local Matchmaker = {}

function Matchmaker.form(queue: { Queued }, size: number, maxSpread: number, relaxAfter: number): ({ { Queued } }, { Queued })
	local sorted = table.clone(queue)
	table.sort(sorted, function(a: Queued, b: Queued): boolean
		return a.rating < b.rating
	end)

	-- every window of `size` neighbours in rating order is a candidate match
	type Candidate = { start: number, spread: number }
	local candidates: { Candidate } = {}
	for start = 1, #sorted - size + 1 do
		local spread = sorted[start + size - 1].rating - sorted[start].rating
		local longestWait = 0
		for i = start, start + size - 1 do
			longestWait = math.max(longestWait, sorted[i].waited)
		end
		if spread <= maxSpread or longestWait > relaxAfter then
			table.insert(candidates, { start = start, spread = spread })
		end
	end
	table.sort(candidates, function(a: Candidate, b: Candidate): boolean
		return a.spread < b.spread
	end)

	local used: { [number]: boolean } = {}
	local matches: { { Queued } } = {}
	for _, c in candidates do
		local free = true
		for i = c.start, c.start + size - 1 do
			if used[i] then
				free = false
				break
			end
		end
		if free then
			local match: { Queued } = {}
			for i = c.start, c.start + size - 1 do
				used[i] = true
				table.insert(match, sorted[i])
			end
			table.insert(matches, match)
		end
	end

	local rest: { Queued } = {}
	for i, player in sorted do
		if not used[i] then
			table.insert(rest, player)
		end
	end
	return matches, rest
end

return Matchmaker
```

- Contiguous windows over the sorted list are enough: the tightest group of `size` players is always a run of neighbours in rating order.
- Taking the smallest spreads first is greedy, not optimal for every queue, but it is predictable and fast enough to run every few seconds on hundreds of players.
- `waited` is computed on the server from when each player entered the queue; the wait relaxation stops high-rated players at off-peak hours from waiting forever.

# Test
```lua
local function q(id, rating, waited)
	return { id = id, rating = rating, waited = waited or 0 }
end
local m1, r1 = item.form({ q(1, 1000), q(2, 1500), q(3, 1010), q(4, 1490) }, 2, 100, 30)
local pairsOk = #m1 == 2
for _, m in m1 do
	if math.abs(m[1].rating - m[2].rating) > 20 then
		pairsOk = false
	end
end
check("close ratings paired", pairsOk and #r1 == 0)
local m2, r2 = item.form({ q(1, 1000), q(2, 1005), q(3, 1010) }, 2, 100, 30)
check("leftover queued", #m2 == 1 and #r2 == 1)
check("spread limit", #item.form({ q(1, 1000), q(2, 1800) }, 2, 100, 30) == 0)
check("wait relaxes", #item.form({ q(1, 1000, 45), q(2, 1800) }, 2, 100, 30) == 1)
check("relaxes only when waited longer than relaxAfter", #item.form({ q(1, 1000, 30), q(2, 1800) }, 2, 100, 30) == 0)
local m3, r3 = item.form({ q(1, 1), q(2, 2), q(3, 3), q(4, 4), q(5, 5), q(6, 6), q(7, 7) }, 3, 10, 30)
check("matches of exact size", #m3 == 2 and #m3[1] == 3 and #m3[2] == 3 and #r3 == 1)
check("empty queue", #item.form({}, 2, 100, 30) == 0)
```
