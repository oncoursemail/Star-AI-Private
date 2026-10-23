---
id: gb-data-autosave-dirty-flag
category: datastore-safety
topics: DataStore, autosave, dirty flag, write budget, throttling
source: original
---
# Request
I autosave every player every 60 seconds, but most of them have not changed anything and I get "request was added to queue" warnings in big servers. How do I only save players whose data actually changed?

# Answer
Keep a dirty flag per player that every change sets, and let the autosave loop write only dirty profiles, spaced out a little. Clear the flag before the write and set it again if the write fails, so a change made during the save is not lost.

```lua
--!strict
-- ModuleScript: ServerScriptService.AutoSave
local Players = game:GetService("Players")
local DataStoreService = game:GetService("DataStoreService")

local store = DataStoreService:GetDataStore("PlayerData")
local INTERVAL = 60
local SPACING = 0.5

type Entry = { data: { [string]: any }, dirty: boolean }
local entries: { [Player]: Entry } = {}

local AutoSave = {}

local function keyFor(userId: number): string
	return "player_" .. userId
end

local function flush(player: Player, entry: Entry): boolean
	if not entry.dirty then
		return true
	end
	entry.dirty = false
	local ok, err = pcall(function()
		store:SetAsync(keyFor(player.UserId), entry.data, { player.UserId })
	end)
	if not ok then
		entry.dirty = true
		warn("autosave failed for", player.UserId, err)
	end
	return ok
end

function AutoSave.track(player: Player, data: { [string]: any })
	entries[player] = { data = data, dirty = false }
end

function AutoSave.set(player: Player, field: string, value: any)
	local entry = entries[player]
	if entry and entry.data[field] ~= value then
		entry.data[field] = value
		entry.dirty = true
	end
end

-- For changes made inside nested tables (inventory lists, quest progress), which set() cannot see.
function AutoSave.markDirty(player: Player)
	local entry = entries[player]
	if entry then
		entry.dirty = true
	end
end

Players.PlayerRemoving:Connect(function(player: Player)
	local entry = entries[player]
	if entry then
		entries[player] = nil
		flush(player, entry)
	end
end)

task.spawn(function()
	while true do
		task.wait(INTERVAL)
		-- snapshot first: players can join or leave while this loop yields between writes
		local due: { Player } = {}
		for player, entry in entries do
			if entry.dirty then
				table.insert(due, player)
			end
		end
		for _, player in due do
			local entry = entries[player]
			if entry then
				flush(player, entry)
				task.wait(SPACING)
			end
		end
	end
end)

return AutoSave
```

- Unchanged players cost zero requests, so the write budget goes to the players who earned something.
- The spacing spreads a full server's writes over several seconds instead of bursting them into the queue.
- Pair it with a `BindToClose` handler that flushes every remaining entry on shutdown.

# Test
```lua
warn = function(...) end
```
```lua
local ds = game:GetService("DataStoreService")
local store = ds:GetDataStore("PlayerData")
local p = __makePlayer(5, "Saver")
item.track(p, { coins = 0 })

local before = ds.__calls
__advance(61)
check("clean profile is not written", ds.__calls == before)

item.set(p, "coins", 10)
__advance(61)
check("dirty profile is written once", ds.__calls == before + 1 and store:GetAsync("player_5").coins == 10)

local afterWrite = ds.__calls
item.set(p, "coins", 10)
__advance(61)
check("setting the same value does not mark dirty", ds.__calls == afterWrite)

item.set(p, "coins", 20)
ds.__failNext = 1
__advance(61)
check("failed write leaves old data", store:GetAsync("player_5").coins == 10)
__advance(61)
check("retried on the next cycle", store:GetAsync("player_5").coins == 20)

item.set(p, "coins", 25)
__removePlayer(p)
check("leaving flushes immediately", store:GetAsync("player_5").coins == 25)
```
