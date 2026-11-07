---
id: gb-data-remote-instance-ownership
category: remote-security
topics: RemoteEvent, Instance argument, ownership, Tool, sell
source: original
---
# Request
I have a "SellTool" RemoteEvent where the client passes the Tool they want to sell. An exploiter sold someone else's sword and even parts of the map. How do I check that the Instance a client sends is really theirs?

# Answer
Treat the Instance as an untrusted pointer: check it is an Instance, of the class you expect, and that it sits directly in that player's Backpack or Character. Then price it from a server table by its name, never from anything on the client or the tool.

```lua
--!strict
-- Script: ServerScriptService.SellTools
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local SELL_PRICES: { [string]: number } = { WoodSword = 10, IronSword = 40, Bow = 25 }

local sellTool = Instance.new("RemoteEvent")
sellTool.Name = "SellTool"
sellTool.Parent = ReplicatedStorage

local function ownedTool(player: Player, value: unknown): Tool?
	local kind = typeof(value)
	if kind ~= "Instance" then
		return nil
	end
	local tool = value :: any
	if not tool:IsA("Tool") then
		return nil
	end
	local backpack = player:FindFirstChildOfClass("Backpack")
	local character = player.Character
	local parent = tool.Parent
	if parent ~= nil and (parent == backpack or parent == character) then
		return tool
	end
	return nil
end

local function onSell(player: Player, value: unknown)
	local tool = ownedTool(player, value)
	if tool == nil then
		return
	end
	local price = SELL_PRICES[tool.Name]
	if price == nil then
		return -- not a sellable item
	end
	local stats: Instance? = player:FindFirstChild("leaderstats")
	local coins: Instance? = if stats then stats:FindFirstChild("Coins") else nil
	if coins == nil or not coins:IsA("IntValue") then
		return
	end
	tool:Destroy()
	local wallet = coins :: IntValue
	wallet.Value += price
end

sellTool.OnServerEvent:Connect(onSell)

Players.PlayerAdded:Connect(function(player: Player)
	local stats = Instance.new("Folder")
	stats.Name = "leaderstats"
	local coins = Instance.new("IntValue")
	coins.Name = "Coins"
	coins.Parent = stats
	stats.Parent = player
end)
for _, player in Players:GetPlayers() do
	if player:FindFirstChild("leaderstats") == nil then
		local stats = Instance.new("Folder")
		stats.Name = "leaderstats"
		local coins = Instance.new("IntValue")
		coins.Name = "Coins"
		coins.Parent = stats
		stats.Parent = player
	end
end
```

- Checking the direct parent (not `IsDescendantOf(workspace)`) is what stops "sell the map": a map part is never a Tool inside your own Backpack.
- Tool names can be renamed by nothing but the server, but your real inventory should live in server data; the Tool is only the visual, and the sale should remove the item from that data too.
- Destroy first, then pay: if anything errors in between, the player loses a tool instead of the server minting coins.

# Test
```lua
local remote = game:GetService("ReplicatedStorage"):WaitForChild("SellTool")
local seller = __makePlayer(1, "Seller")
local victim = __makePlayer(2, "Victim")
__makeCharacter(seller)
local function give(player, name)
	local tool = Instance.new("Tool")
	tool.Name = name
	tool.Parent = player.Backpack
	return tool
end
local mine = give(seller, "IronSword")
remote.OnServerEvent:Fire(seller, mine)
check("selling your own tool pays the server price", __leaderstat(seller, "Coins") == 40 and mine.Parent == nil)

local theirs = give(victim, "IronSword")
remote.OnServerEvent:Fire(seller, theirs)
check("someone else's tool is refused", theirs.Parent == victim.Backpack and __leaderstat(seller, "Coins") == 40)

local mapPart = Instance.new("Part")
mapPart.Parent = workspace
remote.OnServerEvent:Fire(seller, mapPart)
remote.OnServerEvent:Fire(seller, "IronSword")
check("non-tools and strings are refused", mapPart.Parent == workspace and __leaderstat(seller, "Coins") == 40)

local equipped = give(seller, "Bow")
equipped.Parent = seller.Character
remote.OnServerEvent:Fire(seller, equipped)
check("an equipped tool in the character can be sold", __leaderstat(seller, "Coins") == 65)

local junk = give(seller, "Rock")
remote.OnServerEvent:Fire(seller, junk)
check("unpriced items are not sold", junk.Parent == seller.Backpack and __leaderstat(seller, "Coins") == 65)
```
