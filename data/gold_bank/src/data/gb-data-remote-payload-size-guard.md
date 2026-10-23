---
id: gb-data-remote-payload-size-guard
category: remote-security
topics: RemoteEvent, payload size, deep tables, server lag, wrapper
source: original
---
# Request
An exploiter lagged my server by firing a remote with a giant nested table. My handlers validate fields, but by then the server has already walked the whole thing. Can I reject oversized arguments before any handler logic runs?

# Answer
Wrap handlers in a guard that measures each argument with a bounded walk: it stops as soon as a string, table depth or total element count passes your limit, so a hostile payload costs only a small, fixed amount of work. Handlers connected through the guard only ever see arguments within those bounds, plus a per-player rate limit.

```lua
--!strict
-- ModuleScript: ServerScriptService.RemoteGuard
local Players = game:GetService("Players")

export type Limits = { maxString: number, maxDepth: number, maxElements: number, perSecond: number }

local RemoteGuard = {}

-- Returns false as soon as any limit is exceeded; `budget` counts every element visited.
local function within(value: unknown, limits: Limits, depth: number, budget: { n: number }): boolean
	budget.n += 1
	if budget.n > limits.maxElements then
		return false
	end
	local kind = type(value)
	if kind == "string" then
		return #(value :: string) <= limits.maxString
	elseif kind == "table" then
		if depth >= limits.maxDepth then
			return false
		end
		for k, v in value :: { [any]: any } do
			if not within(k, limits, depth + 1, budget) or not within(v, limits, depth + 1, budget) then
				return false
			end
		end
	end
	return true
end

function RemoteGuard.check(limits: Limits, ...: any): boolean
	local budget = { n = 0 }
	for i = 1, select("#", ...) do
		if not within((select(i, ...)), limits, 0, budget) then
			return false
		end
	end
	return true
end

function RemoteGuard.connect(remote: RemoteEvent, limits: Limits, handler: (Player, ...any) -> ()): RBXScriptConnection
	local last: { [Player]: { at: number, count: number } } = {}
	Players.PlayerRemoving:Connect(function(player: Player)
		last[player] = nil
	end)
	return remote.OnServerEvent:Connect(function(player: Player, ...: any)
		local now = os.clock()
		local window = last[player]
		if window == nil or now - window.at >= 1 then
			window = { at = now, count = 0 }
			last[player] = window
		end
		window.count += 1
		if window.count > limits.perSecond or not RemoteGuard.check(limits, ...) then
			return
		end
		handler(player, ...)
	end)
end

return RemoteGuard
```

Usage: `RemoteGuard.connect(saveOutfit, { maxString = 64, maxDepth = 3, maxElements = 200, perSecond = 5 }, onSaveOutfit)`; `onSaveOutfit` still validates the exact shape it expects.

- The walk visits at most `maxElements` values whatever the client sends, so the cost of rejecting a huge table is the same as checking a small one.
- Roblox already caps how much a single remote call can carry, but the server still deserialises it; the guard keeps your own code from doing more work than it must.
- Choose limits per remote: a chat-like remote needs longer strings, a "use ability" remote needs one short string and nothing else.

# Test
```lua
local limits = { maxString = 10, maxDepth = 2, maxElements = 20, perSecond = 3 }
check("small arguments pass", item.check(limits, "hello", 5, { a = 1 }))
check("long strings fail", not item.check(limits, string.rep("x", 11)))
check("deep tables fail", not item.check(limits, { { { 1 } } }))
local wide = {}
for i = 1, 100 do
	wide[i] = i
end
check("tables with too many elements fail", not item.check(limits, wide))
check("long string keys fail too", not item.check(limits, { [string.rep("k", 20)] = 1 }))

local remote = Instance.new("RemoteEvent")
local calls = 0
item.connect(remote, limits, function()
	calls += 1
end)
local p = __makePlayer(1, "Sender")
remote.OnServerEvent:Fire(p, "ok")
remote.OnServerEvent:Fire(p, wide)
check("guarded handler only sees valid payloads", calls == 1)
remote.OnServerEvent:Fire(p, "a")
remote.OnServerEvent:Fire(p, "b")
remote.OnServerEvent:Fire(p, "c")
check("rate limit applies per second", calls == 2)
__advance(1)
remote.OnServerEvent:Fire(p, "d")
check("the window resets", calls == 3)
```
