---
id: gb-data-remote-grid-placement
category: remote-security
topics: building placement, grid, plot bounds, RemoteEvent, server authority
source: original
---
# Request
In my tycoon, players place furniture on their plot. The client sends the CFrame of the preview model and the server clones the item there. People are placing things inside other plots, floating in the sky and rotated sideways. How should placement work?

# Answer
Do not accept a CFrame at all. The client sends intent in grid terms (item id, cell x, cell z, rotation step 0-3), and the server checks the item exists, the cell is inside the player's plot, the cells are free in a server-side occupancy map, then builds the CFrame itself from the plot origin.

```lua
--!strict
-- ModuleScript: ServerScriptService.PlotGrid
export type ItemDef = { width: number, depth: number }
export type Plot = {
	ownerId: number,
	origin: CFrame,       -- corner of the plot, Y at floor level
	cellsX: number,
	cellsZ: number,
	occupied: { [string]: boolean },
}

local CELL = 4 -- studs

local PlotGrid = {}

local function cellKey(x: number, z: number): string
	return x .. ":" .. z
end

local function isInt(n: unknown, lo: number, hi: number): boolean
	return type(n) == "number" and n % 1 == 0 and n >= lo and n <= hi
end

-- Returns the world CFrame for the placement, or nil and a reason. Marks the cells as used on success.
function PlotGrid.place(plot: Plot, userId: number, def: ItemDef?, xArg: unknown, zArg: unknown, rotArg: unknown): (CFrame?, string?)
	if plot.ownerId ~= userId then
		return nil, "not your plot"
	end
	if def == nil or not isInt(rotArg, 0, 3) then
		return nil, "bad request"
	end
	local rotation = rotArg :: number
	local width = if rotation % 2 == 0 then def.width else def.depth
	local depth = if rotation % 2 == 0 then def.depth else def.width
	if not isInt(xArg, 0, plot.cellsX - width) or not isInt(zArg, 0, plot.cellsZ - depth) then
		return nil, "out of bounds"
	end
	local x, z = xArg :: number, zArg :: number
	for dx = 0, width - 1 do
		for dz = 0, depth - 1 do
			if plot.occupied[cellKey(x + dx, z + dz)] then
				return nil, "blocked"
			end
		end
	end
	for dx = 0, width - 1 do
		for dz = 0, depth - 1 do
			plot.occupied[cellKey(x + dx, z + dz)] = true
		end
	end
	local center = Vector3.new((x + width / 2) * CELL, 0, (z + depth / 2) * CELL)
	return plot.origin * CFrame.new(center) * CFrame.Angles(0, math.rad(90 * rotation), 0), nil
end

return PlotGrid
```

The remote handler looks the item up in a server table (`ITEMS[itemId]`) and the plot in a server map keyed by the player, then calls `place` and clones the model to the returned CFrame.

- The client can only choose among valid placements; no CFrame it could forge ever reaches the server.
- The occupancy map is the source of truth for overlap; it is faster and more exact than a physics query, and it is what you save.
- Rotation 1 and 3 swap width and depth, so a 2x1 table rotated 90 degrees still has to fit the plot.

# Test
```lua
local plot = { ownerId = 7, origin = CFrame.new(100, 0, 100), cellsX = 10, cellsZ = 10, occupied = {} }
local table2x1 = { width = 2, depth = 1 }

local cf = item.place(plot, 7, table2x1, 0, 0, 0)
check("valid placement returns a world CFrame inside the plot", cf ~= nil and cf.Position == Vector3.new(104, 0, 102))
local _, why = item.place(plot, 7, table2x1, 1, 0, 0)
check("overlapping placement is blocked", why == "blocked")
local _, other = item.place(plot, 8, table2x1, 5, 5, 0)
check("placing on someone else's plot is refused", other == "not your plot")
local _, edge = item.place(plot, 7, table2x1, 9, 0, 0)
check("items cannot hang off the edge", edge == "out of bounds")
local rotated = item.place(plot, 7, table2x1, 9, 3, 1)
check("rotation swaps the footprint", rotated ~= nil)
local _, badRot = item.place(plot, 7, table2x1, 4, 4, 1.5)
local _, badCell = item.place(plot, 7, table2x1, 0 / 0, 4, 0)
local _, noItem = item.place(plot, 7, nil, 4, 4, 0)
check("bad rotation, NaN cells and unknown items are refused", badRot == "bad request" and badCell == "out of bounds" and noItem == "bad request")
```
