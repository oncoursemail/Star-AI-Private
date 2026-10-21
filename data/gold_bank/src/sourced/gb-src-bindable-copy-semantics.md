---
id: gb-src-bindable-copy-semantics
category: engineering-debugging
topics: BindableEvent, BindableFunction, table copy, metatables, server script communication, ModuleScript signal
source: adapted
source_id: creator-docs
source_path: content/en-us/scripting/events/bindable.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I fire a BindableEvent from my RoundService with a `Round` object (a table with a metatable so it has methods). The listener in another server script gets the data but `round:getTimeLeft()` errors with "attempt to call a nil value", and changes it makes to the table don't show up in RoundService. What's going on?

# Answer
Bindables copy table arguments: the receiver gets a new table, its metatable is stripped (so methods disappear), and edits never reach the original. Pass plain data through bindables, or, for objects shared between server scripts, use a ModuleScript that both require, which passes real references.

```lua
--!strict
-- ModuleScript: ServerScriptService.RoundEvents
export type Round = {
	id: number,
	endsAt: number,
	getTimeLeft: (self: Round) -> number,
}

type Listener = (round: Round) -> ()

local RoundEvents = {}
local listeners: { [number]: Listener } = {}
local nextId = 0

function RoundEvents.onRoundStarted(listener: Listener): () -> ()
	nextId += 1
	local id = nextId
	listeners[id] = listener
	return function()
		listeners[id] = nil
	end
end

function RoundEvents.fireRoundStarted(round: Round)
	local snapshot: { Listener } = {}
	for _, listener in listeners do
		table.insert(snapshot, listener)
	end
	for _, listener in snapshot do
		task.spawn(listener, round)
	end
end

return RoundEvents
```

- Every script that requires the module gets the same table, so listeners receive the exact `Round` object with its methods.
- `task.spawn` runs each listener in its own thread, like a bindable does, so one erroring or yielding listener does not block the others.
- The returned function disconnects the listener, the same job `RBXScriptConnection:Disconnect()` does.
- Keep bindables for plain data such as `{ "Sword", "Bow" }` or `{ CharName = "Diva" }`; avoid mixed tables there too.

# Test
```lua
local RoundMeta = {}
RoundMeta.__index = RoundMeta
function RoundMeta.getTimeLeft(self)
	return self.endsAt - 10
end
local round = setmetatable({ id = 1, endsAt = 70 }, RoundMeta)
local received, timeLeft
local disconnect = item.onRoundStarted(function(r)
	received = r
	timeLeft = r:getTimeLeft()
end)
item.fireRoundStarted(round)
check("same object, not a copy", received == round)
check("methods still work", timeLeft == 60)
disconnect()
received = nil
item.fireRoundStarted(round)
check("disconnected listener not called", received == nil)
```
