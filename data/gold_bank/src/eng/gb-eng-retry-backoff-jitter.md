---
id: gb-eng-retry-backoff-jitter
category: engineering-algorithm
topics: retry, exponential backoff, jitter, pcall, transient errors
source: original
---
# Request
I want one generic helper to retry flaky async calls (badge awards, HTTP to our own backend, MemoryStore reads). It should use exponential backoff, not hammer the service, and let me say which errors are not worth retrying. What does a good one look like?

# Answer
Call the function in `pcall`; on failure wait `base * 2^(attempt-1)` seconds capped at a maximum, with random jitter so many servers that failed together do not retry in lockstep. A `shouldRetry` predicate lets permanent errors fail fast.

```lua
--!strict
-- ModuleScript: ServerScriptService.Retry
export type Options = {
	attempts: number?,
	baseDelay: number?,
	maxDelay: number?,
	shouldRetry: ((err: string) -> boolean)?,
	rng: Random?,
}

local Retry = {}

function Retry.backoffDelay(attempt: number, baseDelay: number, maxDelay: number, rng: Random): number
	local ceiling = math.min(maxDelay, baseDelay * 2 ^ (attempt - 1))
	-- jitter: anywhere between half and all of the ceiling
	local roll: number = rng:NextNumber()
	return ceiling * (0.5 + 0.5 * roll)
end

function Retry.call<T>(fn: () -> T, options: Options?): (boolean, T | string)
	local opts: Options = options or {}
	local attempts = opts.attempts or 4
	local baseDelay = opts.baseDelay or 0.5
	local maxDelay = opts.maxDelay or 8
	local rng = opts.rng or Random.new()
	local lastErr = "no attempts made"
	for attempt = 1, attempts do
		local ok, result = pcall(fn)
		if ok then
			return true, result
		end
		lastErr = tostring(result)
		if opts.shouldRetry and not opts.shouldRetry(lastErr) then
			break
		end
		if attempt < attempts then
			task.wait(Retry.backoffDelay(attempt, baseDelay, maxDelay, rng))
		end
	end
	return false, lastErr
end

return Retry
```

- Usage: `local ok, err = Retry.call(function() BadgeService:AwardBadge(userId, badgeId) end, { attempts = 3 })`; log `err` when `ok` is false.
- Jitter matters after a service outage: without it, every server that failed at the same moment retries at the same moment again.
- Pass `shouldRetry = function(e) return not string.find(e, "not found", 1, true) end` style predicates for errors that will never succeed. The helper yields, so call it from a thread that may wait, not from inside a callback that must return immediately.

# Test
```lua
local rng = Random.new(3)
local d1 = item.backoffDelay(1, 1, 8, rng)
local d4 = item.backoffDelay(4, 1, 8, rng)
local d9 = item.backoffDelay(9, 1, 8, rng)
check("delays grow and stay in jitter band", d1 >= 0.5 and d1 <= 1 and d4 >= 4 and d4 <= 8)
check("delay capped at max", d9 <= 8 and d9 >= 4)

local calls = 0
local result
task.spawn(function()
	result = table.pack(item.call(function()
		calls += 1
		if calls < 3 then
			error("busy", 0)
		end
		return "done"
	end, { baseDelay = 1, rng = Random.new(1) }))
end)
check("waits between attempts", calls == 1 and result == nil)
__advance(10)
check("succeeds on third attempt", calls == 3 and result[1] == true and result[2] == "done")

local permanent = 0
local res2
task.spawn(function()
	res2 = table.pack(item.call(function()
		permanent += 1
		error("item not found", 0)
	end, { shouldRetry = function(e) return not string.find(e, "not found", 1, true) end }))
end)
check("permanent error fails fast", permanent == 1 and res2[1] == false and res2[2] == "item not found")

local always = 0
local res3
task.spawn(function()
	res3 = table.pack(item.call(function()
		always += 1
		error("down", 0)
	end, { attempts = 3, baseDelay = 0.1 }))
end)
__advance(5)
check("gives up after attempts", always == 3 and res3[1] == false and res3[2] == "down")
```
