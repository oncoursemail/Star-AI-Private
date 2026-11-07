---
id: gb-data-serialize-roblox-types
category: datastore-safety
topics: DataStore, serialization, Vector3, CFrame, Color3, EnumItem
source: original
---
# Request
I'm saving a player's placed furniture and SetAsync errors with "Cannot store Vector3 in data store". Each piece has a CFrame, a Color3 and a material. How do I turn those into something a DataStore accepts and back again?

# Answer
DataStores only take strings, numbers, booleans, buffers and tables of those, so encode each Roblox type into a small tagged table and decode it on load. A recursive pair of functions handles nested tables, and unknown types fail loudly instead of saving garbage.

```lua
--!strict
-- ModuleScript: ServerScriptService.Serializer
local Serializer = {}

function Serializer.encode(value: any): any
	local kind = typeof(value)
	if kind == "Vector3" then
		return { _t = "V3", v = { value.X, value.Y, value.Z } }
	elseif kind == "CFrame" then
		return { _t = "CF", v = { value:GetComponents() } }
	elseif kind == "Color3" then
		return { _t = "C3", v = value:ToHex() }
	elseif kind == "EnumItem" then
		return { _t = "EN", e = tostring(value.EnumType), n = value.Name }
	elseif kind == "table" then
		local out = {}
		for k, v in value do
			out[k] = Serializer.encode(v)
		end
		return out
	elseif kind == "string" or kind == "number" or kind == "boolean" then
		return value
	end
	error("Serializer cannot encode a " .. kind)
end

function Serializer.decode(value: any): any
	if type(value) ~= "table" then
		return value
	end
	local tag = value._t
	if tag == "V3" then
		local v = value.v
		return Vector3.new(v[1], v[2], v[3])
	elseif tag == "CF" then
		return CFrame.new(table.unpack(value.v, 1, 12))
	elseif tag == "C3" then
		return Color3.fromHex(value.v)
	elseif tag == "EN" then
		-- indexing Enum with an unknown name throws; FromName returns nil for an unknown item
		local found, enum = pcall(function(): any
			return (Enum :: any)[value.e]
		end)
		return if found and enum then enum:FromName(value.n) else nil
	end
	local out = {}
	for k, v in value do
		out[k] = Serializer.decode(v)
	end
	return out
end

return Serializer
```

- Each encoded value is a pure dictionary (a tag plus a nested array); stores reject tables that mix array and dictionary keys.
- Storing the enum by name (not by number) keeps saves valid if Roblox ever reorders enum values.
- For hundreds of pieces, round positions to a grid and drop rotation components you never use: see a compact format if you approach the 4 MB value limit.

# Test
```lua
local store = game:GetService("DataStoreService"):GetDataStore("Furniture")
local piece = {
	name = "Chair",
	cframe = CFrame.new(10, 2, -4) * CFrame.Angles(0, math.rad(90), 0),
	color = Color3.fromRGB(255, 128, 0),
	material = Enum.Material.Wood,
	offset = Vector3.new(1, 2, 3),
}
local rawOk = pcall(function()
	store:SetAsync("raw", piece)
end)
check("raw Roblox types are rejected by the store", not rawOk)

local encoded = item.encode({ piece })
local saveOk = pcall(function()
	store:SetAsync("encoded", encoded)
end)
check("encoded data is accepted", saveOk)

local back = item.decode(store:GetAsync("encoded"))[1]
check("Vector3 round-trips", back.offset == Vector3.new(1, 2, 3))
check("CFrame round-trips position and rotation", (back.cframe.Position - piece.cframe.Position).Magnitude < 1e-4
	and back.cframe.LookVector:FuzzyEq(piece.cframe.LookVector, 1e-4))
check("Color3 and enum round-trip", back.color:ToHex() == piece.color:ToHex() and back.material == Enum.Material.Wood)
check("unknown enum item decodes to nil", item.decode({ _t = "EN", e = "Material", n = "NoSuchMaterial" }) == nil)
check("unknown enum type decodes to nil", item.decode({ _t = "EN", e = "NoSuchEnum", n = "Wood" }) == nil)
check("unsupported types fail loudly", not pcall(item.encode, { part = Instance.new("Part") }))
```
