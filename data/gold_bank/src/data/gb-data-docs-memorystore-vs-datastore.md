---
id: gb-data-docs-memorystore-vs-datastore
category: docs-question
topics: MemoryStoreService, DataStoreService, choosing storage, expiration, cross-server
source: original
---
# Request
When should I use MemoryStoreService instead of DataStores? I want a list of which servers are running events right now, a matchmaking queue, and player inventories.

# Answer
DataStores are for data that must survive forever: inventories, currency, settings. MemoryStores are fast, shared, temporary memory across all servers: every entry has an expiration (at most 45 days) and the data is not backed up, so they suit live coordination such as matchmaking queues, cross-server locks and cooldowns, and "what is happening right now" lists. For your three: running events and the queue go in MemoryStore, inventories in a DataStore.

```lua
--!strict
-- A live "servers with an active event" registry: MemoryStore, because it only matters while servers run.
local MemoryStoreService = game:GetService("MemoryStoreService")

local registry = MemoryStoreService:GetSortedMap("ActiveEvents")
local TTL = 90 -- seconds; each server refreshes its entry every 30 s, so crashed servers vanish by themselves

local ActiveEvents = {}

function ActiveEvents.announce(eventName: string, playerCount: number): boolean
	local jobId: string = game.JobId
	return (pcall(function()
		registry:SetAsync(jobId, { event = eventName, players = playerCount }, TTL)
	end))
end

function ActiveEvents.clear(): boolean
	local jobId: string = game.JobId
	return (pcall(function()
		registry:RemoveAsync(jobId)
	end))
end

function ActiveEvents.list(limit: number): { { key: string, value: any } }
	local ok, rows = pcall(function()
		return registry:GetRangeAsync(Enum.SortDirection.Ascending, limit)
	end)
	return if ok then rows else {}
end

return ActiveEvents
```

- Expiration is a feature here: a server that crashes cannot clean up, but its entry expires; a DataStore entry would stay forever.
- MemoryStore quotas scale with the experience's concurrent players, and requests are fast (milliseconds), which is why per-second polling of a queue is acceptable there but not on a DataStore.
- Never keep the only copy of anything valuable in a MemoryStore; if it must persist, write it to a DataStore too.

# Test
```lua
game.JobId = "server-1"
check("announcing works", item.announce("MeteorShower", 12))
game.JobId = "server-2"
item.announce("BossFight", 30)
local rows = item.list(10)
check("both servers are listed", #rows == 2 and rows[1].key == "server-1" and rows[2].value.event == "BossFight")
check("clearing removes this server only", item.clear() and #item.list(10) == 1)
check("limit is respected", #item.list(0) == 0)
```
