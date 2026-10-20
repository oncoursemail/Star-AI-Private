---
id: gb-eng-spatial-hash-neighbours
category: engineering-algorithm
topics: spatial hash, neighbour query, broad phase, boids, performance
source: original
---
# Request
I have about 400 fish that each need to find neighbours within 12 studs every frame for flocking. Checking every pair is 160k distance checks and kills the frame rate. What data structure should I use? The fish are plain tables with a position, not parts.

# Answer
A uniform spatial hash: bucket each entity by the cell its position falls in, with cell size equal to the query radius. A radius query then only looks at the 3x3x3 block of cells around the point, so each fish checks a handful of others instead of all 400.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.SpatialHash
export type SpatialHash<T> = {
	cellSize: number,
	cells: { [number]: { T } },
	positions: { [T]: Vector3 },
}

local SpatialHash = {}

-- cell coordinates packed into one exact integer key (each axis must stay within +-65536 cells)
local AXIS = 131072
local function cellKey(x: number, y: number, z: number): number
	return ((x + 65536) * AXIS + (y + 65536)) * AXIS + (z + 65536)
end

local function cellOf(cellSize: number, p: Vector3): (number, number, number)
	local x: number, y: number, z: number = p.X, p.Y, p.Z
	return x // cellSize, y // cellSize, z // cellSize
end

function SpatialHash.new<T>(cellSize: number): SpatialHash<T>
	assert(cellSize > 0, "cell size must be positive")
	return { cellSize = cellSize, cells = {}, positions = {} }
end

function SpatialHash.clear<T>(hash: SpatialHash<T>): ()
	table.clear(hash.cells)
	table.clear(hash.positions)
end

function SpatialHash.insert<T>(hash: SpatialHash<T>, entity: T, position: Vector3): ()
	local c = cellKey(cellOf(hash.cellSize, position))
	local bucket = hash.cells[c]
	if bucket == nil then
		bucket = {}
		hash.cells[c] = bucket
	end
	table.insert(bucket, entity)
	hash.positions[entity] = position
end

function SpatialHash.queryRadius<T>(hash: SpatialHash<T>, center: Vector3, radius: number, out: { T }): { T }
	table.clear(out)
	local x0, y0, z0 = cellOf(hash.cellSize, center - Vector3.one * radius)
	local x1, y1, z1 = cellOf(hash.cellSize, center + Vector3.one * radius)
	local r2 = radius * radius
	for x = x0, x1 do
		for y = y0, y1 do
			for z = z0, z1 do
				local bucket = hash.cells[cellKey(x, y, z)]
				if bucket == nil then
					continue
				end
				for _, entity in bucket do
					local offset = hash.positions[entity] - center
					if offset:Dot(offset) <= r2 then
						table.insert(out, entity)
					end
				end
			end
		end
	end
	return out
end

return SpatialHash
```

- Rebuild once per frame (`clear` then `insert` every fish) rather than moving entries between buckets; for a few hundred entities that is cheaper and has no stale-cell bugs.
- Packing the three cell coordinates into one number gives an exact, collision-free key with cheap hashing; with 12-stud cells the range covers far more than any map.
- `queryRadius` fills a caller-owned `out` table, so the per-frame loop reuses one list instead of allocating 400 new tables a frame. Comparing squared distance with `Dot` avoids a square root per pair.

# Test
```lua
local hash = item.new(12)
local fish = {}
for i = 1, 50 do
	local f = { id = i }
	fish[i] = f
	item.insert(hash, f, Vector3.new(i * 5, 0, 0))
end
local out = {}
item.queryRadius(hash, Vector3.new(100, 0, 0), 12, out)
local ids = {}
for _, f in out do
	ids[f.id] = true
end
check("finds neighbours within radius", ids[18] and ids[20] and ids[22] and not ids[17] and not ids[23])
local count = #out
check("exact count", count == 5)
item.queryRadius(hash, Vector3.new(-500, 0, 0), 12, out)
check("reused out table cleared", #out == 0)
item.insert(hash, { id = 99 }, Vector3.new(-6, 0, 0))
item.queryRadius(hash, Vector3.new(-1, 0, 0), 6, out)
check("negative coordinates across cell edge", #out == 2)
item.clear(hash)
item.queryRadius(hash, Vector3.new(100, 0, 0), 12, out)
check("clear empties", #out == 0)
```
