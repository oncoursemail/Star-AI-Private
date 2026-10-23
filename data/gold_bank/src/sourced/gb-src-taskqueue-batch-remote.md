---
id: gb-src-taskqueue-batch-remote
category: performance
topics: task.defer, batching, RemoteEvent, FireAllClients, network performance, generics
source: adapted
source_id: rbxutil
source_path: modules/task-queue/init.luau
source_commit: 31f9120fca021e3dec275b42bc7047d626962082
---
# Request
My minigun fires about 20 bullets per second per player and I call `bulletEvent:FireAllClients(bullet)` for every bullet. With 10 players the network graph is awful. How can I group everything fired in the same frame into one remote call?

# Answer
Queue items and schedule one flush with `task.defer`: everything added during the current resumption cycle lands in the same batch, and the flush sends it as a single `FireAllClients` call.

```lua
--!strict
export type TaskQueue<T> = {
	add: (item: T) -> (),
	clear: () -> (),
}

local TaskQueue = {}

function TaskQueue.new<T>(onFlush: ({ T }) -> ()): TaskQueue<T>
	local queue: { T } = {}
	local scheduled: thread? = nil
	local flushing = false

	local function flush()
		flushing = true
		local batch = queue
		queue = {}
		scheduled = nil
		onFlush(batch)
		flushing = false
	end

	local function add(item: T)
		table.insert(queue, item)
		if scheduled == nil then
			scheduled = task.defer(flush)
		end
	end

	local function clear()
		if flushing then
			return
		end
		if scheduled then
			task.cancel(scheduled)
			scheduled = nil
		end
		table.clear(queue)
	end

	return { add = add, clear = clear }
end

return TaskQueue
```

Server usage:

```lua
--!strict
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local TaskQueue = require(ReplicatedStorage:WaitForChild("TaskQueue"))
local bulletEvent = ReplicatedStorage:WaitForChild("BulletBatch") :: RemoteEvent

type Bullet = { origin: Vector3, direction: Vector3, shooterId: number }

local bulletQueue = TaskQueue.new(function(bullets: { Bullet })
	bulletEvent:FireAllClients(bullets)
end)

return function(bullet: Bullet)
	bulletQueue.add(bullet)
end
```

- Bullets added in the same resumption cycle share one remote call, so the per-call overhead is paid per batch instead of per bullet.
- The batch table is swapped out before `onFlush` runs, so items added during the flush go into the next batch instead of being lost.
- Send compact data (origin, direction, shooter id) and let clients draw the tracers.

# Test
```lua
local batches = {}
local q = item.new(function(batch)
	table.insert(batches, batch)
end)
q.add(1)
q.add(2)
q.add(3)
check("nothing sent before the deferred flush", #batches == 0)
__advance(0)
check("one batch with all items", #batches == 1 and #batches[1] == 3)
q.add(4)
q.clear()
__advance(0)
check("clear cancels the pending flush", #batches == 1)
q.add(5)
__advance(0)
check("works again after clear", #batches == 2 and batches[2][1] == 5)
```
