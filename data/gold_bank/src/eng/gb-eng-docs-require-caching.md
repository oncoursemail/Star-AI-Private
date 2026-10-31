---
id: gb-eng-docs-require-caching
category: docs-question
topics: ModuleScript, require caching, shared state, client server boundary, module errors
source: original
---
# Request
How does `require` actually work? If two scripts require the same ModuleScript, do they get separate copies? And does a module required on the server share anything with the same module required on a client?

# Answer
A ModuleScript's code runs once per Luau environment, the first time it is required; the value it returns is cached and every later `require` of the same ModuleScript returns that same value. So two server scripts share one table (and any state stored in it), while the server and each client each run the module separately, with no shared memory between them.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.SessionCounter
-- Everything at the top level runs once per environment (once on the server, once per client).
local createdAt = os.clock()
local counts: { [string]: number } = {}

local SessionCounter = {}

function SessionCounter.bump(key: string): number
	counts[key] = (counts[key] or 0) + 1
	return counts[key]
end

function SessionCounter.get(key: string): number
	return counts[key] or 0
end

function SessionCounter.uptime(): number
	return os.clock() - createdAt
end

return table.freeze(SessionCounter)
```

- Script A calling `SessionCounter.bump("kills")` and Script B calling `SessionCounter.get("kills")` on the server see the same number, because both received the same cached table. A LocalScript requiring it sees its own, separate counts.
- To share data between server and clients, use RemoteEvents, attributes or replicated instances; module state never crosses the network.
- If the module errors while loading, `require` errors too, and later requires of that module fail as well instead of re-running it; fix the error rather than retrying the require.
- `require` yields only if the module's top-level code yields; keep top-level code fast and move waits into functions so requiring the module stays cheap.

# Test
```lua
local first = item
check("module state persists across calls", first.bump("kills") == 1 and first.bump("kills") == 2)
check("readers see the same state", first.get("kills") == 2 and first.get("deaths") == 0)
__advance(3)
check("top level ran once at load", math.abs(first.uptime() - 3) < 1e-9)
check("returned table frozen so callers cannot replace functions", not pcall(function() first.bump = nil end))
```
