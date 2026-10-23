---
id: gb-src-actor-parallel-heightmap
category: performance
topics: Parallel Luau, Actor, BindToMessageParallel, task.synchronize, SendMessage, math.noise
source: adapted
source_id: creator-docs
source_path: content/en-us/scripting/multithreading.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I generate terrain heights with `math.noise` for a big map and it freezes the server for a few seconds at startup. How can I spread the noise calculation over several cores with Parallel Luau?

# Answer
Put a worker script under several `Actor` instances. The dispatcher sends each actor a chunk with `SendMessage`; the worker computes the heights in a parallel callback (pure math is allowed there) and only switches to serial with `task.synchronize()` for the part that touches instances.

```lua
--!strict
-- Script inside ServerScriptService.TerrainWorker (cloned under each Actor by the dispatcher)
local actor = script:GetActor()
if actor == nil then
	return
end

local CHUNK = 16
local SCALE = 0.02
local AMPLITUDE = 40

local function computeHeights(chunkX: number, chunkZ: number, seed: number): { number }
	local heights: { number } = table.create(CHUNK * CHUNK, 0)
	for x = 0, CHUNK - 1 do
		for z = 0, CHUNK - 1 do
			local worldX = chunkX * CHUNK + x
			local worldZ = chunkZ * CHUNK + z
			heights[x * CHUNK + z + 1] = math.noise(worldX * SCALE, worldZ * SCALE, seed) * AMPLITUDE
		end
	end
	return heights
end

actor:BindToMessageParallel("GenerateChunk", function(chunkX: number, chunkZ: number, seed: number)
	local heights = computeHeights(chunkX, chunkZ, seed)

	task.synchronize()
	local folder = Instance.new("Folder")
	folder.Name = `Chunk_{chunkX}_{chunkZ}`
	folder:SetAttribute("MaxHeight", math.max(table.unpack(heights)))
	folder.Parent = workspace
end)
```

```lua
--!strict
-- Script: ServerScriptService.TerrainDispatcher
local ServerScriptService = game:GetService("ServerScriptService")

local WORKERS = 8
local RADIUS = 8

local template = ServerScriptService:WaitForChild("TerrainWorker")
local actors: { Actor } = {}
for _ = 1, WORKERS do
	local actor = Instance.new("Actor")
	template:Clone().Parent = actor
	actor.Parent = ServerScriptService
	table.insert(actors, actor)
end

local seed = Random.new():NextNumber() * 1000
local next = 0
task.defer(function()
	for x = -RADIUS, RADIUS do
		for z = -RADIUS, RADIUS do
			next = next % WORKERS + 1
			actors[next]:SendMessage("GenerateChunk", x, z, seed)
		end
	end
end)
```

- Code in a parallel callback may read instances and do math, but creating or changing instances needs `task.synchronize()` first.
- Scripts only run in parallel when they are under different Actors; one actor per worker spreads the chunks over cores.
- The template has no Actor ancestor, so its `GetActor()` is nil and it exits; only the clones work. Disable the template (`Enabled = false`) and enable each clone if you prefer it never runs.
