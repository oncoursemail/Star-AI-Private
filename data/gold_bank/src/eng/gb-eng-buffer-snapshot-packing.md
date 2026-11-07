---
id: gb-eng-buffer-snapshot-packing
category: luau-syntax
topics: buffer, binary packing, network bandwidth, quantization, remotes
source: original
---
# Request
I send positions of 40 NPCs to clients 10 times a second as a table of Vector3s and the network stats look bad. I read that the `buffer` type can pack data compactly. How would I pack id + position + yaw for each NPC into a buffer and read it back on the client?

# Answer
Write a fixed-size record per NPC: a u16 id, three positions quantized to i16 at 1/20-stud precision relative to a map origin, and yaw as a u8. That is 9 bytes per NPC instead of a table with a Vector3 per entry, and buffers can be sent through RemoteEvents directly.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.NpcSnapshot
export type NpcState = { id: number, position: Vector3, yaw: number }

local RECORD = 9 -- u16 id + 3 x i16 position + u8 yaw
local SCALE = 20 -- 1/20 stud precision
local LIMIT = 32767 / SCALE -- about 1638 studs from the origin each way

local NpcSnapshot = {}

local function quantize(n: number): number
	return math.clamp(math.round(n * SCALE), -32768, 32767)
end

function NpcSnapshot.encode(states: { NpcState }, origin: Vector3): buffer
	local b = buffer.create(#states * RECORD)
	for i, state in states do
		local offset = (i - 1) * RECORD
		local p = state.position - origin
		buffer.writeu16(b, offset, state.id)
		buffer.writei16(b, offset + 2, quantize(p.X))
		buffer.writei16(b, offset + 4, quantize(p.Y))
		buffer.writei16(b, offset + 6, quantize(p.Z))
		local turns = (state.yaw % (2 * math.pi)) / (2 * math.pi)
		buffer.writeu8(b, offset + 8, math.round(turns * 256) % 256)
	end
	return b
end

function NpcSnapshot.decode(b: buffer, origin: Vector3): { NpcState }
	local count = buffer.len(b) // RECORD
	local out: { NpcState } = {}
	for i = 1, count do
		local offset = (i - 1) * RECORD
		local position = origin + Vector3.new(
			buffer.readi16(b, offset + 2) / SCALE,
			buffer.readi16(b, offset + 4) / SCALE,
			buffer.readi16(b, offset + 6) / SCALE
		)
		out[i] = {
			id = buffer.readu16(b, offset),
			position = position,
			yaw = buffer.readu8(b, offset + 8) / 256 * 2 * math.pi,
		}
	end
	return out
end

NpcSnapshot.LIMIT = LIMIT

return NpcSnapshot
```

- Server: `snapshotRemote:FireAllClients(NpcSnapshot.encode(states, MAP_ORIGIN))`; client: `snapshotRemote.OnClientEvent:Connect(function(b: buffer) ... NpcSnapshot.decode(b, MAP_ORIGIN) end)`.
- Positions further than `LIMIT` studs from the origin are clamped, so keep the origin at the map centre or switch to i32 for huge maps.
- Yaw at 256 steps is about 1.4 degrees, invisible once the client interpolates between snapshots; use an UnreliableRemoteEvent for these updates since a lost one is replaced 100 ms later.
- When decoding a buffer that came from a client (not the case here), check `buffer.len` first: reads past the end throw.

# Test
```lua
local origin = Vector3.new(500, 0, -200)
local states = {
	{ id = 1, position = Vector3.new(510.03, 4.5, -180.26), yaw = math.pi / 2 },
	{ id = 65535, position = Vector3.new(-200, 12, 300), yaw = 2 * math.pi - 0.01 },
}
local b = item.encode(states, origin)
check("9 bytes per npc", buffer.len(b) == 18)
local back = item.decode(b, origin)
check("ids round trip", back[1].id == 1 and back[2].id == 65535)
check("position within 1/40 stud", (back[1].position - states[1].position).Magnitude < 0.05)
check("yaw within one step", math.abs(back[1].yaw - math.pi / 2) < 0.03)
check("yaw wraps near full turn", back[2].yaw < 0.03)
local far = item.decode(item.encode({ { id = 2, position = origin + Vector3.new(5000, 0, 0), yaw = 0 } }, origin), origin)
check("far position clamps to limit", math.abs((far[1].position - origin).X - item.LIMIT) < 0.06)
check("empty snapshot", buffer.len(item.encode({}, origin)) == 0 and #item.decode(buffer.create(0), origin) == 0)
```
