---
id: gb-eng-debug-client-coins-not-saving
category: engineering-debugging
topics: replication, LocalScript, leaderstats, RemoteEvent, server authority
source: original
---
# Request
I made a "Claim daily reward" button. Clicking it adds 50 coins and I can see them on my screen, but they don't save and other players still see my old amount. Code in a LocalScript inside the button:

```lua
script.Parent.MouseButton1Click:Connect(function()
	local coins = game.Players.LocalPlayer.leaderstats.Coins
	coins.Value = coins.Value + 50
	script.Parent.Text = "Claimed!"
end)
```

# Answer
Changes a LocalScript makes to replicated objects stay on that client: the server (which saves data and replicates leaderstats to everyone) never sees them. The client should only ask, through a RemoteEvent; the server decides whether the claim is allowed, changes the value, and the change replicates back.

```lua
--!strict
-- Script: ServerScriptService.DailyReward
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local REWARD = 50
local COOLDOWN = 20 * 60 * 60

local claimRemote = Instance.new("RemoteEvent")
claimRemote.Name = "ClaimDailyReward"
claimRemote.Parent = ReplicatedStorage

claimRemote.OnServerEvent:Connect(function(player: Player)
	local stats = player:FindFirstChild("leaderstats")
	local coins = stats and stats:FindFirstChild("Coins")
	if coins == nil or not coins:IsA("IntValue") then
		return
	end
	local now = os.time()
	local last = player:GetAttribute("LastDailyClaim")
	if type(last) == "number" and now - last < COOLDOWN then
		claimRemote:FireClient(player, false, COOLDOWN - (now - last))
		return
	end
	player:SetAttribute("LastDailyClaim", now) -- save this with the player's data so rejoining cannot reset it
	coins.Value += REWARD
	claimRemote:FireClient(player, true, COOLDOWN)
end)
```

```lua
--!strict
-- LocalScript inside the button
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local button = script.Parent :: TextButton
local claimRemote = ReplicatedStorage:WaitForChild("ClaimDailyReward") :: RemoteEvent

button.MouseButton1Click:Connect(function()
	claimRemote:FireServer()
end)

claimRemote.OnClientEvent:Connect(function(ok: boolean, secondsLeft: number)
	button.Text = if ok then "Claimed!" else `Come back in {math.ceil(secondsLeft / 3600)}h`
end)
```

- The client sends no amount at all: the reward size and cooldown live on the server, so an exploiter firing the remote in a loop gets at most one reward per cooldown.
- The button text is updated from the server's answer, so it never shows "Claimed!" for a claim that was refused.
- Store `LastDailyClaim` in the player's saved data (with the coins) in a real game; an attribute alone resets when the player rejoins.

# Test
```lua
local remote = game:GetService("ReplicatedStorage"):WaitForChild("ClaimDailyReward")
local p = __makePlayer(1, "Ana")
local ls = Instance.new("Folder")
ls.Name = "leaderstats"
ls.Parent = p
local coins = Instance.new("IntValue")
coins.Name = "Coins"
coins.Value = 10
coins.Parent = ls
remote.OnServerEvent:Fire(p)
check("server grants reward", coins.Value == 60)
remote.OnServerEvent:Fire(p)
remote.OnServerEvent:Fire(p)
check("spam within cooldown ignored", coins.Value == 60)
check("client told result", remote.__sent[1][2] == true and remote.__sent[2][2] == false)
__advance(20 * 60 * 60 + 1)
remote.OnServerEvent:Fire(p)
check("claim allowed after cooldown", coins.Value == 110)
local q = __makePlayer(2, "NoStats")
remote.OnServerEvent:Fire(q)
check("player without leaderstats ignored", #remote.__sent == 4)
```
