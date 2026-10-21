---
id: gb-eng-varargs-pack-select
category: luau-syntax
topics: varargs, table.pack, select, nil holes, deferred calls
source: original
---
# Request
I wrote a helper that queues function calls to run later: it stores `{...}` and later calls `fn(table.unpack(args))`. It loses arguments when one of them is nil, e.g. `queue(setTarget, nil, true)` arrives as `setTarget(nil, nil)`. Why, and how do I fix it?

# Answer
`{...}` builds an array, and `#t` on an array with nil holes is unreliable, so `table.unpack(t)` may stop early. `table.pack(...)` records the real count in `n`, and `table.unpack(t, 1, t.n)` replays every argument including nils. `select("#", ...)` gives the same count without allocating.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.CallQueue
export type CallQueue = {
	queue: (self: CallQueue, fn: (...any) -> (), ...any) -> (),
	flush: (self: CallQueue) -> number,
	pending: (self: CallQueue) -> number,
}

type Pending = { fn: (...any) -> (), args: { n: number, [number]: any } }

local CallQueue = {}

function CallQueue.new(): CallQueue
	local calls: { Pending } = {}
	local q = {} :: CallQueue

	function q.queue(_self: CallQueue, fn: (...any) -> (), ...: any)
		table.insert(calls, { fn = fn, args = table.pack(...) })
	end

	function q.flush(_self: CallQueue): number
		local batch = calls
		calls = {}
		for _, call in batch do
			task.spawn(call.fn, table.unpack(call.args, 1, call.args.n))
		end
		return #batch
	end

	function q.pending(_self: CallQueue): number
		return #calls
	end

	return q
end

function CallQueue.countArgs(...: any): number
	return select("#", ...)
end

return CallQueue
```

- `select("#", nil, true)` is 2 while `#{nil, true}` can be 0 or 2 depending on how the table was built; never rely on `#` for argument lists.
- `flush` swaps in a new list before running, so a queued call that queues another call lands in the next flush instead of looping forever.
- Each call runs in `task.spawn`, so one erroring callback does not drop the rest of the batch.

# Test
```lua
local q = item.new()
local seen = {}
q:queue(function(a, b, c)
	seen.first = { a, b, c, n = 3 }
end, nil, true, nil)
q:queue(function(...)
	seen.count = select("#", ...)
end, nil, nil, nil, 4)
check("calls wait until flush", q:pending() == 2 and seen.first == nil)
check("flush runs both", q:flush() == 2)
check("nil arguments kept in place", seen.first[1] == nil and seen.first[2] == true and seen.first[3] == nil)
check("trailing argument after nils survives", seen.count == 4)
check("countArgs counts nils", item.countArgs(nil, nil) == 2 and item.countArgs() == 0)
q:queue(function()
	q:queue(function() end)
end)
check("nested queue goes to next flush", q:flush() == 1 and q:pending() == 1)
```
