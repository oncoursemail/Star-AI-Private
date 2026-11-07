---
id: gb-eng-perf-sharedtable-aggregation
category: performance
topics: SharedTable, SharedTableRegistry, Parallel Luau, atomic increment, actors
source: original
---
# Request
I have several Actors scanning NPCs in parallel and each one wants to add "threat" points to map zones. A normal table can't be shared between Actors, and sending a message per update is a lot of traffic. How do I aggregate results from many Actors safely?

# Answer
Use a `SharedTable` registered under a name in `SharedTableRegistry`: every Actor gets the same table, and `SharedTable.increment` is atomic, so parallel writers never lose updates. A serial script drains it once per interval with `SharedTable.update`, which reads and removes each key atomically, so increments that land during the drain are kept for the next round.

```lua
--!strict
-- ModuleScript: ServerScriptService.ThreatMap (required by the worker Actors and by the director)
local SharedTableRegistry = game:GetService("SharedTableRegistry")

local TABLE_NAME = "ThreatMap"

local ThreatMap = {}

function ThreatMap.shared(): SharedTable
	return SharedTableRegistry:GetSharedTable(TABLE_NAME)
end

-- Safe to call from any Actor, including in the parallel phase.
function ThreatMap.add(st: SharedTable, zone: string, amount: number): ()
	if amount ~= amount or amount <= 0 then
		return
	end
	SharedTable.increment(st, zone, amount)
end

-- Serial phase: returns the accumulated threat per zone and resets those entries.
function ThreatMap.drain(st: SharedTable): { [string]: number }
	local out: { [string]: number } = {}
	local zones: { string } = {}
	for zone in st do -- collect keys first; do not modify a table while iterating it
		table.insert(zones, zone)
	end
	for _, zone in zones do
		SharedTable.update(st, zone, function(value: number?): number?
			out[zone] = value or 0
			return nil -- removing the key resets that zone
		end)
	end
	return out
end

return ThreatMap
```

```lua
--!strict
-- Script inside each worker Actor: scans its share of NPCs in parallel
local RunService = game:GetService("RunService")
local CollectionService = game:GetService("CollectionService")
local ThreatMap = require(game:GetService("ServerScriptService").ThreatMap)

local actor = script:GetActor()
local workerIndex = actor:GetAttribute("WorkerIndex") :: number
local workerCount = actor:GetAttribute("WorkerCount") :: number
local st = ThreatMap.shared()

RunService.Heartbeat:ConnectParallel(function()
	for i, npc in CollectionService:GetTagged("Hostile") do
		if i % workerCount == workerIndex then
			local zone = npc:GetAttribute("Zone")
			if type(zone) == "string" then
				ThreatMap.add(st, zone, 1)
			end
		end
	end
end)
```

- Reading instances and attributes is allowed in the parallel phase; `SharedTable` writes are allowed too, which is what makes this pattern cheaper than messaging.
- The director (a normal Script) calls `ThreatMap.drain(ThreatMap.shared())` every second or so and acts on the totals in the serial phase.
- SharedTables hold plain values (numbers, strings, booleans, other SharedTables); store instance references as ids or names.

# Test
```lua
local registry = game:GetService("SharedTableRegistry")
local tables = {}
registry.GetSharedTable = function(_, name)
	tables[name] = tables[name] or {}
	return tables[name]
end
SharedTable = {
	increment = function(st, key, delta)
		local old = st[key] or 0
		st[key] = old + delta
		return old
	end,
	update = function(st, key, fn)
		st[key] = fn(st[key])
	end,
}
```
```lua
local st = item.shared()
check("same table for every caller", item.shared() == st)
item.add(st, "North", 2)
item.add(st, "North", 3)
item.add(st, "South", 1)
item.add(st, "South", -4)
item.add(st, "South", 0 / 0)
local totals = item.drain(st)
check("increments aggregated", totals.North == 5 and totals.South == 1)
check("drain resets", next(st) == nil)
item.add(st, "East", 1)
check("new round starts fresh", item.drain(st).East == 1 and item.drain(st).East == nil)
```
