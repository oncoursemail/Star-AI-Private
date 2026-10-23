---
id: gb-eng-generic-queue
category: luau-typing
topics: generics, queue, luau types, O(1) dequeue, strict mode
source: original
---
# Request
I need a FIFO queue for a spawn system and later for chat messages, so it should work for any element type with full type checking. `table.remove(t, 1)` is also too slow for me once the queue gets long. Can you write a generic typed queue?

# Answer
A generic `Queue<T>` that keeps head and tail indices, so push and pop are O(1) with no shifting. The type parameter flows from `Queue.new()` into every method.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Queue
export type Queue<T> = {
	push: (self: Queue<T>, value: T) -> (),
	pop: (self: Queue<T>) -> T?,
	peek: (self: Queue<T>) -> T?,
	size: (self: Queue<T>) -> number,
	_items: { [number]: T },
	_head: number,
	_tail: number,
}

local Queue = {}

local function push<T>(self: Queue<T>, value: T): ()
	self._tail += 1
	self._items[self._tail] = value
end

local function pop<T>(self: Queue<T>): T?
	if self._head > self._tail then
		return nil
	end
	local value = self._items[self._head]
	self._items[self._head] = nil
	self._head += 1
	if self._head > self._tail then
		-- empty again: reset so the indices never grow without bound
		self._head, self._tail = 1, 0
	end
	return value
end

local function peek<T>(self: Queue<T>): T?
	return self._items[self._head]
end

local function size<T>(self: Queue<T>): number
	return self._tail - self._head + 1
end

function Queue.new<T>(): Queue<T>
	return {
		push = push,
		pop = pop,
		peek = peek,
		size = size,
		_items = {},
		_head = 1,
		_tail = 0,
	}
end

return Queue
```

- Usage: `local spawns: Queue.Queue<Player> = Queue.new()`; then `spawns:push(player)` rejects anything that is not a Player.
- `pop` returns `T?`, so strict mode forces callers to handle the empty case: `local nextPlayer = spawns:pop(); if nextPlayer then ... end`.
- Popped slots are set to nil so the queue does not keep references to removed players alive.

# Test
```lua
local q = item.new()
check("empty pop is nil", q:pop() == nil and q:size() == 0)
q:push("a")
q:push("b")
q:push("c")
check("size after pushes", q:size() == 3)
check("fifo order", q:pop() == "a" and q:peek() == "b")
check("pop rest", q:pop() == "b" and q:pop() == "c" and q:pop() == nil)
q:push("d")
check("indices reset after empty", q._head == 1 and q._tail == 1 and q:pop() == "d")
for i = 1, 10000 do
	q:push(i)
end
local sum = 0
while q:size() > 0 do
	sum += q:pop() :: number
end
check("large queue drains in order", sum == 10000 * 10001 / 2)
```
