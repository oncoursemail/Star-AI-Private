---
id: gb-eng-debug-playeradded-missed
category: engineering-debugging
topics: PlayerAdded, race condition, GetPlayers, leaderstats, Studio play solo
source: original
---
# Request
My leaderstats work in a live server but in Studio Play Solo I often have no leaderstats at all. No errors in the output. Why?

```lua
local Config = require(game:GetService("ServerStorage"):WaitForChild("Config"))

game.Players.PlayerAdded:Connect(function(plr)
	local ls = Instance.new("Folder")
	ls.Name = "leaderstats"
	ls.Parent = plr
	local coins = Instance.new("IntValue")
	coins.Name = "Coins"
	coins.Value = Config.StartingCoins
	coins.Parent = ls
end)
```

# Answer
`PlayerAdded` only fires for players who join after you connect. In Play Solo your player is added almost immediately, often before this script reaches the `Connect` line (and any yield before it, such as a `WaitForChild` that has to wait or a module that yields while loading, widens the gap), so the event has already fired by the time it connects. Run the setup for players already in the game as well, and guard against setting someone up twice.

```lua
--!strict
-- Script: ServerScriptService.Leaderstats
local Players = game:GetService("Players")
local ServerStorage = game:GetService("ServerStorage")
local Config = require(ServerStorage:WaitForChild("Config"))

local function setupPlayer(player: Player)
	if player:FindFirstChild("leaderstats") then
		return -- already set up (joined during the loop below and fired PlayerAdded too)
	end
	local stats = Instance.new("Folder")
	stats.Name = "leaderstats"
	local coins = Instance.new("IntValue")
	coins.Name = "Coins"
	coins.Value = Config.StartingCoins
	coins.Parent = stats
	stats.Parent = player
end

Players.PlayerAdded:Connect(setupPlayer)
for _, player in Players:GetPlayers() do
	task.spawn(setupPlayer, player)
end
```

- Connect first, then loop over `GetPlayers()`: in that order no player can slip through the gap between the two.
- `task.spawn` per existing player keeps one slow setup (for example a data load) from delaying the others.
- Building the folder fully before parenting it to the player means clients and other scripts never see a half-built `leaderstats`.
- The same pattern applies to `CharacterAdded` (check `player.Character`) and to `CollectionService` tags (handle `GetTagged` as well as the added signal).

# Test
```lua
local cfg = Instance.new("ModuleScript")
cfg.Name = "Config"
cfg.Parent = game:GetService("ServerStorage")
local realRequire = require
require = function(m)
	if m == cfg then
		return { StartingCoins = 25 }
	end
	return realRequire(m)
end
early = __makePlayer(1, "Early")
```
```lua
check("player present before script got leaderstats", __leaderstat(early, "Coins") == 25)
local late = __makePlayer(2, "Late")
check("later player set up", __leaderstat(late, "Coins") == 25)
game:GetService("Players").PlayerAdded:Fire(late)
local folders = 0
for _, c in late:GetChildren() do
	if c.Name == "leaderstats" then
		folders += 1
	end
end
check("no duplicate leaderstats", folders == 1)
```
