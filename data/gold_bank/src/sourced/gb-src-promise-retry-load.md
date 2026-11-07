---
id: gb-src-promise-retry-load
category: datastore-safety
topics: Promise, retryWithDelay, timeout, DataStore load, kick on failure, andThen, catch
source: adapted
source_id: promise
source_path: lib/init.lua
source_commit: 031d429c82ee458a849e79fa523523bd349d7695
---
# Request
I'm using the Promise library in my data module. When a player joins I want to load their data with a few retries, give up after 15 seconds total, and kick them with a friendly message if it fails instead of letting them play with empty data that would overwrite their save. How would that look with Promises?

# Answer
Wrap a protected `GetAsync` in `Promise.new` that rejects on error, retry it with `Promise.retryWithDelay`, bound the whole thing with `:timeout`, and handle success and failure once at the end with `andThen` and `catch`.

```lua
--!strict
local DataStoreService = game:GetService("DataStoreService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Promise = require(ReplicatedStorage:WaitForChild("Packages"):WaitForChild("Promise"))

local RETRIES = 4
local RETRY_DELAY = 2
local TOTAL_TIMEOUT = 15

local store = DataStoreService:GetDataStore("PlayerData")
local loaded: { [Player]: { [string]: any } } = {}

local function getAsync(key: string)
	return Promise.new(function(resolve, reject)
		local ok, result = pcall(store.GetAsync, store, key)
		if ok then
			resolve(result)
		else
			reject(result)
		end
	end)
end

local function onPlayerAdded(player: Player)
	Promise.retryWithDelay(getAsync, RETRIES, RETRY_DELAY, "Player_" .. player.UserId)
		:timeout(TOTAL_TIMEOUT)
		:andThen(function(data: { [string]: any }?)
			if player.Parent ~= Players then
				return
			end
			loaded[player] = data or { coins = 0 }
			player:SetAttribute("DataLoaded", true)
		end)
		:catch(function(err)
			warn("Data load failed for", player.UserId, tostring(err))
			player:Kick("We couldn't load your data. Please rejoin in a minute.")
		end)
end

Players.PlayerAdded:Connect(onPlayerAdded)
for _, player in Players:GetPlayers() do
	onPlayerAdded(player)
end
Players.PlayerRemoving:Connect(function(player: Player)
	loaded[player] = nil
end)

return loaded
```

- A failed `GetAsync` becomes a rejection, which is what `retryWithDelay` retries on.
- The timeout rejects the whole chain if retries take too long, so a player never waits forever on a loading screen.
- Kicking on failure, and never saving for a player whose `DataLoaded` is not set, protects existing saves from being overwritten with defaults.
- A player who leaves mid-load is skipped in `andThen`, so nothing is stored for them.
