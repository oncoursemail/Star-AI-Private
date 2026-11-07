---
id: gb-eng-lru-cache
category: engineering-algorithm
topics: LRU cache, doubly linked list, memoization, bounded memory, eviction
source: original
---
# Request
I cache results of an expensive lookup (player thumbnails / profile summaries fetched by user id) in a plain table, and on a long-running server it grows forever. I want an LRU cache with a max size and O(1) get/set. How do I build one in Luau?

# Answer
Combine a hash map from key to node with a doubly linked list ordered by recency. `get` moves the node to the front, `set` inserts at the front and evicts from the back when over capacity; every operation touches a constant number of nodes.

```lua
--!strict
-- ModuleScript: ServerScriptService.LruCache
type Node<K, V> = { key: K, value: V, prev: Node<K, V>?, next: Node<K, V>? }

export type LruCache<K, V> = {
	capacity: number,
	size: number,
	map: { [K]: Node<K, V> },
	head: Node<K, V>?, -- most recently used
	tail: Node<K, V>?, -- least recently used
}

local LruCache = {}

function LruCache.new<K, V>(capacity: number): LruCache<K, V>
	assert(capacity >= 1, "capacity must be at least 1")
	return { capacity = capacity, size = 0, map = {}, head = nil, tail = nil }
end

local function unlink<K, V>(cache: LruCache<K, V>, node: Node<K, V>)
	if node.prev then
		node.prev.next = node.next
	else
		cache.head = node.next
	end
	if node.next then
		node.next.prev = node.prev
	else
		cache.tail = node.prev
	end
	node.prev, node.next = nil, nil
end

local function pushFront<K, V>(cache: LruCache<K, V>, node: Node<K, V>)
	node.next = cache.head
	if cache.head then
		cache.head.prev = node
	end
	cache.head = node
	if cache.tail == nil then
		cache.tail = node
	end
end

function LruCache.get<K, V>(cache: LruCache<K, V>, key: K): V?
	local node = cache.map[key]
	if node == nil then
		return nil
	end
	unlink(cache, node)
	pushFront(cache, node)
	return node.value
end

function LruCache.set<K, V>(cache: LruCache<K, V>, key: K, value: V): ()
	local node = cache.map[key]
	if node then
		node.value = value
		unlink(cache, node)
		pushFront(cache, node)
		return
	end
	local fresh: Node<K, V> = { key = key, value = value, prev = nil, next = nil }
	cache.map[key] = fresh
	pushFront(cache, fresh)
	cache.size += 1
	if cache.size > cache.capacity then
		local oldest = cache.tail
		if oldest then
			unlink(cache, oldest)
			cache.map[oldest.key] = nil
			cache.size -= 1
		end
	end
end

return LruCache
```

- Usage: `local summaries: LruCache.LruCache<number, Summary> = LruCache.new(500)`; on a miss, fetch, then `LruCache.set(summaries, userId, result)`.
- A cache hit refreshes recency, so popular entries stay while one-off lookups age out at the tail.
- Cache only successful fetches; storing an error result would serve the failure until it is evicted. Add a timestamp to the value if entries should also expire by age.

# Test
```lua
local c = item.new(2)
item.set(c, "a", 1)
item.set(c, "b", 2)
check("basic get", item.get(c, "a") == 1)
item.set(c, "c", 3)
check("least recently used evicted", item.get(c, "b") == nil)
check("recent entries kept", item.get(c, "a") == 1 and item.get(c, "c") == 3)
item.set(c, "a", 10)
check("update existing keeps size", c.size == 2 and item.get(c, "a") == 10)
item.set(c, "d", 4)
check("update counted as use", item.get(c, "c") == nil and item.get(c, "a") == 10)
local one = item.new(1)
item.set(one, 1, "x")
item.set(one, 2, "y")
check("capacity one", item.get(one, 1) == nil and item.get(one, 2) == "y" and one.head == one.tail)
```
