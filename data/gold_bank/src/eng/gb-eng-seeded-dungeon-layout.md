---
id: gb-eng-seeded-dungeon-layout
category: engineering-algorithm
topics: seeded generation, Random.new, determinism, procedural dungeon, daily seed
source: original
---
# Request
I want a "daily dungeon" where every server generates the same room layout for the day, and players can share a seed to replay a layout. My generator uses `math.random` and gives different results on each server. How do I make generation deterministic?

# Answer
Create one `Random.new(seed)` object per generation and draw every random value from it, in a fixed order. Derive the daily seed from the UTC date so all servers agree, and keep the generator pure (seed in, layout data out) so building parts happens separately.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.DungeonLayout
export type Room = { x: number, y: number, kind: "Start" | "Combat" | "Treasure" | "Boss" }

local DungeonLayout = {}

local DIRS = { { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } }

function DungeonLayout.dailySeed(unixTime: number): number
	local day = os.date("!*t", unixTime)
	return day.year * 10000 + day.month * 100 + day.day
end

function DungeonLayout.generate(seed: number, roomCount: number): { Room }
	local rng = Random.new(seed)
	local rooms: { Room } = { { x = 0, y = 0, kind = "Start" } }
	local taken: { [string]: boolean } = { ["0,0"] = true }
	local attempts = 0
	while #rooms < roomCount and attempts < roomCount * 50 do
		attempts += 1
		-- grow from a random existing room in a random direction (a random walk with branches)
		local from = rooms[rng:NextInteger(1, #rooms)]
		local dir = DIRS[rng:NextInteger(1, 4)]
		local x, y = from.x + dir[1], from.y + dir[2]
		local key = `{x},{y}`
		if taken[key] then
			continue
		end
		taken[key] = true
		local kind: "Combat" | "Treasure" = if rng:NextNumber() < 0.2 then "Treasure" else "Combat"
		table.insert(rooms, { x = x, y = y, kind = kind })
	end
	-- the boss goes in the room farthest (Manhattan) from the start
	local farthest, best = 2, -1
	for i = 2, #rooms do
		local d = math.abs(rooms[i].x) + math.abs(rooms[i].y)
		if d > best then
			farthest, best = i, d
		end
	end
	if #rooms > 1 then
		rooms[farthest].kind = "Boss"
	end
	return rooms
end

return DungeonLayout
```

- `Random.new(seed)` has its own state, so other scripts calling `math.random` cannot shift the sequence; with `math.random` any unrelated call changes every room after it.
- `os.date("!*t", t)` uses UTC (the `!`), so servers in different regions produce the same seed at the same moment; pass `os.time()` or `DateTime.now().UnixTimestamp`.
- Determinism holds only while the draw order is fixed: add new random choices at the end of generation, or older seeds will produce different layouts after an update.

# Test
```lua
local a = item.generate(20261020, 15)
local b = item.generate(20261020, 15)
local same = #a == #b
for i, room in a do
	if b[i].x ~= room.x or b[i].y ~= room.y or b[i].kind ~= room.kind then
		same = false
	end
end
check("same seed same layout", same and #a == 15)
local c = item.generate(42, 15)
local differs = false
for i, room in a do
	if c[i].x ~= room.x or c[i].y ~= room.y then
		differs = true
	end
end
check("different seed differs", differs)
local seen, unique, bosses = {}, true, 0
for _, room in a do
	local k = room.x .. "," .. room.y
	if seen[k] then
		unique = false
	end
	seen[k] = true
	if room.kind == "Boss" then
		bosses += 1
	end
end
check("rooms unique and one boss", unique and bosses == 1 and a[1].kind == "Start")
check("daily seed from UTC date", item.dailySeed(1760918400) == 20251020)
check("single room dungeon", #item.generate(1, 1) == 1 and item.generate(1, 1)[1].kind == "Start")
```
