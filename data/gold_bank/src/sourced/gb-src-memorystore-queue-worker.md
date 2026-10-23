---
id: gb-src-memorystore-queue-worker
category: messaging
topics: MemoryStoreService, queue, AddAsync, ReadAsync, RemoveAsync, invisibility timeout, matchmaking
source: adapted
source_id: creator-docs
source_path: content/en-us/cloud-services/memory-stores/queue.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
For a matchmaking lobby, players across servers go into a shared queue and one server pulls them out in groups of 8. How do I read from a MemoryStore queue without losing entries if a server dies mid-batch?

# Answer
Add entries with `AddAsync`, and in the worker call `ReadAsync` with an invisibility timeout. Read items are hidden, not deleted; only `RemoveAsync(readId)` after you finish handling them deletes them. If the server crashes first, the items reappear when the timeout ends.

```lua
--!strict
local MemoryStoreService = game:GetService("MemoryStoreService")

local BATCH_SIZE = 8
local WAIT_TIMEOUT = 30
local ENTRY_EXPIRATION = 300

local queue = MemoryStoreService:GetQueue("Matchmaking", 30)

local function enqueue(userId: number): boolean
	local ok, err = pcall(function()
		queue:AddAsync(userId, ENTRY_EXPIRATION)
	end)
	if not ok then
		warn("Enqueue failed:", err)
	end
	return ok
end

local function runWorker(handleBatch: ({ number }) -> boolean)
	while true do
		local ok, items, readId = pcall(function()
			return queue:ReadAsync(BATCH_SIZE, true, WAIT_TIMEOUT)
		end)
		if not ok then
			task.wait(2)
		elseif #items > 0 and handleBatch(items) then
			local removed, err = pcall(function()
				queue:RemoveAsync(readId)
			end)
			if not removed then
				warn("Remove failed, batch will reappear:", err)
			end
		end
	end
end

return { enqueue = enqueue, runWorker = runWorker }
```

- `GetQueue(name, 30)` sets a 30 second invisibility timeout for items returned by `ReadAsync`.
- `ReadAsync(count, allOrNothing, waitTimeout)`: with `allOrNothing = true` it returns nothing until a full group of 8 is available, and it waits up to 30 s itself, so the loop does not busy-spin.
- The batch is removed only after `handleBatch` returns true (for example after the teleport succeeded).
