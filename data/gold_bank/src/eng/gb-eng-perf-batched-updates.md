---
id: gb-eng-perf-batched-updates
category: performance
topics: batching, network traffic, dirty set, RemoteEvent, Heartbeat flush
source: original
---
# Request
Our tycoon fires a RemoteEvent to the client every time any dropper produces ore value, sometimes 200 times a second per player, and the client UI rebuilds on each one. How do I batch these so we send at most one update per player per interval?

# Answer
Mark changes in a per-player "dirty" table as they happen (cheap, no network), and flush on a fixed interval: one remote call per player carrying only the keys that changed, with the latest value for each. Many changes to the same key collapse into one entry.

```lua
--!strict
-- ModuleScript: ServerScriptService.UpdateBatcher
export type Batcher = {
	set: (self: Batcher, player: Player, key: string, value: number) -> (),
	flush: (self: Batcher) -> number,
	forget: (self: Batcher, player: Player) -> (),
}

local UpdateBatcher = {}

function UpdateBatcher.new(remote: RemoteEvent): Batcher
	local dirty: { [Player]: { [string]: number } } = {}
	local batcher = {} :: Batcher

	function batcher.set(_self: Batcher, player: Player, key: string, value: number)
		local changes = dirty[player]
		if changes == nil then
			changes = {}
			dirty[player] = changes
		end
		changes[key] = value -- later values overwrite earlier ones; only the latest is sent
	end

	function batcher.flush(_self: Batcher): number
		local sent = 0
		local pending = dirty
		dirty = {}
		for player, changes in pending do
			if player.Parent ~= nil then
				remote:FireClient(player, changes)
				sent += 1
			end
		end
		return sent
	end

	function batcher.forget(_self: Batcher, player: Player)
		dirty[player] = nil
	end

	return batcher
end

function UpdateBatcher.autoFlush(batcher: Batcher, heartbeat: RBXScriptSignal, interval: number): RBXScriptConnection
	local elapsed = 0
	return heartbeat:Connect(function(dt: number)
		elapsed += dt
		if elapsed >= interval then
			elapsed = 0
			batcher:flush()
		end
	end)
end

return UpdateBatcher
```

- Server wiring: `local batcher = UpdateBatcher.new(statsRemote)`, `UpdateBatcher.autoFlush(batcher, RunService.Heartbeat, 0.2)`, `Players.PlayerRemoving:Connect(function(p) batcher:forget(p) end)`, and droppers call `batcher:set(player, "Ore", newTotal)`.
- Sending absolute values (the new total) rather than deltas means a dropped or merged update can never desynchronise the client.
- Five updates per second is plenty for UI; the client can tween the displayed number toward the latest value to hide the step.

# Test
```lua
local remote = Instance.new("RemoteEvent")
local b = item.new(remote)
local p1 = __makePlayer(1, "A")
local p2 = __makePlayer(2, "B")
for i = 1, 200 do
	b:set(p1, "Ore", i)
end
b:set(p1, "Cash", 50)
b:set(p2, "Ore", 7)
check("one message per player", b:flush() == 2 and #remote.__sent == 2)
local forP1
for _, entry in remote.__sent do
	if entry[1] == p1 then
		forP1 = entry[2]
	end
end
check("latest value per key", forP1.Ore == 200 and forP1.Cash == 50)
check("nothing to send after flush", b:flush() == 0)
local conn = item.autoFlush(b, game:GetService("RunService").Heartbeat, 0.2)
b:set(p2, "Ore", 8)
__frames(6, 1 / 60)
check("autoflush waits for interval", #remote.__sent == 2)
__frames(10, 1 / 60)
check("autoflush sends", #remote.__sent == 3)
b:set(p2, "Ore", 9)
b:forget(p2)
__frames(20, 1 / 60)
check("forgotten player not sent", #remote.__sent == 3)
conn:Disconnect()
```
