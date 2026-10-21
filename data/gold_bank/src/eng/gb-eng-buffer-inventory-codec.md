---
id: gb-eng-buffer-inventory-codec
category: luau-syntax
topics: buffer, serialization, length-prefixed strings, versioning, compact save
source: original
---
# Request
I'm hitting the DataStore size limit with a big building save, and I'd like to serialize item records (string item name, u32 count, f32 durability) to a compact binary format. There is no `string.pack` that I want to rely on here; can I do it with the `buffer` library and still store the result in a DataStore?

# Answer
Encode with `buffer`: a version byte, a u16 record count, then per record a length-prefixed name, a u32 count and an f32 durability. DataStores accept a buffer value directly, so save the buffer itself; the decoder bounds-checks so a corrupt value returns nil instead of erroring.

```lua
--!strict
-- ModuleScript: ServerScriptService.InventoryCodec
export type Stack = { name: string, count: number, durability: number }

local VERSION = 1
local MAX_NAME = 255

local InventoryCodec = {}

function InventoryCodec.encode(stacks: { Stack }): buffer
	assert(#stacks <= 65535, "too many stacks for a u16 count")
	local size = 3
	for _, s in stacks do
		assert(#s.name <= MAX_NAME, "item name too long")
		size += 1 + #s.name + 4 + 4
	end
	local b = buffer.create(size)
	buffer.writeu8(b, 0, VERSION)
	buffer.writeu16(b, 1, #stacks)
	local offset = 3
	for _, s in stacks do
		buffer.writeu8(b, offset, #s.name)
		buffer.writestring(b, offset + 1, s.name)
		offset += 1 + #s.name
		buffer.writeu32(b, offset, math.clamp(s.count, 0, 2 ^ 32 - 1))
		buffer.writef32(b, offset + 4, s.durability)
		offset += 8
	end
	return b
end

function InventoryCodec.decode(b: buffer): { Stack }?
	local len = buffer.len(b)
	if len < 3 or buffer.readu8(b, 0) ~= VERSION then
		return nil
	end
	local count = buffer.readu16(b, 1)
	local offset = 3
	local out: { Stack } = {}
	for _ = 1, count do
		if offset + 1 > len then
			return nil
		end
		local nameLength = buffer.readu8(b, offset)
		if offset + 1 + nameLength + 8 > len then
			return nil
		end
		local name = buffer.readstring(b, offset + 1, nameLength)
		offset += 1 + nameLength
		table.insert(out, {
			name = name,
			count = buffer.readu32(b, offset),
			durability = buffer.readf32(b, offset + 4),
		})
		offset += 8
	end
	return out
end

return InventoryCodec
```

- Save with `store:SetAsync(key, InventoryCodec.encode(stacks))`. Do not save `buffer.tostring(b)` instead: arbitrary bytes are not valid UTF-8 text, and data store strings must be. A 20-character name with count and durability encodes to 29 bytes instead of about 60 as JSON.
- The version byte lets a future format be decoded differently; bump `VERSION` and keep the old decoder for old saves.
- f32 keeps about 7 significant digits, fine for durability but not for currency; store money as an integer (u32 or f64).
- Load through your normal pcall/retry DataStore wrapper and treat a nil decode as corrupt data (keep the old value, do not overwrite it).

# Test
```lua
local stacks = {
	{ name = "Iron Sword", count = 1, durability = 0.75 },
	{ name = "Wood", count = 4000000, durability = 1 },
	{ name = "", count = 0, durability = 0 },
}
local encoded = item.encode(stacks)
check("compact size", buffer.len(encoded) == 3 + (1 + 10 + 8) + (1 + 4 + 8) + (1 + 0 + 8))
local back = item.decode(encoded)
check("round trip names and counts", back ~= nil and back[1].name == "Iron Sword" and back[2].count == 4000000 and back[3].name == "")
check("f32 durability close", back ~= nil and math.abs(back[1].durability - 0.75) < 1e-6)
check("truncated data rejected", item.decode(buffer.fromstring(string.sub(buffer.tostring(encoded), 1, buffer.len(encoded) - 3))) == nil)
check("wrong version rejected", item.decode(buffer.fromstring("\2\0\0")) == nil)
check("empty list round trips", #(item.decode(item.encode({})) :: any) == 0)
check("overlong name refused", not pcall(item.encode, { { name = string.rep("x", 300), count = 1, durability = 1 } }))
local tooMany = table.create(65536, { name = "", count = 0, durability = 0 })
check("more stacks than the u16 count refused", not pcall(item.encode, tooMany))
```
