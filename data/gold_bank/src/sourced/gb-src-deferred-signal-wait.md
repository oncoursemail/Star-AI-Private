---
id: gb-src-deferred-signal-wait
category: engineering-debugging
topics: deferred events, SignalBehavior, Once, timeout, coroutine, event ordering
source: adapted
source_id: creator-docs
source_path: content/en-us/scripting/events/deferred.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
This used to work and broke after Workspace.SignalBehavior became Deferred:

```lua
local done = false
door.Opened:Connect(function() done = true end)
openDoor()
print(done) -- now prints false
```

Why, and what's the correct way to wait for an event that I just caused, without hanging forever if it never fires?

# Answer
With deferred events, handlers no longer run inside the call that fired the event; they run later in the same frame, at the next resumption point. Code that checks a flag right after firing reads it too early. Wait for the event explicitly with a one-shot connection and a timeout.

```lua
--!strict
local SignalUtil = {}

function SignalUtil.waitFor(signal: RBXScriptSignal, timeout: number): (boolean, ...any)
	local thread = coroutine.running()
	local finished = false
	local connection: RBXScriptConnection
	local timer: thread

	connection = signal:Once(function(...)
		if finished then
			return
		end
		finished = true
		task.cancel(timer)
		task.spawn(thread, true, ...)
	end)
	timer = task.delay(timeout, function()
		if finished then
			return
		end
		finished = true
		connection:Disconnect()
		task.spawn(thread, false)
	end)

	return coroutine.yield()
end

return SignalUtil
```

Usage: connect first, then trigger, then wait:

```lua
--!strict
local function openAndConfirm(door: any, openDoor: () -> (), waitFor: (RBXScriptSignal, number) -> boolean): boolean
	task.defer(openDoor)
	return waitFor(door.Opened, 5)
end

return openAndConfirm
```

- `Once` disconnects itself after the first fire, so nothing lingers after the wait.
- The timeout path disconnects the listener and resumes with `false`; the `finished` flag makes sure only one of the two paths resumes the thread.
- Starting the trigger with `task.defer` after the wait is set up avoids missing an event that fires immediately.

# Test
```lua
local event = Instance.new("BindableEvent")
local ok, value
task.spawn(function()
	ok, value = item.waitFor(event.Event, 2)
end)
check("still waiting before the fire", ok == nil)
event:Fire(42)
__advance(0)
check("returns true with the fired values", ok == true and value == 42)
local timedOut
task.spawn(function()
	timedOut = item.waitFor(event.Event, 1)
end)
__advance(1.1)
check("times out with false", timedOut == false)
event:Fire(1)
__advance(0)
check("late fire after timeout is ignored", timedOut == false)
```
