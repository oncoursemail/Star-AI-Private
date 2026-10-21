---
id: gb-eng-grid-index-floor-division
category: luau-syntax
topics: floor division, compound assignment, grid index, tile map, luau operators
source: original
---
# Request
For my farming plot I store tiles in a flat array and convert between `(x, y)` and an index with `math.floor((i - 1) / width)` and `(i - 1) % width`. It works, but someone told me Luau has `//` and `+=` now. Can you clean up this tile grid using them, and convert world positions to tiles too?

# Answer
`a // b` is floor division (same as `math.floor(a / b)`, including for negatives) and `x += 1` style compound assignment evaluates the target once. Both fit index math well.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.TileGrid
export type TileGrid = {
	width: number,
	height: number,
	tileSize: number,
	origin: Vector3,
	tiles: { number },
}

local TileGrid = {}

function TileGrid.new(width: number, height: number, tileSize: number, origin: Vector3): TileGrid
	return { width = width, height = height, tileSize = tileSize, origin = origin, tiles = table.create(width * height, 0) }
end

function TileGrid.toIndex(grid: TileGrid, x: number, y: number): number?
	if x < 0 or y < 0 or x >= grid.width or y >= grid.height then
		return nil
	end
	return y * grid.width + x + 1
end

function TileGrid.fromIndex(grid: TileGrid, index: number): (number, number)
	local zeroBased = index - 1
	return zeroBased % grid.width, zeroBased // grid.width
end

function TileGrid.worldToTile(grid: TileGrid, position: Vector3): (number, number)
	local offset = position - grid.origin
	return offset.X // grid.tileSize, offset.Z // grid.tileSize
end

function TileGrid.addGrowth(grid: TileGrid, x: number, y: number, amount: number): boolean
	local index = TileGrid.toIndex(grid, x, y)
	if index == nil then
		return false
	end
	grid.tiles[index] += amount
	grid.tiles[index] = math.min(grid.tiles[index], 100)
	return true
end

return TileGrid
```

- `//` floors toward negative infinity, so a position 0.5 studs left of the origin maps to tile `-1`, not `0`; `toIndex` then rejects it instead of wrapping onto the wrong row.
- `grid.tiles[index] += amount` indexes `grid.tiles` once; with longer expressions such as `self.cache[key()] += 1` that avoids calling `key()` twice.
- `table.create(n, 0)` preallocates the array, which matters for big plots that are filled right away.

# Test
```lua
local g = item.new(4, 3, 5, Vector3.new(100, 0, 100))
check("index round trip", select(1, item.fromIndex(g, item.toIndex(g, 3, 2))) == 3 and select(2, item.fromIndex(g, item.toIndex(g, 3, 2))) == 2)
check("first and last index", item.toIndex(g, 0, 0) == 1 and item.toIndex(g, 3, 2) == 12)
check("out of bounds rejected", item.toIndex(g, 4, 0) == nil and item.toIndex(g, -1, 0) == nil)
local tx, ty = item.worldToTile(g, Vector3.new(112, 0, 104.9))
check("world to tile", tx == 2 and ty == 0)
local nx = item.worldToTile(g, Vector3.new(99.5, 0, 100))
check("negative offset floors to -1", nx == -1)
check("growth adds and caps", item.addGrowth(g, 1, 1, 70) and item.addGrowth(g, 1, 1, 70) and g.tiles[item.toIndex(g, 1, 1)] == 100)
check("growth out of grid fails", not item.addGrowth(g, 9, 9, 1))
```
