---
id: gb-world-npc-flee-point
category: npc-pathing
topics: flee behaviour, candidate points, path scoring, PathfindingService, NPC AI
source: original
---
# Request
I want critters that run away from the player. Just moving in the opposite direction makes them run into walls and corners. How can I pick a good place to flee to?

# Answer
Sample candidate points on a ring around the critter, score each by how much farther from the threat it is (and prefer directions away from the threat), then try them best-first and keep the first one that has a valid path. If none is reachable the function returns nil and the critter can cower or fight back.

```lua
--!strict
-- ModuleScript: ServerScriptService.FleePlanner
local PathfindingService = game:GetService("PathfindingService")

local FleePlanner = {}

export type Candidate = { position: Vector3, score: number }

function FleePlanner.candidates(position: Vector3, threat: Vector3, radius: number, samples: number): { Candidate }
	local away = Vector3.new(position.X - threat.X, 0, position.Z - threat.Z)
	local awayUnit = if away.Magnitude > 1e-3 then away.Unit else Vector3.xAxis
	local list: { Candidate } = {}
	for index = 1, samples do
		local angle = index / samples * 2 * math.pi
		local direction = Vector3.new(math.cos(angle), 0, math.sin(angle))
		local point = position + direction * radius
		local gain = (point - threat).Magnitude - (position - threat).Magnitude
		table.insert(list, { position = point, score = gain + direction:Dot(awayUnit) * radius * 0.5 })
	end
	table.sort(list, function(a: Candidate, b: Candidate): boolean
		return a.score > b.score
	end)
	return list
end

function FleePlanner.choose(position: Vector3, threat: Vector3, radius: number, maxTries: number): (Vector3?, Path?)
	local path = PathfindingService:CreatePath({ AgentRadius = 1.5, AgentHeight = 3, AgentCanJump = false })
	for index, candidate in FleePlanner.candidates(position, threat, radius, 12) do
		if index > maxTries then
			break
		end
		local ok = pcall(function()
			path:ComputeAsync(position, candidate.position)
		end)
		if ok and path.Status == Enum.PathStatus.Success then
			return candidate.position, path
		end
	end
	return nil, nil
end

return FleePlanner
```

- Trying only the best few candidates bounds the cost; each `ComputeAsync` is real work, so 3-4 tries per decision is plenty.
- Scoring by distance gained from the threat naturally rejects points behind the player, and the direction term breaks ties toward "straight away".
- A wall right behind the critter makes those candidates fail to path, so it slides sideways along the wall instead of pressing into it.
- Re-plan when the threat closes in, not every frame; a flee decision every half second looks natural.

# Test
```lua
local list = item.candidates(Vector3.new(0, 0, 0), Vector3.new(10, 0, 0), 20, 12)
check("twelve candidates", #list == 12)
check("best candidate runs away from the threat", list[1].position.X < -19)
check("worst candidate is toward the threat", list[12].position.X > 19)
local sameSpot = item.candidates(Vector3.new(5, 0, 5), Vector3.new(5, 0, 5), 10, 8)
check("threat on top of the critter still yields valid points", sameSpot[1].position.X == sameSpot[1].position.X)

local point, path = item.choose(Vector3.new(0, 3, 0), Vector3.new(10, 3, 0), 20, 3)
check("reachable flee point chosen", point ~= nil and path ~= nil and point.X < -19)
game:GetService("PathfindingService").__status = Enum.PathStatus.NoPath
local none = item.choose(Vector3.new(0, 3, 0), Vector3.new(10, 3, 0), 20, 3)
check("no reachable point returns nil", none == nil)
game:GetService("PathfindingService").__status = nil
```
