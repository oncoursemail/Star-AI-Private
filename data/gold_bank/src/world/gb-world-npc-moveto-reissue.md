---
id: gb-world-npc-moveto-reissue
category: npc-pathing
topics: Humanoid MoveTo, 8 second timeout, MoveToFinished, long walks, reissue
source: original
---
# Request
I call `npc.Humanoid:MoveTo(farAwayPoint)` and the NPC stops halfway across the map for no reason. The point is reachable in a straight line. Why does it stop?

# Answer
`Humanoid:MoveTo` gives up after 8 seconds if the target has not been reached, and fires `MoveToFinished(false)`. For long walks, issue the MoveTo again before that limit. The helper below keeps re-issuing it until the NPC arrives, dies, or an overall deadline passes, and returns whether it arrived.

```lua
--!strict
-- ModuleScript: ServerScriptService.LongMove
local REISSUE_EVERY = 6
local POLL = 0.1

local LongMove = {}

function LongMove.walk(humanoid: Humanoid, target: Vector3, deadline: number): boolean
	local reached = false
	local connection = humanoid.MoveToFinished:Connect(function(success: boolean)
		if success then
			reached = true
		end
	end)

	local started = os.clock()
	local lastIssue = -math.huge
	while not reached and humanoid.Health > 0 and os.clock() - started < deadline do
		if os.clock() - lastIssue >= REISSUE_EVERY then
			humanoid:MoveTo(target)
			lastIssue = os.clock()
		end
		task.wait(POLL)
	end

	connection:Disconnect()
	return reached
end

return LongMove
```

- Re-issuing at 6 seconds restarts the internal 8-second timer before it can expire, so the walk never stalls mid-way.
- `MoveToFinished(false)` (timed out or interrupted) is not treated as arrival; only `true` ends the walk successfully.
- The overall deadline is still needed: a straight line can be blocked by a wall the NPC cannot get around, and the caller decides what to do then.
- For anything that is not a clear straight line, use PathfindingService and walk the waypoints instead.

# Test
```lua
local npc = __buildRig(Vector3.new(0, 3, 0))
npc.Parent = workspace
local humanoid = npc.Humanoid
local target = Vector3.new(0, 3, -300)

local arrived = nil
task.spawn(function()
	arrived = item.walk(humanoid, target, 60)
end)
check("first MoveTo issued immediately", humanoid.__moveTo == target and humanoid.__moves == 1)
__advance(13)
check("MoveTo re-issued before the 8 second limit", humanoid.__moves == 3)
humanoid.MoveToFinished:Fire(false)
__advance(0.2)
check("a timed-out finish is not arrival", arrived == nil)
humanoid.MoveToFinished:Fire(true)
__advance(0.2)
check("arrival ends the walk", arrived == true)

local giveUp = nil
task.spawn(function()
	giveUp = item.walk(humanoid, target, 10)
end)
__advance(11)
check("deadline returns false", giveUp == false)

local died = nil
task.spawn(function()
	died = item.walk(humanoid, target, 60)
end)
humanoid.Health = 0
__advance(0.2)
check("death stops the walk", died == false)
```
