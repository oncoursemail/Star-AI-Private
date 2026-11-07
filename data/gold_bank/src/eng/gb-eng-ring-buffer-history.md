---
id: gb-eng-ring-buffer-history
category: engineering-algorithm
topics: ring buffer, circular buffer, position history, lag compensation, fixed memory
source: original
---
# Request
For lag compensation I want to store each player's last 1 second of positions (sampled every frame) and look up where they were at a given past time. Appending to a table and removing from the front feels wasteful. What structure should I use?

# Answer
A fixed-capacity ring buffer: writes overwrite the oldest slot, so memory stays constant and nothing shifts. Store `(time, position)` pairs and answer "where at time t" by walking back from the newest sample and interpolating between the two samples around `t`.

```lua
--!strict
-- ModuleScript: ServerScriptService.PositionHistory
export type History = {
	capacity: number,
	count: number,
	head: number, -- index of the newest sample
	times: { number },
	positions: { Vector3 },
}

local PositionHistory = {}

function PositionHistory.new(capacity: number): History
	assert(capacity >= 2, "need room for at least two samples")
	return { capacity = capacity, count = 0, head = 0, times = {}, positions = {} }
end

function PositionHistory.push(h: History, time: number, position: Vector3): ()
	h.head = h.head % h.capacity + 1
	h.times[h.head] = time
	h.positions[h.head] = position
	h.count = math.min(h.count + 1, h.capacity)
end

-- i = 0 is the newest sample, i = count - 1 the oldest
local function slot(h: History, i: number): number
	return (h.head - 1 - i) % h.capacity + 1
end

function PositionHistory.at(h: History, time: number): Vector3?
	if h.count == 0 then
		return nil
	end
	local newest = slot(h, 0)
	if time >= h.times[newest] then
		return h.positions[newest]
	end
	for i = 1, h.count - 1 do
		local older, newer = slot(h, i), slot(h, i - 1)
		local t0, t1 = h.times[older], h.times[newer]
		if time >= t0 then
			local alpha = if t1 > t0 then (time - t0) / (t1 - t0) else 0
			return h.positions[older]:Lerp(h.positions[newer], alpha)
		end
	end
	return nil -- older than anything we kept
end

return PositionHistory
```

- At 60 samples per second, `PositionHistory.new(60)` holds one second per player; size it from the oldest rewind you allow, and reject hit claims older than that (the `nil` return).
- Parallel `times`/`positions` arrays mean a push allocates nothing new after the buffer fills.
- Record from the server's Heartbeat with `os.clock()` and rewind to `os.clock() - player:GetNetworkPing()`; never take the time to rewind to from the client.

# Test
```lua
local h = item.new(4)
check("empty returns nil", item.at(h, 0) == nil)
for i = 1, 6 do
	item.push(h, i, Vector3.new(i * 10, 0, 0))
end
check("count capped at capacity", h.count == 4)
check("newest sample for future time", item.at(h, 99).X == 60)
check("exact sample", item.at(h, 4).X == 40)
check("interpolates between samples", math.abs(item.at(h, 4.5).X - 45) < 1e-9)
check("overwritten history is gone", item.at(h, 2) == nil)
check("oldest kept sample", item.at(h, 3).X == 30)
```
