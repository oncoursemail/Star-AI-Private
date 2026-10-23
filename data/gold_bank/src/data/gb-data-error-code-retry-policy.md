---
id: gb-data-error-code-retry-policy
category: datastore-safety
topics: DataStore, error codes, retry policy, throttling, pcall
source: original
---
# Request
My retry wrapper retries every DataStore error five times, even ones like "value too large" that will never succeed, and that wastes the whole save window at shutdown. How do I decide which errors are worth retrying?

# Answer
DataStore error messages start with a numeric code, and the code family tells you what to do: 1xx means the request itself is wrong (your bug, never retry), 3xx means you were throttled (retry after a longer wait), 4xx means access or configuration problems (retrying will not help), and 5xx is mixed: a few codes are transient service failures worth a retry with backoff (501, 502, 504, 505), while others never succeed (511-513 mean a malformed or oversized UserId or metadata, and 503 means the key was not found). Parse the code and let the policy decide, and retry only the codes you know are transient.

```lua
--!strict
-- ModuleScript: ServerScriptService.DataErrors
export type Decision = "retry" | "retry_slow" | "give_up"

local MAX_ATTEMPTS = 5
local TRANSIENT_SERVER_CODES: { [number]: boolean } = { [501] = true, [502] = true, [504] = true, [505] = true }

local DataErrors = {}

function DataErrors.code(err: any): number?
	local digits = string.match(tostring(err), "^(%d%d%d):")
	return if digits then tonumber(digits) else nil
end

function DataErrors.decide(err: any): Decision
	local code = DataErrors.code(err)
	if code == nil then
		return "retry" -- unknown shape (network hiccup, engine message): one more try is cheap
	elseif code >= 100 and code < 200 then
		return "give_up" -- bad key, bad value, value too large
	elseif code >= 300 and code < 400 then
		return "retry_slow"
	elseif TRANSIENT_SERVER_CODES[code] then
		return "retry"
	end
	return "give_up"
end

-- Same calling style as pcall: DataErrors.call(store.UpdateAsync, store, key, fn)
function DataErrors.call(fn: (...any) -> ...any, ...: any): (boolean, any)
	local delay = 1
	local lastError: any = nil
	for attempt = 1, MAX_ATTEMPTS do
		local ok, result = pcall(fn, ...)
		if ok then
			return true, result
		end
		lastError = result
		local decision = DataErrors.decide(result)
		if decision == "give_up" or attempt == MAX_ATTEMPTS then
			break -- no pointless wait after the last attempt
		end
		task.wait(if decision == "retry_slow" then delay * 3 else delay)
		delay *= 2
	end
	return false, lastError
end

return DataErrors
```

- A 1xx failure at save time usually means the data itself is bad (NaN, an Instance, a mixed table, over 4 MB); log the key and the error once and fix the data instead of hammering the service.
- 4xx in Studio usually means "Enable Studio Access to API Services" is off in Game Settings; it is not something a retry can fix.
- Keep the attempt count small for joins and give saves on leave and shutdown the remaining time budget instead.

# Test
```lua
check("parses the code", item.code("502: API Services rejected request") == 502)
check("value too large is not retried", item.decide("105: Serialized value exceeds 4MB limit.") == "give_up")
check("throttling waits longer", item.decide("304: UpdateAsync request dropped. Request was throttled") == "retry_slow")
check("transient server errors retry", item.decide("502: API Services rejected request") == "retry")
check("key not found is not retried", item.decide("503: DataStore request successful, but key not found") == "give_up")
check("malformed metadata is not retried", item.decide("512: Metadata attribute size exceeds 300 bytes limit") == "give_up")
check("access errors give up", item.decide("403: Cannot write to DataStore from studio") == "give_up")
check("unknown messages get a retry", item.decide("HTTP 0 (connection failed)") == "retry")

local calls = 0
local function badValue()
	calls += 1
	error("104: Cannot store Array in data store.", 0)
end
local ok = item.call(badValue)
check("a 1xx error stops after one attempt", ok == false and calls == 1)

local store = game:GetService("DataStoreService"):GetDataStore("PolicyTest")
store:SetAsync("k", 3)
game:GetService("DataStoreService").__failNext = 2
local result, value = nil, nil
task.spawn(function()
	result, value = item.call(store.GetAsync, store, "k")
end)
__advance(10)
check("5xx failures are retried until success", result == true and value == 3)

local slowCalls = 0
local finished = false
task.spawn(function()
	item.call(function()
		slowCalls += 1
		error("502: API Services rejected request", 0)
	end)
	finished = true
end)
__advance(15.5)
check("gives up after the last attempt without waiting again", finished and slowCalls == 5)
```
