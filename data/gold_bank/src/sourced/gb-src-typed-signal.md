---
id: gb-src-typed-signal
category: luau-typing
topics: Signal, generic type packs, linked list, Connect, Once, Wait, Disconnect, events
source: adapted
source_id: rbxutil
source_path: modules/signal/init.luau
source_commit: 31f9120fca021e3dec275b42bc7047d626962082
---
# Request
I want a pure-Luau Signal for events between my modules (BindableEvent copies tables and is clunky). It should be typed so `signal:Fire(player, 10)` and the handler arguments are checked, and support Connect, Once, Wait and disconnecting while firing. Can you write one?

# Answer
Use a generic type pack `T...` for the arguments, keep handlers in a linked list so disconnecting during `Fire` is safe, and run each handler with `task.spawn` so one yielding or erroring handler does not block the rest.

```lua
--!strict
export type Connection = {
	Connected: boolean,
	Disconnect: (self: Connection) -> (),
}

export type Signal<T...> = {
	Connect: (self: Signal<T...>, fn: (T...) -> ()) -> Connection,
	Once: (self: Signal<T...>, fn: (T...) -> ()) -> Connection,
	Wait: (self: Signal<T...>) -> T...,
	Fire: (self: Signal<T...>, T...) -> (),
	DisconnectAll: (self: Signal<T...>) -> (),
}

type Node = { fn: (...any) -> (), connected: boolean, next: Node? }

local Signal = {}

function Signal.new<T...>(): Signal<T...>
	local head: Node? = nil

	local function connect(fn: (...any) -> ()): Connection
		local node: Node = { fn = fn, connected = true, next = head }
		head = node
		local connection = { Connected = true }
		function connection.Disconnect(self: Connection)
			if not node.connected then
				return
			end
			node.connected = false
			self.Connected = false
			if head == node then
				head = node.next
				return
			end
			local prev = head
			while prev and prev.next ~= node do
				prev = prev.next
			end
			if prev then
				prev.next = node.next
			end
		end
		return connection
	end

	local self = {}

	function self.Connect(_: Signal<T...>, fn: (T...) -> ()): Connection
		return connect(fn :: any)
	end

	function self.Once(_: Signal<T...>, fn: (T...) -> ()): Connection
		local handler: (...any) -> () = fn :: any
		local connection: Connection
		connection = connect(function(...)
			connection:Disconnect()
			handler(...)
		end)
		return connection
	end

	function self.Wait(signal: Signal<T...>): T...
		local thread = coroutine.running()
		signal:Once(function(...)
			task.spawn(thread, ...)
		end)
		return coroutine.yield()
	end

	function self.Fire(_: Signal<T...>, ...: T...)
		local node = head
		while node do
			if node.connected then
				task.spawn(node.fn, ...)
			end
			node = node.next
		end
	end

	function self.DisconnectAll(_: Signal<T...>)
		local node = head
		while node do
			node.connected = false
			node = node.next
		end
		head = nil
	end

	return (self :: any) :: Signal<T...>
end

return Signal
```

Usage: `local scoreChanged: Signal.Signal<Player, number> = Signal.new()`; `scoreChanged:Connect(function(player, score) ... end)`.

- The type pack makes `Fire` and the handler parameters agree, so `scoreChanged:Fire(player, "ten")` is a type error.
- A disconnected node keeps its `next` pointer, so a `Fire` loop that is standing on it can still move on.
- Handlers run in their own threads: a handler that yields or errors does not stop the others.

# Test
```lua
local signal = item.new()
local got = {}
local conn = signal:Connect(function(a, b)
	table.insert(got, a + b)
end)
signal:Once(function(a)
	table.insert(got, a * 100)
end)
signal:Fire(1, 2)
signal:Fire(3, 4)
check("connect receives every fire, once only the first", #got == 3 and table.find(got, 100) ~= nil and table.find(got, 7) ~= nil)
conn:Disconnect()
signal:Fire(5, 5)
check("disconnected handler not called", #got == 3 and conn.Connected == false)
local waited
task.spawn(function()
	waited = signal:Wait()
end)
signal:Fire(42)
check("wait returns fired values", waited == 42)
local selfRemoving
selfRemoving = signal:Connect(function()
	selfRemoving:Disconnect()
end)
local after = 0
signal:Connect(function()
	after += 1
end)
signal:Fire(0)
signal:DisconnectAll()
signal:Fire(0)
check("disconnect during fire is safe, DisconnectAll stops all", after == 1)
```
