---
id: gb-world-npc-path-follower
category: npc-pathing
topics: PathfindingService, agent parameters, waypoints, Jump action, MoveToFinished timeout
source: original
---
# Request
My NPC uses PathfindingService but gets stuck on ledges it should jump, walks through narrow gaps it can't fit, and sometimes freezes forever on `humanoid.MoveToFinished:Wait()`. Can you show a proper path-following function?

# Answer
Describe the NPC's size and abilities in the agent parameters so paths fit it, honour `Jump` waypoints, and wait for each waypoint with a timeout scaled to the distance instead of an unbounded `Wait()`. The function reports why it stopped, so the caller can retry or give up.

```lua
--!strict
-- ModuleScript: ServerScriptService.PathFollower
local PathfindingService = game:GetService("PathfindingService")

export type Result = "Reached" | "NoPath" | "Stuck"

local PathFollower = {}

PathFollower.agent = {
	AgentRadius = 2.5,
	AgentHeight = 6,
	AgentCanJump = true,
	WaypointSpacing = 4,
	Costs = { Water = 20 },
}

function PathFollower.stepTimeout(distance: number, walkSpeed: number): number
	return distance / math.max(walkSpeed, 1) * 1.5 + 0.5
end

function PathFollower.moveToWaypoint(humanoid: Humanoid, waypoint: PathWaypoint)
	if waypoint.Action == Enum.PathWaypointAction.Jump then
		humanoid.Jump = true
	end
	humanoid:MoveTo(waypoint.Position)
end

-- Yields until MoveToFinished fires or the timeout passes; true only if the humanoid reached the point.
local function waitForMove(humanoid: Humanoid, timeout: number): boolean
	local thread = coroutine.running()
	local settled = false
	local connection = humanoid.MoveToFinished:Once(function(reached: boolean)
		if not settled then
			settled = true
			task.spawn(thread, reached)
		end
	end)
	task.delay(timeout, function()
		if not settled then
			settled = true
			connection:Disconnect()
			task.spawn(thread, false)
		end
	end)
	return coroutine.yield()
end

function PathFollower.walkTo(humanoid: Humanoid, root: BasePart, goal: Vector3): Result
	local path = PathfindingService:CreatePath(PathFollower.agent)
	local ok = pcall(function()
		path:ComputeAsync(root.Position, goal)
	end)
	if not ok or path.Status ~= Enum.PathStatus.Success then
		return "NoPath"
	end
	local waypoints = path:GetWaypoints()
	for index = 2, #waypoints do
		local waypoint = waypoints[index]
		local timeout = PathFollower.stepTimeout((waypoint.Position - root.Position).Magnitude, humanoid.WalkSpeed)
		PathFollower.moveToWaypoint(humanoid, waypoint)
		if not waitForMove(humanoid, timeout) or humanoid.Health <= 0 then
			return "Stuck"
		end
	end
	return "Reached"
end

return PathFollower
```

- The first waypoint is the starting position, so following starts at index 2.
- `AgentRadius`/`AgentHeight` should be a little larger than the NPC's real size; paths through gaps it can barely fit look like snagging in practice.
- `Costs` makes the path avoid materials or PathfindingModifier labels (here water) unless there is no alternative.
- "Stuck" with a distance-based timeout replaces the infinite `Wait()`; the caller can jump, re-path from the current position, or teleport after a few failures.

# Test
```lua
local npc = __buildRig(Vector3.new(0, 3, 0))
npc.Parent = workspace
local humanoid = npc.Humanoid
local root = npc.HumanoidRootPart

local result = nil
task.spawn(function()
	result = item.walkTo(humanoid, root, Vector3.new(0, 3, -12))
end)
check("first move goes to the second waypoint", humanoid.__moveTo == Vector3.new(0, 3, -4))
humanoid.MoveToFinished:Fire(true)
humanoid.MoveToFinished:Fire(true)
humanoid.MoveToFinished:Fire(true)
check("reaches the goal after every waypoint", result == "Reached" and humanoid.__moveTo == Vector3.new(0, 3, -12))

local stuck = nil
task.spawn(function()
	stuck = item.walkTo(humanoid, root, Vector3.new(0, 3, -12))
end)
__advance(5)
check("timeout reports stuck instead of hanging", stuck == "Stuck")

game:GetService("PathfindingService").__status = Enum.PathStatus.NoPath
local none = nil
task.spawn(function()
	none = item.walkTo(humanoid, root, Vector3.new(50, 3, 0))
end)
check("no path reported", none == "NoPath")
game:GetService("PathfindingService").__status = nil

item.moveToWaypoint(humanoid, PathWaypoint.new(Vector3.new(1, 5, 1), Enum.PathWaypointAction.Jump))
check("jump waypoints make the humanoid jump", humanoid.Jump == true and humanoid.__moveTo == Vector3.new(1, 5, 1))
check("timeout grows with distance", item.stepTimeout(32, 16) > item.stepTimeout(4, 16))
```
