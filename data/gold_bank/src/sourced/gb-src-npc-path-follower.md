---
id: gb-src-npc-path-follower
category: npc-pathing
topics: PathfindingService, ComputeAsync, Blocked, waypoints, MoveToFinished, agent costs
source: adapted
source_id: creator-docs
source_path: content/en-us/characters/pathfinding.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
My guard NPC should walk to a target point using pathfinding, avoid water if possible, jump where the path says to, and re-plan if a door closes in front of it. Right now I just call `humanoid:MoveTo(target)` and it walks into walls.

# Answer
Create the path once with agent parameters and material costs, compute it in `pcall`, then walk the waypoints one at a time with `MoveTo` and `MoveToFinished`. Listen to `Path.Blocked`; if the blocked waypoint is still ahead, stop and recompute from the current position.

```lua
--!strict
local PathfindingService = game:GetService("PathfindingService")

local MOVE_TIMEOUT = 4
local MAX_REPLANS = 3

local PathFollower = {}

local function moveToWaypoint(humanoid: Humanoid, position: Vector3): boolean
	local finished: boolean? = nil
	local connection = humanoid.MoveToFinished:Connect(function(reached: boolean)
		finished = reached
	end)
	humanoid:MoveTo(position)
	local started = os.clock()
	while finished == nil and os.clock() - started < MOVE_TIMEOUT do
		task.wait(0.1)
	end
	connection:Disconnect()
	return finished == true
end

function PathFollower.walkTo(humanoid: Humanoid, root: BasePart, destination: Vector3): string
	local path = PathfindingService:CreatePath({
		AgentRadius = 2,
		AgentHeight = 5,
		AgentCanJump = true,
		Costs = { Water = 20 },
	})

	for _ = 1, MAX_REPLANS do
		local ok, err = pcall(function()
			path:ComputeAsync(root.Position, destination)
		end)
		if not ok or path.Status ~= Enum.PathStatus.Success then
			warn("Path failed:", err or path.Status)
			return "NoPath"
		end

		local waypoints = path:GetWaypoints()
		local current = 1
		local blocked = false
		local blockedConnection = path.Blocked:Connect(function(index: number)
			if index >= current then
				blocked = true
			end
		end)

		for index = 2, #waypoints do
			if blocked then
				break
			end
			current = index
			local waypoint = waypoints[index]
			if waypoint.Action == Enum.PathWaypointAction.Jump then
				humanoid.Jump = true
			end
			if not moveToWaypoint(humanoid, waypoint.Position) then
				blocked = true
			end
		end
		blockedConnection:Disconnect()

		if not blocked then
			return "Reached"
		end
	end
	return "GaveUp"
end

return PathFollower
```

Usage on the server: `PathFollower.walkTo(npc.Humanoid, npc.HumanoidRootPart, targetPart.Position)`.

- `Costs = { Water = 20 }` makes water 20 times as expensive, so the guard walks around it unless there is no other way.
- The first waypoint is the start position, so walking starts at index 2.
- A stuck move (no `MoveToFinished` within 4 s, for example pushed off course) counts as blocked and triggers a re-plan, capped at 3 attempts.
- Run this on the server and set the NPC's root part network owner to the server (`root:SetNetworkOwner(nil)`) so players cannot move it.

# Test
```lua
local rig = __buildRig(Vector3.new(0, 3, 0))
rig.Parent = workspace
local humanoid = rig.Humanoid
local status
task.spawn(function()
	status = item.walkTo(humanoid, rig.HumanoidRootPart, Vector3.new(0, 3, 12))
end)
local firstTarget = humanoid.__moveTo
check("moves to the second waypoint first", firstTarget ~= nil and firstTarget.Z > 0 and firstTarget.Z < 12)
for _ = 1, 10 do
	if status then
		break
	end
	humanoid.MoveToFinished:Fire(true)
	__advance(0.2)
end
check("reaches destination", status == "Reached")
check("last move is the destination", (humanoid.__moveTo - Vector3.new(0, 3, 12)).Magnitude < 1e-3)
game:GetService("PathfindingService").__status = Enum.PathStatus.NoPath
local failed
task.spawn(function()
	failed = item.walkTo(humanoid, rig.HumanoidRootPart, Vector3.new(50, 3, 0))
end)
check("no path reported", failed == "NoPath")
```
