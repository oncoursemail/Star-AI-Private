---
id: gb-world-npc-patrol-route
category: npc-pathing
topics: patrol, waypoints, ping-pong, MoveToFinished, guard NPC
source: original
---
# Request
I want a guard NPC that walks between patrol points I place in a folder, pauses at each one, and either loops or goes back and forth. The points should be ordered by a number I set, not by their names. Can you write it?

# Answer
Read the points once, sort them by an `Order` attribute, and run the patrol in its own thread: move, wait for arrival (with a timeout so a blocked guard keeps going), pause, then pick the next index according to the mode. A stop function ends the thread cleanly so the guard can switch to chasing.

```lua
--!strict
-- ModuleScript: ServerScriptService.Patrol
export type Mode = "Loop" | "PingPong"
export type Patrol = {
	stopPatrol: () -> (),
	targetIndex: () -> number,
}

local Patrol = {}

function Patrol.orderedPoints(folder: Instance): { BasePart }
	local points: { BasePart } = {}
	for _, child in folder:GetChildren() do
		if child:IsA("BasePart") and type(child:GetAttribute("Order")) == "number" then
			table.insert(points, child)
		end
	end
	table.sort(points, function(a: BasePart, b: BasePart): boolean
		return (a:GetAttribute("Order") :: number) < (b:GetAttribute("Order") :: number)
	end)
	return points
end

function Patrol.nextIndex(index: number, direction: number, count: number, mode: Mode): (number, number)
	if count <= 1 then
		return 1, direction
	end
	if mode == "Loop" then
		return index % count + 1, 1
	end
	local nextValue = index + direction
	if nextValue > count or nextValue < 1 then
		direction = -direction
		nextValue = index + direction
	end
	return nextValue, direction
end

function Patrol.start(humanoid: Humanoid, points: { BasePart }, mode: Mode, pause: number): Patrol
	assert(#points > 0, "patrol needs at least one point")
	local running = true
	local index, direction = 1, 1
	local arrived = false
	local connection = humanoid.MoveToFinished:Connect(function()
		arrived = true
	end)

	task.spawn(function()
		while running and humanoid.Health > 0 do
			arrived = false
			humanoid:MoveTo(points[index].Position)
			local waited = 0
			while running and not arrived and waited < 8 do
				waited += task.wait(0.1)
			end
			if not running then
				break
			end
			task.wait(pause)
			index, direction = Patrol.nextIndex(index, direction, #points, mode)
		end
		connection:Disconnect()
	end)

	return {
		stopPatrol = function()
			running = false
		end,
		targetIndex = function(): number
			return index
		end,
	}
end

return Patrol
```

Usage: `local patrol = Patrol.start(guard.Humanoid, Patrol.orderedPoints(workspace.GuardRoute), "PingPong", 2)`; call `patrol.stopPatrol()` when the guard spots someone and start a new patrol when it gives up the chase.

- Sorting by an attribute lets level designers insert a point between 2 and 3 by giving it Order 2.5, with no renaming.
- The 8-second cap mirrors Humanoid:MoveTo's own timeout, so a guard blocked by a crate moves on to the next point instead of freezing.
- `nextIndex` is pure, which makes the loop/ping-pong order easy to verify.

# Test
```lua
local folder = Instance.new("Folder")
for i, order in { 3, 1, 2 } do
	local p = Instance.new("Part")
	p.Name = "P" .. i
	p.Position = Vector3.new(order * 10, 0, 0)
	p:SetAttribute("Order", order)
	p.Parent = folder
end
local points = item.orderedPoints(folder)
check("points sorted by Order attribute", points[1].Position.X == 10 and points[3].Position.X == 30)

local seq, i, d = {}, 1, 1
for _ = 1, 5 do
	i, d = item.nextIndex(i, d, 3, "PingPong")
	table.insert(seq, i)
end
check("ping-pong goes back and forth", table.concat(seq, ",") == "2,3,2,1,2")
check("loop wraps around", (item.nextIndex(3, 1, 3, "Loop")) == 1)

local guard = __buildRig(Vector3.new(0, 3, 0))
guard.Parent = workspace
local humanoid = guard.Humanoid
local patrol = item.start(humanoid, points, "Loop", 1)
check("walks to the first point", humanoid.__moveTo == points[1].Position)
humanoid.MoveToFinished:Fire(true)
__advance(1.3)
check("after pausing moves to the next point", humanoid.__moveTo == points[2].Position)
__advance(10)
check("blocked guard gives up and continues", humanoid.__moveTo == points[3].Position)
patrol.stopPatrol()
__advance(20)
check("stopped patrol issues no more moves", humanoid.__moveTo == points[3].Position)
```
