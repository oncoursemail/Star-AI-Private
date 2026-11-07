---
id: gb-eng-perf-cache-character-parts
category: performance
topics: caching lookups, FindFirstChild, GetService, per-frame cost, character parts
source: original
---
# Request
A server script checks every player's distance to 50 capture zones every frame. Inside the loop I do `game:GetService("Players")`, `player.Character:FindFirstChild("HumanoidRootPart")` and `workspace.Zones:GetChildren()` each time. Is this lookup-heavy code actually a problem, and how should I restructure it?

# Answer
Each lookup is cheap alone, but inside players x zones x 60 frames they add up and also allocate (`GetChildren` returns a new table every call). Resolve things once: services at the top, the zone list once (updated by events), and each player's root part when the character spawns, then the hot loop only reads cached references.

```lua
--!strict
-- ModuleScript: ServerScriptService.ZoneWatch
local Players = game:GetService("Players")

export type Zone = { name: string, center: Vector3, radiusSq: number }

local ZoneWatch = {}

local roots: { [Player]: BasePart } = {}
local zones: { Zone } = {}

local function track(player: Player)
	local function onCharacter(character: Model)
		roots[player] = nil
		local root = character:WaitForChild("HumanoidRootPart", 10)
		if root and root:IsA("BasePart") and player.Character == character then
			roots[player] = root
		end
	end
	player.CharacterAdded:Connect(onCharacter)
	player.CharacterRemoving:Connect(function()
		roots[player] = nil
	end)
	if player.Character then
		task.spawn(onCharacter, player.Character)
	end
end

function ZoneWatch.start(zoneFolder: Instance): ()
	local function rebuild()
		table.clear(zones)
		for _, part in zoneFolder:GetChildren() do
			if part:IsA("BasePart") then
				local r = part.Size.X / 2
				table.insert(zones, { name = part.Name, center = part.Position, radiusSq = r * r })
			end
		end
	end
	rebuild()
	zoneFolder.ChildAdded:Connect(rebuild)
	zoneFolder.ChildRemoved:Connect(rebuild)
	Players.PlayerAdded:Connect(track)
	Players.PlayerRemoving:Connect(function(player: Player)
		roots[player] = nil
	end)
	for _, player in Players:GetPlayers() do
		track(player)
	end
end

-- Hot path: called every frame; only cached reads and arithmetic.
function ZoneWatch.occupancy(out: { [string]: number }): { [string]: number }
	table.clear(out)
	for _, root in roots do
		local p = root.Position
		for _, zone in zones do
			local d = p - zone.center
			if d.X * d.X + d.Z * d.Z <= zone.radiusSq then
				out[zone.name] = (out[zone.name] or 0) + 1
			end
		end
	end
	return out
end

return ZoneWatch
```

- `roots` drops entries on `CharacterRemoving` and `PlayerRemoving`, so cached references never point at destroyed parts and the table does not leak.
- Zones are static in most maps; rebuilding the cached list on `ChildAdded`/`ChildRemoved` keeps it correct if you add zones at runtime without paying for `GetChildren` each frame.
- `occupancy` fills a caller-owned table, so the per-frame call allocates nothing. Profile first: if this loop is under 0.1 ms, readability wins over further tuning.

# Test
```lua
local folder = Instance.new("Folder")
folder.Name = "Zones"
folder.Parent = workspace
local function zone(name, x)
	local z = Instance.new("Part")
	z.Name = name
	z.Size = Vector3.new(20, 1, 20)
	z.Position = Vector3.new(x, 0, 0)
	z.Parent = folder
end
zone("A", 0)
zone("B", 100)
local early = __makePlayer(1, "Early")
__makeCharacter(early, Vector3.new(2, 3, 0))
item.start(folder)
local late = __makePlayer(2, "Late")
__makeCharacter(late, Vector3.new(105, 3, 0))
__advance(0.1)
local out = {}
item.occupancy(out)
check("players counted in their zones", out.A == 1 and out.B == 1)
zone("C", 200)
__makeCharacter(early, Vector3.new(198, 3, 0))
__advance(0.1)
item.occupancy(out)
check("new zone and respawned character picked up", out.C == 1 and out.A == nil)
__removePlayer(late)
item.occupancy(out)
check("leaving player dropped from cache", out.B == nil)
```
