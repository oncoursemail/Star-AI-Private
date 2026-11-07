---
id: gb-world-npc-chase-throttle
category: npc-pathing
topics: chase AI, re-path throttling, line of sight, PathfindingService, performance
source: original
---
# Request
I have 30 zombies chasing players and each one recomputes a path every 0.1 seconds. The server is dying. But if I recompute less often they run to where the player used to be. What's the standard approach?

# Answer
Mix two modes. When the zombie can see the target with nothing in between, skip pathfinding and `MoveTo` the target directly every update. Only when the view is blocked, compute a path, and recompute only if the target has moved far from the old goal or the path is getting old. Between recomputes the zombie keeps walking its current waypoints.

```lua
--!strict
-- ModuleScript: ServerScriptService.Chaser
local PathfindingService = game:GetService("PathfindingService")

export type Options = { repathDistance: number, repathInterval: number, sightRange: number }
export type Mode = "Direct" | "Path" | "Idle"
export type Chaser = {
	update: (target: BasePart) -> Mode,
	pathsComputed: () -> number,
}

local Chaser = {}

function Chaser.new(npc: Model, options: Options): Chaser
	local humanoid = npc:FindFirstChildOfClass("Humanoid")
	local root = npc:FindFirstChild("HumanoidRootPart")
	assert(humanoid and root and root:IsA("BasePart"), "NPC needs a Humanoid and HumanoidRootPart")

	local path = PathfindingService:CreatePath({ AgentRadius = 2, AgentHeight = 5, AgentCanJump = true })
	local waypoints: { PathWaypoint } = {}
	local waypointIndex = 0
	local lastGoal: Vector3? = nil
	local lastPathAt = -math.huge
	local lastFailed = false
	local computed = 0

	local function canSee(target: BasePart): boolean
		local offset = target.Position - root.Position
		if offset.Magnitude > options.sightRange or math.abs(offset.Y) > 6 then
			return false
		end
		local params = RaycastParams.new()
		params.FilterType = Enum.RaycastFilterType.Exclude
		params.FilterDescendantsInstances = { npc, target.Parent or target }
		return workspace:Raycast(root.Position, offset, params) == nil
	end

	local function repath(goal: Vector3)
		lastGoal = goal
		lastPathAt = os.clock()
		computed += 1
		local ok = pcall(function()
			path:ComputeAsync(root.Position, goal)
		end)
		lastFailed = not (ok and path.Status == Enum.PathStatus.Success)
		waypoints = if lastFailed then {} else path:GetWaypoints()
		waypointIndex = 2
	end

	local function update(target: BasePart): Mode
		if humanoid.Health <= 0 then
			return "Idle"
		end
		if canSee(target) then
			waypoints = {}
			lastFailed = false
			humanoid:MoveTo(target.Position)
			return "Direct"
		end
		local stale = os.clock() - lastPathAt > options.repathInterval
		local moved = lastGoal == nil or (target.Position - lastGoal).Magnitude > options.repathDistance
		-- An unreachable target (no waypoints after a failed compute) is retried once per interval, not every update.
		local needPath = if #waypoints == 0 then not lastFailed or stale else stale and moved
		if needPath then
			repath(target.Position)
		end
		local current = waypoints[waypointIndex]
		if current == nil then
			return "Idle"
		end
		local flat = current.Position - root.Position
		if Vector3.new(flat.X, 0, flat.Z).Magnitude < 2 and waypoints[waypointIndex + 1] then
			waypointIndex += 1
		end
		local waypoint: PathWaypoint = waypoints[waypointIndex]
		if waypoint.Action == Enum.PathWaypointAction.Jump then
			humanoid.Jump = true
		end
		humanoid:MoveTo(waypoint.Position)
		return "Path"
	end

	return {
		update = update,
		pathsComputed = function(): number
			return computed
		end,
	}
end

return Chaser
```

A single loop drives every zombie at a modest rate, staggered so they don't all path on the same frame:

```lua
--!strict
local Chaser = require(script.Parent:WaitForChild("Chaser"))

local function runZombie(zombie: Model, getTarget: () -> BasePart?)
	local chaser = Chaser.new(zombie, { repathDistance = 6, repathInterval = 1, sightRange = 80 })
	task.wait(math.random() * 0.25)
	while zombie.Parent do
		local target = getTarget()
		if target then
			chaser.update(target)
		end
		task.wait(0.25)
	end
end

return runZombie
```

- Direct chasing covers most of the time a zombie is actually near a player, at the cost of one raycast instead of a path computation.
- Requiring both "stale" and "moved" means a stationary target never triggers recomputes, and a moving one at most once per interval.
- A failed compute (player on a roof the zombie cannot reach) is also retried only once per interval, so 30 zombies under one tower do not path every update.
- Reusing one Path object per NPC avoids allocating a new one per computation.

# Test
```lua
local zombie = __buildRig(Vector3.new(0, 3, 0))
zombie.Parent = workspace
local victim = __buildRig(Vector3.new(0, 3, -20))
victim.Parent = workspace
local target = victim.HumanoidRootPart
local chaser = item.new(zombie, { repathDistance = 6, repathInterval = 1, sightRange = 80 })

check("clear line of sight chases directly", chaser.update(target) == "Direct" and zombie.Humanoid.__moveTo == target.Position)
check("no path computed while visible", chaser.pathsComputed() == 0)
local wall = Instance.new("Part")
wall.Anchored = true
wall.Size = Vector3.new(30, 20, 1)
wall.Position = Vector3.new(0, 5, -10)
wall.Parent = workspace
check("blocked view switches to a path", chaser.update(target) == "Path" and chaser.pathsComputed() == 1)
chaser.update(target)
__advance(2)
chaser.update(target)
check("stationary target is not re-pathed", chaser.pathsComputed() == 1)
target.Position = Vector3.new(15, 3, -25)
chaser.update(target)
check("moved target re-paths once the interval passed", chaser.pathsComputed() == 2)
target.Position = Vector3.new(-15, 3, -25)
chaser.update(target)
check("but not again before the interval", chaser.pathsComputed() == 2)
local pathfinding = game:GetService("PathfindingService")
local blocked = __buildRig(Vector3.new(0, 3, 0))
blocked.Parent = workspace
local stuck = item.new(blocked, { repathDistance = 6, repathInterval = 1, sightRange = 80 })
pathfinding.__status = Enum.PathStatus.NoPath
check("unreachable target idles", stuck.update(target) == "Idle" and stuck.pathsComputed() == 1)
stuck.update(target)
stuck.update(target)
check("unreachable target is not re-pathed every update", stuck.pathsComputed() == 1)
__advance(1.5)
stuck.update(target)
check("unreachable target is retried after the interval", stuck.pathsComputed() == 2)
pathfinding.__status = nil
zombie.Humanoid.Health = 0
check("dead NPC idles", chaser.update(target) == "Idle")
```
