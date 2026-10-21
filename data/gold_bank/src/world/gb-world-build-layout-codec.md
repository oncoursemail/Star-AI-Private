---
id: gb-world-build-layout-codec
category: building-layout
topics: save base layout, plot-relative CFrame, ToObjectSpace, DataStore format, validation
source: original
---
# Request
I save players' bases by storing each item's world position, but players get a different plot every server, so their base loads in the wrong place. How should I store and rebuild the layout so it follows whichever plot they get?

# Answer
Store every item relative to the plot (`plotCFrame:ToObjectSpace(item pivot)`) as plain numbers plus the item id, and rebuild with `plotCFrame:ToWorldSpace` on whatever plot the player gets next time. Decoding treats the saved data as untrusted: unknown ids, non-finite numbers and positions outside the plot are skipped.

```lua
--!strict
-- ModuleScript: ServerScriptService.LayoutCodec
export type Entry = { id: string, x: number, y: number, z: number, yaw: number }

local LayoutCodec = {}

local function round(value: number): number
	return math.round(value * 100) / 100
end

function LayoutCodec.encode(plotFrame: CFrame, items: { Model }): { Entry }
	local entries: { Entry } = {}
	for _, model in items do
		local id = model:GetAttribute("ItemId")
		if type(id) == "string" then
			local relative = plotFrame:ToObjectSpace(model:GetPivot())
			local _, yaw, _ = relative:ToOrientation()
			table.insert(entries, { id = id, x = round(relative.X), y = round(relative.Y), z = round(relative.Z), yaw = round(yaw) })
		end
	end
	return entries
end

local function finite(value: any, limit: number): boolean
	return type(value) == "number" and value == value and math.abs(value) <= limit
end

function LayoutCodec.decode(plotFrame: CFrame, entries: { any }, catalog: Instance, halfSize: number, parent: Instance): number
	local placed = 0
	for _, entry in entries do
		if type(entry) ~= "table" or type(entry.id) ~= "string" then
			continue
		end
		if not (finite(entry.x, halfSize) and finite(entry.y, 200) and finite(entry.z, halfSize) and finite(entry.yaw, 7)) then
			continue
		end
		local template = catalog:FindFirstChild(entry.id)
		if template == nil or not template:IsA("Model") then
			continue
		end
		local copy = template:Clone()
		copy:PivotTo(plotFrame:ToWorldSpace(CFrame.new(entry.x, entry.y, entry.z) * CFrame.Angles(0, entry.yaw, 0)))
		copy:SetAttribute("ItemId", entry.id)
		copy.Parent = parent
		placed += 1
	end
	return placed
end

return LayoutCodec
```

- The encoded entries are strings and numbers only, so the list can go straight into a DataStore (Vector3 and CFrame values cannot).
- Saving only yaw assumes furniture stays upright; store the full orientation if you allow tilted placement.
- Rounding to 0.01 studs keeps the saved data small without visible drift.
- `halfSize` is half the plot's width, so a corrupted or edited save cannot put an item on someone else's plot.

# Test
```lua
local catalog = Instance.new("Folder")
local chair = Instance.new("Model")
chair.Name = "Chair"
local seat = Instance.new("Part")
seat.Parent = chair
chair.PrimaryPart = seat
chair.Parent = catalog

local function placedChair(cf)
	local m = Instance.new("Model")
	local p = Instance.new("Part")
	p.CFrame = cf
	p.Parent = m
	m.PrimaryPart = p
	m:SetAttribute("ItemId", "Chair")
	return m
end
local oldPlot = CFrame.new(0, 0, 0)
local a = placedChair(CFrame.new(5, 1, -3) * CFrame.Angles(0, math.rad(90), 0))
local b = placedChair(CFrame.new(-8, 1, 6))
local saved = item.encode(oldPlot, { a, b })
check("entries are plain numbers and strings", #saved == 2 and saved[1].id == "Chair" and saved[1].x == 5 and type(saved[1].yaw) == "number")

local newPlot = CFrame.new(100, 0, 50) * CFrame.Angles(0, math.rad(90), 0)
local folder = Instance.new("Folder")
folder.Parent = workspace
check("both items rebuilt", item.decode(newPlot, saved, catalog, 50, folder) == 2)
local rebuilt = folder:GetChildren()[2]
local expected = newPlot * Vector3.new(-8, 1, 6)
check("positions follow the new plot", (rebuilt:FindFirstChildWhichIsA("BasePart").Position - expected).Magnitude < 1e-6)

local tampered = {
	{ id = "Chair", x = 0 / 0, y = 1, z = 0, yaw = 0 },
	{ id = "Throne", x = 0, y = 1, z = 0, yaw = 0 },
	{ id = "Chair", x = 900, y = 1, z = 0, yaw = 0 },
	"garbage",
	{ id = "Chair", x = 1, y = 1, z = 1, yaw = 0 },
}
check("only the valid entry is placed", item.decode(newPlot, tampered, catalog, 50, folder) == 1)
```
