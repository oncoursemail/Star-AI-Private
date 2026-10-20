---
id: gb-eng-perf-time-sliced-loop
category: performance
topics: time slicing, frame budget, os.clock, background work, Heartbeat
source: original
---
# Request
Once a minute my server recalculates the "value" of every placed object in the world (about 20,000 of them) for the leaderboard, and the whole server hitches for half a second. The calculation itself is fine, it just runs all at once. How do I spread it across frames?

# Answer
Time-slice it: process items until a per-frame budget (say 2 ms) is used, then yield to the next frame and continue where you stopped. The total work is unchanged, but no single frame pays for all of it.

```lua
--!strict
-- ModuleScript: ServerScriptService.TimeSliced
local RunService = game:GetService("RunService")

local TimeSliced = {}

-- Calls work(item) for every element, spending at most budgetSeconds per frame.
-- Yields between frames; returns the number of frames it took.
function TimeSliced.forEach<T>(list: { T }, budgetSeconds: number, work: (T) -> ()): number
	local frames = 1
	local frameStart = os.clock()
	for i = 1, #list do
		work(list[i])
		if os.clock() - frameStart >= budgetSeconds and i < #list then
			RunService.Heartbeat:Wait()
			frames += 1
			frameStart = os.clock()
		end
	end
	return frames
end

return TimeSliced
```

```lua
--!strict
-- Script: ServerScriptService.ValueRecalc
local ServerScriptService = game:GetService("ServerScriptService")
local CollectionService = game:GetService("CollectionService")
local Players = game:GetService("Players")
local TimeSliced = require(ServerScriptService.TimeSliced)

local BUDGET = 0.002

while true do
	local totals: { [number]: number } = {}
	local placed = CollectionService:GetTagged("Placed")
	TimeSliced.forEach(placed, BUDGET, function(model: Instance)
		local owner = model:GetAttribute("OwnerId")
		local value = model:GetAttribute("Value")
		if type(owner) == "number" and type(value) == "number" then
			totals[owner] = (totals[owner] or 0) + value
		end
	end)
	for _, player in Players:GetPlayers() do
		player:SetAttribute("PlacedValue", totals[player.UserId] or 0)
	end
	task.wait(60)
end
```

- The list is snapshotted (`GetTagged` returns a new array), so objects added or removed mid-pass do not break the loop; an object destroyed before its turn just reads nil attributes and is skipped.
- 2 ms is a good default on a 16.7 ms frame; raise it for work players wait on, lower it if other systems are already heavy.
- Results are only consistent at the end of the pass, so publish them (leaderboard, attributes) after `forEach` returns, not item by item.

# Test
```lua
local list = {}
for i = 1, 100 do
	list[i] = i
end
local sum = 0
local frames
task.spawn(function()
	frames = item.forEach(list, 0.0095, function(n)
		sum += n
		__now += 0.001 -- each item "costs" 1 ms of virtual time
	end)
end)
check("first frame stops at the budget", sum == 55 and frames == nil)
for _ = 1, 20 do
	game:GetService("RunService").Heartbeat:Fire(1 / 60)
end
check("all items processed eventually", sum == 5050)
check("spread over ten frames", frames == 10)
local quick
task.spawn(function()
	quick = item.forEach({ 1, 2, 3 }, 0.01, function() end)
end)
check("small job finishes in one frame without yielding", quick == 1)
```
