---
id: gb-eng-typed-signal-generic
category: luau-typing
topics: generic type packs, signal, typed events, strict mode, connections
source: original
---
# Request
I made my own Signal class for module-to-module events but `Connect` callbacks always get `...any`. Can a custom signal be typed so that `signal:Fire(player, 5)` and the handler's parameters are checked, like `Signal<Player, number>`?

# Answer
Use a generic type pack: `Signal<T...>` threads the argument types through `Fire`, `Connect` and the handler. The implementation stores handlers in a list and snapshots it while firing so handlers may disconnect themselves safely.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.TypedSignal
export type Connection = {
	Connected: boolean,
	Disconnect: (self: Connection) -> (),
}

export type Signal<T...> = {
	Connect: (self: Signal<T...>, handler: (T...) -> ()) -> Connection,
	Fire: (self: Signal<T...>, T...) -> (),
	DisconnectAll: (self: Signal<T...>) -> (),
}

local TypedSignal = {}

function TypedSignal.new<T...>(): Signal<T...>
	type Entry = { fn: (T...) -> (), connection: Connection }
	-- copy-on-write: Connect/Disconnect build a new list, so a Fire loop keeps iterating its own snapshot
	local handlers: { Entry } = {}

	local signal = {} :: Signal<T...>

	function signal.Connect(_self: Signal<T...>, handler: (T...) -> ()): Connection
		local connection: Connection
		local entry: Entry
		connection = {
			Connected = true,
			Disconnect = function(self: Connection)
				if not self.Connected then
					return
				end
				self.Connected = false
				local remaining: { Entry } = {}
				for _, e in handlers do
					if e ~= entry then
						table.insert(remaining, e)
					end
				end
				handlers = remaining
			end,
		}
		entry = { fn = handler, connection = connection }
		local grown: { Entry } = {}
		for i, e in handlers do
			grown[i] = e
		end
		grown[#handlers + 1] = entry
		handlers = grown
		return connection
	end

	function signal.Fire(_self: Signal<T...>, ...: T...)
		for _, e in handlers do
			if e.connection.Connected then
				task.spawn(e.fn, ...)
			end
		end
	end

	function signal.DisconnectAll(_self: Signal<T...>)
		for _, e in handlers do
			e.connection.Connected = false
		end
		handlers = {}
	end

	return signal
end

return TypedSignal
```

- Declare the payload once: `local coinsChanged: TypedSignal.Signal<Player, number> = TypedSignal.new()`; then `coinsChanged:Fire(player, "5")` is an error and the handler's parameters are inferred as `(Player, number)`.
- `task.spawn` per handler means one erroring or yielding handler does not stop the others.
- Connect and Disconnect replace the handler list instead of editing it, so a handler that disconnects itself (or another handler) mid-fire cannot make the loop skip an entry. Firing, the common operation, never copies the list.

# Test
```lua
local s = item.new()
local got = {}
local c1 = s:Connect(function(name, amount)
	table.insert(got, name .. ":" .. amount)
end)
s:Fire("a", 1)
check("handler receives arguments", got[1] == "a:1")
local selfDisconnecting
selfDisconnecting = s:Connect(function()
	selfDisconnecting:Disconnect()
	table.insert(got, "once")
end)
s:Fire("b", 2)
s:Fire("c", 3)
local onceCount = 0
for _, v in got do
	if v == "once" then
		onceCount += 1
	end
end
check("self-disconnect runs once", onceCount == 1)
check("other handler kept firing", got[#got] == "c:3")
c1:Disconnect()
c1:Disconnect()
s:Fire("d", 4)
check("disconnected handler silent and double disconnect safe", got[#got] == "c:3" and not c1.Connected)
local count = 0
s:Connect(function() count += 1 end)
s:DisconnectAll()
s:Fire("e", 5)
check("DisconnectAll stops everything", count == 0)
```
