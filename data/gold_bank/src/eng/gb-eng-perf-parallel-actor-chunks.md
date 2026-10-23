---
id: gb-eng-perf-parallel-actor-chunks
category: performance
topics: Parallel Luau, Actor, task.synchronize, BindToMessageParallel, terrain generation
source: original
---
# Request
Generating terrain chunks (noise heights for a 64x64 grid each) freezes my server for a second when many chunks are requested at once. How do I move the math to Parallel Luau with Actors, and what can and can't run in parallel?

# Answer
Split the work into a pure function (noise math, no Instance writes) that runs in the parallel phase, and a short serial phase that writes the results to the world. Several Actors each receive chunk requests by message; inside the handler the math runs desynchronized, then `task.synchronize()` switches back before touching Terrain.

```lua
--!strict
-- ModuleScript: ServerScriptService.ChunkMath (pure: safe to call in parallel)
local ChunkMath = {}

export type Params = { size: number, scale: number, amplitude: number, seed: number }

function ChunkMath.heights(chunkX: number, chunkZ: number, p: Params): { number }
	local out = table.create(p.size * p.size, 0)
	local i = 0
	for z = 0, p.size - 1 do
		for x = 0, p.size - 1 do
			i += 1
			local wx = (chunkX * p.size + x) * p.scale
			local wz = (chunkZ * p.size + z) * p.scale
			-- two octaves of noise; math.noise is deterministic for the same inputs
			local n = math.noise(wx, wz, p.seed) + 0.5 * math.noise(wx * 2, wz * 2, p.seed + 17)
			out[i] = math.floor((n + 1.5) / 3 * p.amplitude)
		end
	end
	return out
end

return ChunkMath
```

```lua
--!strict
-- Script inside each Actor (ServerScriptService.ChunkWorkers.Worker1.Worker, ...)
local ServerScriptService = game:GetService("ServerScriptService")
local ChunkMath = require(ServerScriptService.ChunkMath)

local PARAMS = { size = 64, scale = 0.02, amplitude = 40, seed = 12345 }
local CELL = 4

local actor = script:GetActor()
actor:BindToMessageParallel("Generate", function(chunkX: number, chunkZ: number)
	-- parallel phase: pure math only, no writes to the DataModel
	local heights = ChunkMath.heights(chunkX, chunkZ, PARAMS)

	task.synchronize() -- serial phase: now it is safe to modify Terrain
	local i = 0
	for z = 0, PARAMS.size - 1 do
		for x = 0, PARAMS.size - 1 do
			i += 1
			local h = math.max(1, heights[i])
			local position = Vector3.new((chunkX * PARAMS.size + x) * CELL, h / 2, (chunkZ * PARAMS.size + z) * CELL)
			workspace.Terrain:FillBlock(CFrame.new(position), Vector3.new(CELL, h, CELL), Enum.Material.Grass)
		end
	end
end)
```

```lua
--!strict
-- Script: ServerScriptService.ChunkDispatcher (sends requests round-robin to the Actors)
local ServerScriptService = game:GetService("ServerScriptService")
local workers = ServerScriptService:WaitForChild("ChunkWorkers"):GetChildren()

local nextWorker = 1
local function requestChunk(chunkX: number, chunkZ: number)
	local actor = workers[nextWorker] :: Actor
	nextWorker = nextWorker % #workers + 1
	actor:SendMessage("Generate", chunkX, chunkZ)
end

for cx = -2, 2 do
	for cz = -2, 2 do
		requestChunk(cx, cz)
	end
end
```

- Work only spreads across cores when it is split over several Actors; code inside one Actor runs on one thread. Four to eight workers is a reasonable start.
- In the parallel phase you may read Instances and call pure functions, but property writes, `Instance.new` parenting and most engine mutations error until `task.synchronize()`. Use `task.desynchronize()` to enter the parallel phase from serial code that is not already running in a parallel handler.
- Keep the serial part short: if writing to Terrain dominates, batch it with `Terrain:WriteVoxels` over a region instead of one `FillBlock` per cell.

# Test
```lua
local p = { size = 8, scale = 0.05, amplitude = 40, seed = 3 }
local a = item.heights(0, 0, p)
local b = item.heights(0, 0, p)
local same = #a == 64
for i = 1, #a do
	if a[i] ~= b[i] then
		same = false
	end
end
check("deterministic for the same chunk", same)
local inRange = true
for _, h in a do
	if h < 0 or h > 40 or h % 1 ~= 0 then
		inRange = false
	end
end
check("heights are integers within amplitude", inRange)
local c = item.heights(1, 0, p)
local differs = false
for i = 1, #a do
	if a[i] ~= c[i] then
		differs = true
	end
end
check("neighbouring chunk differs", differs)
check("grid size respected", #item.heights(2, 2, { size = 3, scale = 0.1, amplitude = 10, seed = 1 }) == 9)
```
