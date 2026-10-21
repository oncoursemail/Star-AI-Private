---
id: gb-data-docs-datastore-limits-errors
category: docs-question
topics: DataStore limits, request budget, key length, value size, error handling
source: original
---
# Request
What limits do DataStores have that I should design around, and what is the right way to handle their errors?

# Answer
The ones that shape most designs: a value can be at most 4 MB, key and store names at most 50 characters, a single key should not be written more than about once every 6 seconds, and each server gets a per-minute request budget per request type that grows with its player count (about 60 + 10 per player for reads and for writes). Every call can fail, so each one goes in `pcall`, transient failures (throttling and service errors) are retried with backoff, and a failed load must never lead to saving defaults.

```lua
--!strict
-- A pre-flight check you can run before a save: size, key and budget, with reasons.
local DataStoreService = game:GetService("DataStoreService")

local MAX_VALUE_BYTES = 4_000_000
local MAX_KEY_LENGTH = 50

-- Approximate encoded size, or nil when the value holds something a DataStore refuses: only strings, finite
-- numbers, booleans, buffers, and tables with all-string keys or a proper array 1..n (no cycles).
local function measure(value: any, seen: { [any]: boolean }): number?
	local kind = typeof(value)
	if kind == "string" then
		return #value + 2
	elseif kind == "number" then
		return if value == value and math.abs(value) ~= math.huge then 8 else nil
	elseif kind == "boolean" then
		return 5
	elseif kind == "buffer" then
		return buffer.len(value)
	elseif kind ~= "table" or seen[value] then
		return nil
	end
	seen[value] = true
	local count = 0
	local allStrings = true
	for key in value do
		count += 1
		if type(key) ~= "string" then
			allStrings = false
		end
	end
	if not allStrings then
		for index = 1, count do
			if value[index] == nil then
				return nil
			end
		end
	end
	local total = 2
	for key, child in value do
		local size = measure(child, seen)
		if size == nil then
			return nil
		end
		total += size + (if allStrings then #key + 3 else 1)
	end
	seen[value] = nil
	return total
end

local function canSave(key: string, value: any): (boolean, string?)
	if #key == 0 or #key > MAX_KEY_LENGTH then
		return false, "key must be 1-50 characters"
	end
	local size = measure(value, {})
	if size == nil then
		return false, "value is not serialisable (only strings, finite numbers, booleans, buffers and clean tables)"
	end
	if size > MAX_VALUE_BYTES then
		return false, "value is over the 4 MB limit"
	end
	if DataStoreService:GetRequestBudgetForRequestType(Enum.DataStoreRequestType.SetIncrementAsync) < 1 then
		return false, "write budget exhausted; wait and retry"
	end
	return true, nil
end

return canSave
```

- Budget: spend reads on joins, writes on autosave (every 1-2 minutes, only if changed), leave and `BindToClose`; never write on every coin change.
- Per-key limit: many servers writing one shared key (a global counter, a guild) need batching or `IncrementAsync`, not a write per event.
- Errors carry a numeric code at the start of the message: 1xx means your request is invalid (do not retry), 3xx throttling (retry later), a few 5xx service errors such as 502 (retry with backoff). Other 5xx codes never succeed on retry (503 means key not found, 511-513 mean a malformed or oversized UserId or metadata), so retry only codes you know are transient.
- In Studio, enable "Studio Access to API Services" in Game Settings, and use separate store names so tests never touch live data.

# Test
```lua
check("normal data passes", item("player_1", { coins = 10 }))
local okLong, whyLong = item(string.rep("k", 51), {})
check("long keys are refused", not okLong and string.find(whyLong, "50") ~= nil)
local okNaN, whyNaN = item("player_1", { coins = 0 / 0 })
check("unserialisable values are refused", not okNaN and string.find(whyNaN, "serialisable") ~= nil)
local okBig = item("player_1", { blob = string.rep("x", 4_100_000) })
check("oversized values are refused", not okBig)
check("instances are refused", not item("player_1", { part = Instance.new("Part") }))
check("mixed tables are refused", not item("player_1", { 1, 2, name = "x" }))
check("arrays with holes are refused", not item("player_1", { [1] = "a", [3] = "c" }))
check("buffers and arrays are accepted", item("player_1", { items = { "a", "b" }, raw = buffer.create(16) }))
```
