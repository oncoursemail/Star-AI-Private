---
id: gb-world-npc-blocked-replan
category: npc-pathing
topics: Path.Blocked, replanning, dynamic obstacles, doors, PathfindingService
source: original
---
# Request
Doors in my map close on a timer, and NPCs that already computed a path walk straight into a closed door and stand there. I know `Path.Blocked` exists but I don't understand how to use it to recompute.

# Answer
`Path.Blocked` fires with the index of the waypoint that became blocked. If that index is still ahead of the NPC, abandon the current walk and compute a new path from where it stands. A replan limit stops an NPC from spinning forever when the goal is truly unreachable.

```lua
--!strict
-- ModuleScript: ServerScriptService.ReplanningWalker
local PathfindingService = game:GetService("PathfindingService")

export type Outcome = "Reached" | "Unreachable" | "Stuck"
export type Walker = {
	goTo: (goal: Vector3) -> Outcome,
	currentPath: () -> Path?,
	replans: () -> number,
}

local MAX_REPLANS = 5
local STEP_TIMEOUT = 4

local ReplanningWalker = {}

function ReplanningWalker.new(humanoid: Humanoid, root: BasePart, agent: { [string]: any }): Walker
	local path: Path? = nil
	local replanCount = 0

	-- Walks one computed path. Returns "Reached", "Blocked" or "Stuck".
	local function follow(current: Path): string
		local waypoints = current:GetWaypoints()
		local index = 2
		local thread = coroutine.running()
		local waiting = false
		local function wake(signal: string)
			if waiting then
				waiting = false
				task.spawn(thread, signal)
			end
		end
		local blocked = current.Blocked:Connect(function(blockedIndex: number)
			if blockedIndex >= index then
				wake("blocked")
			end
		end)
		local finished = humanoid.MoveToFinished:Connect(function(reached: boolean)
			wake(if reached then "moved" else "failed")
		end)

		local outcome = "Reached"
		while index <= #waypoints do
			humanoid:MoveTo(waypoints[index].Position)
			waiting = true
			local myStep = index
			task.delay(STEP_TIMEOUT, function()
				if index == myStep then
					wake("failed")
				end
			end)
			local signal = coroutine.yield()
			if signal == "blocked" then
				outcome = "Blocked"
				break
			elseif signal ~= "moved" then
				outcome = "Stuck"
				break
			end
			index += 1
		end
		waiting = false
		blocked:Disconnect()
		finished:Disconnect()
		return outcome
	end

	local function goTo(goal: Vector3): Outcome
		replanCount = 0
		while replanCount <= MAX_REPLANS do
			local newPath = PathfindingService:CreatePath(agent)
			local ok = pcall(function()
				newPath:ComputeAsync(root.Position, goal)
			end)
			if not ok or newPath.Status ~= Enum.PathStatus.Success then
				return "Unreachable"
			end
			path = newPath
			local result = follow(newPath)
			if result ~= "Blocked" then
				return if result == "Reached" then "Reached" else "Stuck"
			end
			replanCount += 1
		end
		return "Unreachable"
	end

	return {
		goTo = goTo,
		currentPath = function(): Path?
			return path
		end,
		replans = function(): number
			return replanCount
		end,
	}
end

return ReplanningWalker
```

- Blocks behind the NPC (an index it already passed) are ignored; only obstacles on the remaining route trigger a replan.
- Each replan starts from `root.Position`, so the new path begins where the NPC actually is, not where the old path started.
- Closed doors should be parts the pathfinder treats as obstacles (CanCollide on, or a PathfindingModifier with `PassThrough` off) so the new path routes around them.
- Call `goTo` from its own thread per NPC (`task.spawn`) because it yields while walking.

# Test
```lua
local npc = __buildRig(Vector3.new(0, 3, 0))
npc.Parent = workspace
local humanoid = npc.Humanoid
local walker = item.new(humanoid, npc.HumanoidRootPart, { AgentRadius = 2 })

local outcome = nil
task.spawn(function()
	outcome = walker.goTo(Vector3.new(0, 3, -16))
end)
local firstPath = walker.currentPath()
humanoid.MoveToFinished:Fire(true)
firstPath.Blocked:Fire(1)
check("a block behind the NPC is ignored", walker.currentPath() == firstPath and outcome == nil)
firstPath.Blocked:Fire(4)
check("a block ahead triggers a new path", walker.currentPath() ~= firstPath and walker.replans() == 1)
for _ = 1, 4 do
	humanoid.MoveToFinished:Fire(true)
end
check("the new path is followed to the goal", outcome == "Reached")

local stuck = nil
task.spawn(function()
	stuck = walker.goTo(Vector3.new(0, 3, -16))
end)
__advance(5)
check("no progress reports stuck", stuck == "Stuck")

local looping = nil
task.spawn(function()
	looping = walker.goTo(Vector3.new(0, 3, -16))
end)
for _ = 1, 7 do
	local p = walker.currentPath()
	if p and looping == nil then
		p.Blocked:Fire(5)
	end
end
check("endless blocking gives up after the replan limit", looping == "Unreachable")
```
