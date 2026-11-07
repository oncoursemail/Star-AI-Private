---
id: gb-src-task-library-ordering
category: docs-question
topics: task.spawn, task.defer, task.delay, task.wait, task.cancel, scheduler, execution order
source: adapted
source_id: creator-docs
source_path: content/en-us/scripting/scheduler.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
What's actually the difference between `task.spawn`, `task.defer`, `task.delay` and `task.wait`? I use them interchangeably and sometimes things run in an order I don't expect.

# Answer
`task.spawn` runs the function right now, before the next line of the caller. `task.defer` runs it later in the current frame, after the caller yields or finishes. `task.delay(t, f)` runs it after at least `t` seconds. `task.wait(t)` pauses the current thread for at least `t` seconds and returns how long it actually waited. `delay`, `defer` and `spawn` return the thread, which `task.cancel` can stop.

```lua
--!strict
local Order = {}

function Order.demo(log: { string }): thread
	task.defer(function()
		table.insert(log, "deferred")
	end)
	task.spawn(function()
		table.insert(log, "spawned")
	end)
	local delayed = task.delay(1, function()
		table.insert(log, "delayed")
	end)
	table.insert(log, "caller")
	return delayed
end

function Order.timedWait(seconds: number): number
	return task.wait(seconds)
end

return Order
```

Running `Order.demo(log)` logs `spawned`, `caller`, `deferred`, and one second later `delayed`.

- Use `task.spawn` to start work that must begin now (for example `task.spawn(onPlayerAdded, player)` for players who joined before the script ran).
- Use `task.defer` to run after the current code finishes, for example to batch several changes into one update.
- `task.delay` and `task.wait` never resume early; the returned or measured time is at least what you asked for and may be a frame longer.
- Cancel scheduled work with `task.cancel(thread)` when the thing it was for is gone (the round ended, the player left).

# Test
```lua
local log = {}
local delayed = item.demo(log)
check("spawn runs before the caller continues", log[1] == "spawned" and log[2] == "caller")
__advance(0)
check("defer runs after the caller", log[3] == "deferred" and #log == 3)
__advance(1)
check("delay runs after its time", log[4] == "delayed")
local log2 = {}
local d2 = item.demo(log2)
task.cancel(d2)
__advance(2)
check("cancelled delay never runs", #log2 == 3 and delayed ~= nil)
local measured
task.spawn(function()
	measured = item.timedWait(0.5)
end)
__advance(0.6)
check("task.wait returns elapsed time", measured ~= nil and measured >= 0.5)
```
