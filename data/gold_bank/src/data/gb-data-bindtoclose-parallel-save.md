---
id: gb-data-bindtoclose-parallel-save
category: datastore-safety
topics: DataStore, BindToClose, shutdown, parallel save, PlayerRemoving
source: original
---
# Request
When I shut down servers for an update, some players lose their last few minutes of progress. I save on PlayerRemoving only. What is the right way to save everyone when the server closes?

# Answer
`BindToClose` gives the server up to 30 seconds before it dies. Save every loaded profile in parallel there, and also wait for saves that `PlayerRemoving` already started, so nothing is cut off. Each profile is saved once: it leaves the table the moment its save begins.

```lua
--!strict
-- ModuleScript: ServerScriptService.PlayerData
local Players = game:GetService("Players")
local DataStoreService = game:GetService("DataStoreService")

local store = DataStoreService:GetDataStore("PlayerData")

export type Profile = { coins: number, level: number }

local profiles: { [Player]: Profile } = {}
local savesInFlight = 0

local PlayerData = {}

local function keyFor(userId: number): string
	return "player_" .. userId
end

local function writeProfile(userId: number, profile: Profile)
	savesInFlight += 1
	for attempt = 1, 3 do
		local ok, err = pcall(function()
			store:SetAsync(keyFor(userId), profile, { userId })
		end)
		if ok then
			break
		end
		warn("save failed for", userId, err)
		task.wait(attempt)
	end
	savesInFlight -= 1
end

local function release(player: Player)
	local profile = profiles[player]
	if profile then
		profiles[player] = nil -- taken out first, so BindToClose cannot save it a second time
		writeProfile(player.UserId, profile)
	end
end

local function loadProfile(player: Player)
	local ok, saved = pcall(function()
		return store:GetAsync(keyFor(player.UserId))
	end)
	if not ok then
		player:Kick("Could not load your data. Please rejoin.")
		return
	end
	local profile: Profile = { coins = 0, level = 1 }
	if type(saved) == "table" then
		profile.coins = tonumber(saved.coins) or 0
		profile.level = tonumber(saved.level) or 1
	end
	if player.Parent then
		profiles[player] = profile
	end
end

function PlayerData.get(player: Player): Profile?
	return profiles[player]
end

Players.PlayerAdded:Connect(loadProfile)
Players.PlayerRemoving:Connect(release)
for _, player in Players:GetPlayers() do
	task.spawn(loadProfile, player)
end

game:BindToClose(function()
	for player in profiles do
		task.spawn(release, player)
	end
	local deadline = os.clock() + 25
	while savesInFlight > 0 and os.clock() < deadline do
		task.wait(0.1)
	end
end)

return PlayerData
```

- Saves run in parallel because 30 seconds divided by a full server of sequential saves with retries is not enough.
- `savesInFlight` covers `PlayerRemoving` saves too: at shutdown players are removed while the close handler runs, and those saves must finish before the process exits.
- Never save a profile that failed to load; here a failed load kicks the player and no profile exists to save.

# Test
```lua
warn = function(...) end
```
```lua
local store = game:GetService("DataStoreService"):GetDataStore("PlayerData")
local a = __makePlayer(1, "A")
local b = __makePlayer(2, "B")
check("profiles load with defaults", item.get(a) ~= nil and item.get(a).coins == 0)

item.get(a).coins = 30
item.get(b).level = 4
__removePlayer(b)
check("leaving saves and drops the profile", item.get(b) == nil and store:GetAsync("player_2").level == 4)

game:GetService("DataStoreService").__failNext = 1
__close()
local saved = store:GetAsync("player_1")
check("shutdown saves the remaining player, even after a failed attempt", saved ~= nil and saved.coins == 30)
check("profile released after the shutdown save", item.get(a) == nil)

game:GetService("DataStoreService").__failNext = 1
local c = __makePlayer(3, "C")
check("failed load kicks instead of using defaults", item.get(c) == nil and c.__kicked ~= nil)
```
