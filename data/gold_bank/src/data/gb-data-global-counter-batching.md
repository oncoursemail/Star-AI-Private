---
id: gb-data-global-counter-batching
category: datastore-safety
topics: DataStore, IncrementAsync, global counter, batching, BindToClose
source: original
---
# Request
I want a "total eggs hatched worldwide" counter. Right now I call IncrementAsync on every hatch and in busy servers it gets throttled. How should I count this across all servers?

# Answer
Count hatches in memory per server and flush the pending amount with one `IncrementAsync` every 30 seconds, plus once in `BindToClose`. Move the pending count out before the call and add it back if the call fails, so a failed flush does not lose hatches.

```lua
--!strict
-- ModuleScript: ServerScriptService.GlobalCounter
local DataStoreService = game:GetService("DataStoreService")

local store = DataStoreService:GetDataStore("GlobalStats")
local FLUSH_INTERVAL = 30

export type Counter = {
	add: (amount: number) -> (),
	flush: () -> boolean,
	lastKnownTotal: () -> number,
}

local GlobalCounter = {}

function GlobalCounter.new(key: string): Counter
	local pending = 0
	local total = 0

	local function add(amount: number)
		-- IncrementAsync takes integers only; this also rejects NaN and infinity (inf % 1 is NaN)
		if amount > 0 and amount % 1 == 0 then
			pending += amount
		end
	end

	local function flush(): boolean
		if pending == 0 then
			return true
		end
		local sending = pending
		pending = 0
		local ok, newTotal = pcall(function()
			return store:IncrementAsync(key, sending)
		end)
		if ok then
			total = newTotal
		else
			pending += sending
		end
		return ok
	end

	task.spawn(function()
		while true do
			task.wait(FLUSH_INTERVAL)
			flush()
		end
	end)

	game:BindToClose(function()
		flush()
	end)

	return {
		add = add,
		flush = flush,
		lastKnownTotal = function(): number
			return total + pending
		end,
	}
end

return GlobalCounter
```

Usage: `local eggs = GlobalCounter.new("EggsHatched")`, then `eggs.add(1)` in the hatch code and show `eggs.lastKnownTotal()` on the board.

- One write per server every 30 seconds stays far below the limits however busy the server is.
- `IncrementAsync` returns the new global total, so the board refreshes for free on each flush without an extra read.
- The total only moves forward from this server's view between flushes; other servers' hatches appear on the next flush.

# Test
```lua
local ds = game:GetService("DataStoreService")
local store = ds:GetDataStore("GlobalStats")
local eggs = item.new("EggsHatched")

local before = ds.__calls
for _ = 1, 25 do
	eggs.add(1)
end
check("adds are counted locally, no requests yet", ds.__calls == before and eggs.lastKnownTotal() == 25)

__advance(31)
check("one flush writes the whole batch", ds.__calls == before + 1 and store:GetAsync("EggsHatched") == 25)

store:IncrementAsync("EggsHatched", 100)
eggs.add(5)
ds.__failNext = 1
__advance(30)
check("failed flush keeps the pending amount", eggs.lastKnownTotal() == 30)
__advance(30)
check("next flush sends it and picks up other servers' totals", store:GetAsync("EggsHatched") == 130 and eggs.lastKnownTotal() == 130)

eggs.add(-10)
eggs.add(0 / 0)
eggs.add(1.5)
eggs.add(math.huge)
check("negative, NaN, fractional and infinite amounts are ignored", eggs.lastKnownTotal() == 130)

eggs.add(2)
__close()
check("shutdown flushes the rest", store:GetAsync("EggsHatched") == 132)
```
