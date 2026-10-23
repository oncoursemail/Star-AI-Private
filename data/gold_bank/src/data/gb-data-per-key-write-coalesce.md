---
id: gb-data-per-key-write-coalesce
category: datastore-safety
topics: DataStore, write throttle, per-key limit, UpdateAsync, guild data
source: original
---
# Request
Our guild bank is one DataStore key per guild. When several members deposit at once I get throttling warnings because the same key is written many times a second. How can I batch the writes so each key is written at most once every 6 seconds without losing deposits?

# Answer
Queue each change as a transform function per key. The first change writes right away; changes arriving inside the 6-second window wait and are applied together, in order, inside one `UpdateAsync`. A failed write puts its batch back at the front of the queue and tries again after the gap.

```lua
--!strict
-- ModuleScript: ServerScriptService.KeyWriteQueue
export type Transform = (current: any) -> any
export type Queue = {
	update: (key: string, transform: Transform) -> (),
	pending: (key: string) -> number,
	flushAll: () -> (),
}

type KeyState = { transforms: { Transform }, lastWrite: number, scheduled: boolean }

local MIN_GAP = 6 -- seconds between writes to the same key

local KeyWriteQueue = {}

function KeyWriteQueue.new(store: DataStore): Queue
	local states: { [string]: KeyState } = {}
	local schedule: (key: string) -> ()

	local function flush(key: string)
		local state = states[key]
		state.scheduled = false
		if #state.transforms == 0 then
			return -- already written by flushAll
		end
		local batch = state.transforms
		state.transforms = {}
		state.lastWrite = os.clock()
		local ok = pcall(function()
			store:UpdateAsync(key, function(current: any): any
				local value = current
				for _, transform in batch do
					value = transform(value)
				end
				return value
			end)
		end)
		if not ok then
			local merged = batch
			for _, transform in state.transforms do
				table.insert(merged, transform)
			end
			state.transforms = merged
		end
		if #state.transforms > 0 then
			schedule(key)
		end
	end

	schedule = function(key: string)
		local state = states[key]
		if state.scheduled then
			return
		end
		state.scheduled = true
		task.delay(math.max(0, state.lastWrite + MIN_GAP - os.clock()), flush, key)
	end

	local function update(key: string, transform: Transform)
		local state = states[key]
		if state == nil then
			state = { transforms = {}, lastWrite = -math.huge, scheduled = false }
			states[key] = state
		end
		table.insert(state.transforms, transform)
		schedule(key)
	end

	local function pending(key: string): number
		local state = states[key]
		return if state then #state.transforms else 0
	end

	-- For BindToClose: write every pending batch now instead of waiting for its gap.
	local function flushAll()
		local keys: { string } = {}
		for key, state in states do
			if #state.transforms > 0 then
				table.insert(keys, key)
			end
		end
		for _, key in keys do
			flush(key)
		end
	end

	return { update = update, pending = pending, flushAll = flushAll }
end

return KeyWriteQueue
```

Usage: `queue.update("guild_" .. guildId, function(bank) bank = bank or { gold = 0 }; bank.gold += amount; return bank end)`.

- Transforms receive the freshest stored value each time, so deposits from other servers are never overwritten.
- Each transform must return the new value; returning `nil` from the whole chain cancels that write.
- Call `game:BindToClose(queue.flushAll)` so deposits still waiting for their gap are written before the server closes.

# Test
```lua
local ds = game:GetService("DataStoreService")
local store = ds:GetDataStore("GuildBank")
local queue = item.new(store)
local function deposit(amount)
	return function(bank)
		bank = bank or { gold = 0 }
		bank.gold += amount
		return bank
	end
end

local before = ds.__calls
for _ = 1, 5 do
	queue.update("guild_1", deposit(10))
end
__advance(0)
check("burst is written in one call", ds.__calls == before + 1 and store:GetAsync("guild_1").gold == 50)

__advance(1)
local mid = ds.__calls
queue.update("guild_1", deposit(1))
queue.update("guild_1", deposit(2))
__advance(4)
check("waits for the per-key gap", ds.__calls == mid and queue.pending("guild_1") == 2)
__advance(1.5)
check("coalesced batch lands after the gap", store:GetAsync("guild_1").gold == 53)

__advance(10)
ds.__failNext = 1
queue.update("guild_1", deposit(100))
__advance(0)
check("failed batch is kept", queue.pending("guild_1") == 1)
__advance(7)
check("retried after the gap without losing the deposit", store:GetAsync("guild_1").gold == 153)

__advance(10)
queue.update("guild_1", deposit(1000))
__advance(0)
queue.update("guild_1", deposit(7))
check("deposits inside the gap wait", queue.pending("guild_1") == 1 and store:GetAsync("guild_1").gold == 1153)
queue.flushAll()
check("flushAll writes pending work immediately for shutdown", queue.pending("guild_1") == 0
	and store:GetAsync("guild_1").gold == 1160)
__advance(7)
check("the already-scheduled flush does not apply the batch twice", store:GetAsync("guild_1").gold == 1160)
```
