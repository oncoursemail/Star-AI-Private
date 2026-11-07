---
id: gb-data-compact-build-format
category: datastore-safety
topics: DataStore, 4 MB limit, compact format, building game, JSONEncode
source: original
---
# Request
My building game saves every block as a table with name, position, rotation and color strings. Big bases are hitting the DataStore size limit. How do I store thousands of blocks compactly and check the size before saving?

# Answer
Store bases as one flat number array: five small integers per block (grid x, y, z, rotation step, block type id) instead of a keyed table with strings. Decode with strict validation, and measure the JSON size before writing so an oversized base is refused instead of erroring mid-save.

```lua
--!strict
-- ModuleScript: ServerScriptService.BuildCodec
local HttpService = game:GetService("HttpService")

export type Block = { typeId: number, cell: Vector3, rotation: number } -- cell in grid units, rotation 0..3

local FIELDS = 5
local MAX_CELL = 512
local MAX_BYTES = 3_500_000 -- below the 4 MB value limit, leaving room for other fields

local BuildCodec = {}

function BuildCodec.encode(blocks: { Block }): { number }
	local flat: { number } = {}
	for _, block in blocks do
		local cell = block.cell
		table.insert(flat, cell.X)
		table.insert(flat, cell.Y)
		table.insert(flat, cell.Z)
		table.insert(flat, block.rotation)
		table.insert(flat, block.typeId)
	end
	return flat
end

local function isInt(n: any, lo: number, hi: number): boolean
	return type(n) == "number" and n % 1 == 0 and n >= lo and n <= hi
end

-- Saved data is untrusted after every format change or bug; drop bad records instead of building them.
function BuildCodec.decode(flat: any, validTypes: { [number]: boolean }): { Block }
	local blocks: { Block } = {}
	if type(flat) ~= "table" or #flat % FIELDS ~= 0 then
		return blocks
	end
	for i = 1, #flat, FIELDS do
		local x, y, z, rotation, typeId = flat[i], flat[i + 1], flat[i + 2], flat[i + 3], flat[i + 4]
		if isInt(x, -MAX_CELL, MAX_CELL) and isInt(y, 0, MAX_CELL) and isInt(z, -MAX_CELL, MAX_CELL)
			and isInt(rotation, 0, 3) and validTypes[typeId] then
			table.insert(blocks, { typeId = typeId, cell = Vector3.new(x, y, z), rotation = rotation })
		end
	end
	return blocks
end

function BuildCodec.size(value: any): number
	return #HttpService:JSONEncode(value)
end

function BuildCodec.fits(value: any, limit: number?): (boolean, number)
	local bytes = BuildCodec.size(value)
	return bytes <= (limit or MAX_BYTES), bytes
end

return BuildCodec
```

- A block now costs about 15-20 characters of JSON instead of 150+, so well over a hundred thousand blocks fit in one key.
- Keep a server-side table mapping `typeId` to block definitions; never store names or colors per block when an id can look them up.
- If `fits` fails, refuse the placement that crossed the limit and tell the player, rather than letting the next autosave fail silently.

# Test
```lua
local valid = { [1] = true, [2] = true }
local blocks = {
	{ typeId = 1, cell = Vector3.new(0, 0, 0), rotation = 0 },
	{ typeId = 2, cell = Vector3.new(-12, 3, 40), rotation = 3 },
	{ typeId = 1, cell = Vector3.new(5, 1, -7), rotation = 1 },
}
local flat = item.encode(blocks)
check("five numbers per block", #flat == 15)
local back = item.decode(flat, valid)
check("round trip keeps every block", #back == 3 and back[2].cell == Vector3.new(-12, 3, 40) and back[2].rotation == 3)

local store = game:GetService("DataStoreService"):GetDataStore("Bases")
local ok = pcall(function()
	store:SetAsync("base_1", flat)
end)
check("flat array is a valid DataStore value", ok)

check("compact: under 25 characters per block", item.size(flat) / 3 < 25)

local tampered = { 0, 0, 0, 0, 1, 1.5, 0, 0, 0, 1, 0, 0, 0, 9, 1, 0, 0, 0, 0, 99 }
check("bad records are dropped", #item.decode(tampered, valid) == 1)
check("truncated data decodes to nothing", #item.decode({ 1, 2, 3 }, valid) == 0)

local fitsSmall = item.fits(flat)
local fitsTiny, bytes = item.fits(flat, 10)
check("size guard reports over-limit values", fitsSmall and not fitsTiny and bytes > 10)
```
