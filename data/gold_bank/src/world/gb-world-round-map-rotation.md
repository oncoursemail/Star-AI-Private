---
id: gb-world-round-map-rotation
category: round-systems
topics: map loading, map rotation, ServerStorage, cleanup, spawn points
source: original
---
# Request
I store my maps in ServerStorage and clone a random one into workspace each round. Sometimes the same map comes up three times in a row, and the old map isn't always removed, so two maps overlap. How should map loading and cleanup work?

# Answer
Keep one loader that owns the current map: loading always destroys the previous one first, picks randomly among the maps other than the last one played, and parents the clone in a single step. Spawn points come from a folder inside each map, so the round code never searches the whole workspace.

```lua
--!strict
-- ModuleScript: ServerScriptService.MapRotation
export type Rotation = {
	loadNext: () -> Model,
	unload: () -> (),
	spawnPoints: () -> { BasePart },
	current: () -> Model?,
}

local MapRotation = {}

function MapRotation.new(library: Instance, container: Instance, random: Random): Rotation
	local currentMap: Model? = nil
	local lastName: string? = nil

	local function unload()
		if currentMap then
			currentMap:Destroy()
			currentMap = nil
		end
	end

	local function loadNext(): Model
		local candidates: { Model } = {}
		for _, child in library:GetChildren() do
			if child:IsA("Model") and (child.Name ~= lastName or #library:GetChildren() == 1) then
				table.insert(candidates, child)
			end
		end
		assert(#candidates > 0, "the map library has no Models")
		unload()
		local chosen = candidates[random:NextInteger(1, #candidates)]
		local map = chosen:Clone()
		map.Name = "CurrentMap"
		map:SetAttribute("MapName", chosen.Name)
		map.Parent = container
		currentMap = map
		lastName = chosen.Name
		return map
	end

	return {
		loadNext = loadNext,
		unload = unload,
		spawnPoints = function(): { BasePart }
			local points: { BasePart } = {}
			local folder = if currentMap then currentMap:FindFirstChild("Spawns") else nil
			if folder then
				for _, child in folder:GetChildren() do
					if child:IsA("BasePart") then
						table.insert(points, child)
					end
				end
			end
			return points
		end,
		current = function(): Model?
			return currentMap
		end,
	}
end

return MapRotation
```

Usage: `local maps = MapRotation.new(ServerStorage.Maps, workspace, Random.new())`, then `maps.loadNext()` at round start and `maps.unload()` after results.

- Excluding only the last map keeps rotation random while guaranteeing no back-to-back repeats; with a single map it is still allowed.
- Destroying before cloning means a crash mid-load leaves at most one map, never two overlapping.
- Parenting the fully built clone once replicates it in one batch instead of part by part.
- The original map name is kept as an attribute for the UI and analytics, since the clone is always called CurrentMap.

# Test
```lua
local library = Instance.new("Folder")
for _, name in { "Desert", "Forest", "Castle" } do
	local map = Instance.new("Model")
	map.Name = name
	local spawns = Instance.new("Folder")
	spawns.Name = "Spawns"
	spawns.Parent = map
	for i = 1, 2 do
		local pad = Instance.new("Part")
		pad.Name = "Pad" .. i
		pad.Parent = spawns
	end
	map.Parent = library
end
local rotation = item.new(library, workspace, Random.new(5))

local previous = nil
local repeats = 0
for _ = 1, 20 do
	local map = rotation.loadNext()
	if map:GetAttribute("MapName") == previous then
		repeats += 1
	end
	previous = map:GetAttribute("MapName")
end
check("never the same map twice in a row", repeats == 0)
local loaded = 0
for _, child in workspace:GetChildren() do
	if child.Name == "CurrentMap" then loaded += 1 end
end
check("only one map is ever loaded", loaded == 1)
check("spawn points come from the current map", #rotation.spawnPoints() == 2)
rotation.unload()
check("unload clears the map", rotation.current() == nil and workspace:FindFirstChild("CurrentMap") == nil and #rotation.spawnPoints() == 0)
check("empty library errors", not pcall(item.new(Instance.new("Folder"), workspace, Random.new(1)).loadNext))
```
