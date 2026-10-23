---
id: gb-eng-typed-event-bus
category: luau-typing
topics: event bus, typed events, generics, decoupling, strict mode
source: original
---
# Request
I have a global event bus where everything goes through `Bus.emit("EnemyKilled", ...)` with string names, and handlers get untyped varargs. A typo in an event name silently does nothing. How do I keep the decoupling but get typed events?

# Answer
Replace string keys with one typed channel per event, declared in a single table. Each channel is generic over its payload, so emitting with the wrong arguments or subscribing to a misspelled event is caught by the analyzer.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.GameEvents
export type Channel<T...> = {
	subscribe: (self: Channel<T...>, handler: (T...) -> ()) -> () -> (),
	emit: (self: Channel<T...>, T...) -> (),
}

local function channel<T...>(): Channel<T...>
	local handlers: { [number]: (T...) -> () } = {}
	local nextId = 0
	return {
		subscribe = function(_self: Channel<T...>, handler: (T...) -> ()): () -> ()
			nextId += 1
			local id = nextId
			handlers[id] = handler
			return function()
				handlers[id] = nil
			end
		end,
		emit = function(_self: Channel<T...>, ...: T...)
			-- snapshot first: a handler may subscribe or unsubscribe while we iterate
			local snapshot: { (T...) -> () } = {}
			for _, handler in handlers do
				table.insert(snapshot, handler)
			end
			for _, handler in snapshot do
				task.spawn(handler, ...)
			end
		end,
	}
end

local GameEvents = table.freeze({
	EnemyKilled = channel() :: Channel<Player, string>, -- killer, enemy type
	CoinsAwarded = channel() :: Channel<Player, number>,
	RoundEnded = channel() :: Channel<number>, -- round number
})

return GameEvents
```

- `GameEvents.EnemyKiled:subscribe(...)` is an unknown-key error because the table is a sealed literal, which fixes the silent-typo problem.
- `subscribe` returns an unsubscribe function, so owners clean up with one call: `local stop = GameEvents.RoundEnded:subscribe(onRoundEnded)` then `stop()`.
- Handler order is not guaranteed (ids live in a hash table); each runs in its own thread so a failing handler cannot block the rest.

# Test
```lua
local kills = {}
local stop = item.EnemyKilled:subscribe(function(player, enemy)
	table.insert(kills, player .. "/" .. enemy)
end)
local coins = 0
item.CoinsAwarded:subscribe(function(_, amount)
	coins += amount
end)
item.EnemyKilled:emit("ana", "wolf")
item.CoinsAwarded:emit("ana", 15)
check("typed channel delivers", kills[1] == "ana/wolf" and coins == 15)
stop()
item.EnemyKilled:emit("ana", "bear")
check("unsubscribe works", #kills == 1)
check("channels are independent", coins == 15)
check("bus table frozen", not pcall(function() item.NewEvent = 1 end))
```
