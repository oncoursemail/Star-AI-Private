---
id: gb-data-load-failure-guest-mode
category: datastore-safety
topics: DataStore, load failure, data loss, guest mode, retry
source: original
---
# Request
A player reported that all their progress was reset to zero. Looking at my code, I think when GetAsync fails they get default data and then that gets saved. Can you show me how to handle a failed load properly?

```lua
local ok, data = pcall(function()
	return store:GetAsync(player.UserId)
end)
sessions[player] = data or { coins = 0, level = 1 }
```

# Answer
Your code cannot tell "new player" (`ok` and `data == nil`) apart from "the load failed" (`ok == false`), so a failed load becomes defaults that overwrite the real save on leave. Retry the load, and if it still fails, mark the session as not saveable: the player can keep playing on temporary data, but nothing is ever written for them.

```lua
--!strict
-- ModuleScript: ServerScriptService.Sessions
local DataStoreService = game:GetService("DataStoreService")

local store = DataStoreService:GetDataStore("PlayerData")

export type Session = { data: { coins: number, level: number }, canSave: boolean }

local sessions: { [Player]: Session } = {}
local Sessions = {}

local function keyFor(userId: number): string
	return "player_" .. userId
end

local function loadWithRetry(userId: number): (boolean, any)
	for attempt = 1, 3 do
		local ok, saved = pcall(function()
			return store:GetAsync(keyFor(userId))
		end)
		if ok then
			return true, saved
		end
		task.wait(attempt)
	end
	return false, nil
end

function Sessions.start(player: Player): Session
	local ok, saved = loadWithRetry(player.UserId)
	local session: Session = { data = { coins = 0, level = 1 }, canSave = ok }
	if ok and type(saved) == "table" then
		session.data.coins = tonumber(saved.coins) or 0
		session.data.level = tonumber(saved.level) or 1
	end
	if player.Parent ~= nil then -- a player who left during the load would leave a stale entry behind
		sessions[player] = session
	end
	return session
end

function Sessions.get(player: Player): Session?
	return sessions[player]
end

function Sessions.save(player: Player): boolean
	local session = sessions[player]
	if session == nil or not session.canSave then
		return false -- never overwrite a save we could not read
	end
	local ok = pcall(function()
		store:SetAsync(keyFor(player.UserId), session.data, { player.UserId })
	end)
	return ok
end

function Sessions.stop(player: Player)
	Sessions.save(player)
	sessions[player] = nil
end

return Sessions
```

- When `canSave` is false, tell the client ("Your data could not load; progress this session will not be saved") so the player can rejoin instead of grinding for nothing.
- `ok == true` with `saved == nil` is the only case that means a new player; that path is safe to save.
- If you prefer, kick instead of guest mode; both are fine, the bug is only ever saving defaults over a read you could not do.

# Test
```lua
local ds = game:GetService("DataStoreService")
local store = ds:GetDataStore("PlayerData")
store:SetAsync("player_1", { coins = 5000, level = 30 })

local p = __makePlayer(1, "Veteran")
ds.__failNext = 3
local session = nil
task.spawn(function()
	session = item.start(p)
end)
__advance(10)
check("failed load is not saveable", session ~= nil and session.canSave == false)
session.data.coins = 0
check("saving a failed session is refused", item.save(p) == false)
check("the real save is untouched", store:GetAsync("player_1").coins == 5000)

local q = __makePlayer(2, "Newbie")
local fresh = nil
task.spawn(function()
	fresh = item.start(q)
end)
__advance(0)
check("a brand new player is saveable", fresh ~= nil and fresh.canSave and fresh.data.coins == 0)

local r = __makePlayer(1, "VeteranAgain")
ds.__failNext = 1
local retried = nil
task.spawn(function()
	retried = item.start(r)
end)
__advance(10)
check("one failure is retried and real data loads", retried ~= nil and retried.canSave and retried.data.coins == 5000)

local quitter = __makePlayer(3, "Quitter")
ds.__failNext = 1
task.spawn(function()
	item.start(quitter)
end)
__removePlayer(quitter)
__advance(10)
check("a player who leaves during the load leaves no session behind", item.get(quitter) == nil)
```
