---
id: gb-src-hashmap-community-pool
category: messaging
topics: MemoryStoreService, hash map, UpdateAsync, cross-server state, expiration, community goal
source: adapted
source_id: creator-docs
source_path: content/en-us/cloud-services/memory-stores/hash-map.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I'm running a weekend event where all servers contribute wood and stone to one community build, capped at 500 of each. Every server needs to add contributions and show the shared totals. What's the right storage for that, and how do I avoid two servers overwriting each other?

# Answer
Use a memory store hash map: one key per resource, updated with `UpdateAsync`, which retries your transform if another server changed the value in between, so no contribution is lost. Cap inside the transform and give entries an expiration longer than the event.

```lua
--!strict
local MemoryStoreService = game:GetService("MemoryStoreService")

local CAP = 500
local EXPIRATION = 3 * 24 * 60 * 60

local pool = MemoryStoreService:GetHashMap("CommunityPool")

local CommunityPool = {}

function CommunityPool.contribute(resource: string, amount: number): number?
	if amount <= 0 or amount ~= amount then
		return nil
	end
	local ok, result = pcall(function()
		return pool:UpdateAsync(resource, function(current: { count: number }?): { count: number }?
			local entry = current or { count = 0 }
			if entry.count >= CAP then
				return nil
			end
			entry.count = math.min(CAP, entry.count + amount)
			return entry
		end, EXPIRATION)
	end)
	if not ok then
		warn("Contribution failed:", result)
		return nil
	end
	return if result then result.count else CAP
end

function CommunityPool.read(resource: string): number
	local ok, entry = pcall(function()
		return pool:GetAsync(resource)
	end)
	if ok and entry then
		return entry.count
	end
	return 0
end

return CommunityPool
```

- Returning `nil` from the transform cancels the update, so a full pool costs no write.
- The hash map is shared by all servers but is not permanent; copy the final totals into a data store when the event ends if you need them later.
- Refresh the displayed totals on a timer (every few seconds per server) rather than per player, to stay within the memory store request limits.
