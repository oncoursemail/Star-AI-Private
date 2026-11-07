---
id: gb-eng-priority-queue-scheduler
category: engineering-algorithm
topics: binary heap, priority queue, timer scheduler, generics, O(log n)
source: original
---
# Request
I have hundreds of timed events (crop growth, buff expiry, respawns) and I currently loop over all of them every second to see which are due. I want a priority queue keyed by due time so I only touch the ones that are actually due. Can you write a generic binary heap and show it used as a scheduler?

# Answer
A generic min-heap stored in an array with parallel priorities: `push` sifts up, `pop` moves the last element to the root and sifts down, both O(log n). The scheduler then pops only while the earliest event is due.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.MinHeap
export type MinHeap<T> = { items: { T }, priorities: { number } }

local MinHeap = {}

function MinHeap.new<T>(): MinHeap<T>
	return { items = {}, priorities = {} }
end

local function swap<T>(heap: MinHeap<T>, i: number, j: number)
	heap.items[i], heap.items[j] = heap.items[j], heap.items[i]
	heap.priorities[i], heap.priorities[j] = heap.priorities[j], heap.priorities[i]
end

function MinHeap.push<T>(heap: MinHeap<T>, item: T, priority: number): ()
	local i = #heap.items + 1
	heap.items[i] = item
	heap.priorities[i] = priority
	while i > 1 do
		local parent = i // 2
		if heap.priorities[parent] <= heap.priorities[i] then
			break
		end
		swap(heap, i, parent)
		i = parent
	end
end

function MinHeap.peek<T>(heap: MinHeap<T>): (T?, number?)
	return heap.items[1], heap.priorities[1]
end

function MinHeap.pop<T>(heap: MinHeap<T>): (T?, number?)
	local n = #heap.items
	if n == 0 then
		return nil, nil
	end
	local top, topPriority = heap.items[1], heap.priorities[1]
	swap(heap, 1, n)
	heap.items[n] = nil
	heap.priorities[n] = nil
	n -= 1
	local i = 1
	while i * 2 <= n do
		local child = i * 2
		if child + 1 <= n and heap.priorities[child + 1] < heap.priorities[child] then
			child += 1
		end
		if heap.priorities[i] <= heap.priorities[child] then
			break
		end
		swap(heap, i, child)
		i = child
	end
	return top, topPriority
end

function MinHeap.size<T>(heap: MinHeap<T>): number
	return #heap.items
end

-- Runs every callback whose due time is <= now, earliest first. Returns how many ran.
function MinHeap.runDue(heap: MinHeap<() -> ()>, now: number): number
	local ran = 0
	local _, due = MinHeap.peek(heap)
	while due ~= nil and due <= now do
		local callback = MinHeap.pop(heap)
		if callback then
			task.spawn(callback)
			ran += 1
		end
		_, due = MinHeap.peek(heap)
	end
	return ran
end

return MinHeap
```

- Scheduler loop: `MinHeap.push(timers, function() growCrop(plot) end, os.clock() + 30)` and once per Heartbeat `MinHeap.runDue(timers, os.clock())`; a frame with nothing due costs one peek.
- Items and priorities live in parallel arrays, so the heap allocates no wrapper table per entry.
- Equal priorities come out in an unspecified order; add a sequence number as a tie-break if order matters.

# Test
```lua
local heap = item.new()
check("empty pop", item.pop(heap) == nil)
for _, p in { 5, 3, 8, 1, 9, 2, 7 } do
	item.push(heap, "p" .. p, p)
end
local out = {}
while item.size(heap) > 0 do
	local _, pr = item.pop(heap)
	table.insert(out, pr)
end
check("pops in ascending order", table.concat(out, ",") == "1,2,3,5,7,8,9")
local timers = item.new()
local log = {}
item.push(timers, function() table.insert(log, "b") end, 20)
item.push(timers, function() table.insert(log, "a") end, 10)
item.push(timers, function() table.insert(log, "c") end, 30)
check("nothing due yet", item.runDue(timers, 5) == 0)
check("runs only due events in order", item.runDue(timers, 20) == 2 and log[1] == "a" and log[2] == "b")
check("remaining event kept", item.size(timers) == 1 and select(2, item.peek(timers)) == 30)
```
