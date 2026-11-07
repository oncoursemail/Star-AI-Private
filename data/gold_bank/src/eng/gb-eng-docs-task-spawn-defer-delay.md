---
id: gb-eng-docs-task-spawn-defer-delay
category: docs-question
topics: task.spawn, task.defer, task.delay, scheduler, execution order
source: original
---
# Request
What's the actual difference between `task.spawn`, `task.defer` and `task.delay`? When would I pick each one, and in what order do they run if I call them back to back?

# Answer
- `task.spawn(f)` runs `f` immediately, before the next line of the caller, until `f` yields; then the caller continues.
- `task.defer(f)` queues `f` to run after the current thread (and the rest of the current resumption cycle) finishes, still in the same frame. Use it to let the caller finish its setup first, or to avoid re-entering an event handler while it is still running.
- `task.delay(t, f)` runs `f` after at least `t` seconds, on a later frame. It returns the thread, so `task.cancel` can stop it before it runs.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.SchedulerDemo
local SchedulerDemo = {}

function SchedulerDemo.order(log: { string }): thread
	table.insert(log, "caller start")
	task.spawn(function()
		table.insert(log, "spawn body")
	end)
	task.defer(function()
		table.insert(log, "defer body")
	end)
	local delayed = task.delay(0.5, function()
		table.insert(log, "delay body")
	end)
	table.insert(log, "caller end")
	return delayed
end

-- Typical use of defer: fire "ready" only after the constructor has returned the object to its caller.
function SchedulerDemo.newLoader(onReady: (loader: { ready: boolean }) -> ()): { ready: boolean }
	local loader = { ready = false }
	task.defer(function()
		loader.ready = true
		onReady(loader)
	end)
	return loader
end

return SchedulerDemo
```

- Running `order` logs: caller start, spawn body, caller end, defer body, and then delay body half a second later.
- An error inside a spawned, deferred or delayed function is reported in the output but does not stop the caller, because each runs in its own thread.
- `task.wait(t)` is `task.delay` for the current thread: it yields and resumes after at least `t` seconds; do not use the deprecated globals `spawn`, `delay` and `wait`, which throttle and run late.

# Test
```lua
local log = {}
local delayed = item.order(log)
check("spawn runs before the caller continues", log[1] == "caller start" and log[2] == "spawn body" and log[3] == "caller end")
check("defer has not run yet inside the caller", #log == 3)
__advance(0)
check("defer runs after the caller finishes", log[4] == "defer body" and #log == 4)
__advance(0.6)
check("delay runs after its time", log[5] == "delay body")
local log2 = {}
local d2 = item.order(log2)
task.cancel(d2)
__advance(1)
check("cancelled delay never runs", #log2 == 4)
local readyCalls = 0
local loader = item.newLoader(function(l)
	readyCalls += 1
	check("ready callback sees the finished object", l.ready)
end)
check("constructor returns before ready fires", loader.ready == false and readyCalls == 0)
__advance(0)
check("ready fired once", readyCalls == 1 and delayed ~= nil)
```
