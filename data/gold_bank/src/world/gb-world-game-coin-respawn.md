---
id: gb-world-game-coin-respawn
category: gameplay-systems
topics: collectibles, coins, respawn timer, leaderstats, Touched debounce
source: original
---
# Request
I have coins around the map (tagged "Coin"). Touching one should give +1 coin once, hide it, and bring it back after 15 seconds. My current version sometimes gives 3-4 coins per touch and destroyed coins never come back.

# Answer
Each Touched burst comes from several limbs, so the coin needs a per-coin debounce flag set before anything is awarded. Instead of destroying the coin, hide it (transparent, `CanTouch` off) and restore it after the respawn delay. Coins carry their value as an attribute, and only real player characters can collect.

```lua
--!strict
-- Script: ServerScriptService.Coins
local CollectionService = game:GetService("CollectionService")
local Players = game:GetService("Players")

local RESPAWN = 15
local debounce: { [BasePart]: boolean } = {}

local function coinsStat(player: Player): IntValue?
	local leaderstats = player:FindFirstChild("leaderstats")
	local stat = if leaderstats then leaderstats:FindFirstChild("Coins") else nil
	return if stat and stat:IsA("IntValue") then stat else nil
end

local function setVisible(coin: BasePart, visible: boolean)
	coin.Transparency = if visible then 0 else 1
	coin.CanTouch = visible
	for _, child in coin:GetDescendants() do
		if child:IsA("ParticleEmitter") or child:IsA("PointLight") then
			child.Enabled = visible
		end
	end
end

local function onCoin(coin: Instance)
	if not coin:IsA("BasePart") then
		return
	end
	coin.Touched:Connect(function(hit: BasePart)
		if debounce[coin] then
			return
		end
		local character = hit:FindFirstAncestorOfClass("Model")
		local player = if character then Players:GetPlayerFromCharacter(character) else nil
		local stat = if player then coinsStat(player) else nil
		if stat == nil then
			return
		end
		debounce[coin] = true
		local value = coin:GetAttribute("Value")
		stat.Value += if type(value) == "number" then value else 1
		setVisible(coin, false)
		task.delay(RESPAWN, function()
			if coin.Parent then
				setVisible(coin, true)
			end
			debounce[coin] = nil
		end)
	end)
end

local function onPlayer(player: Player)
	local leaderstats = Instance.new("Folder")
	leaderstats.Name = "leaderstats"
	local coins = Instance.new("IntValue")
	coins.Name = "Coins"
	coins.Parent = leaderstats
	leaderstats.Parent = player
end

CollectionService:GetInstanceAddedSignal("Coin"):Connect(onCoin)
for _, coin in CollectionService:GetTagged("Coin") do
	onCoin(coin)
end
Players.PlayerAdded:Connect(onPlayer)
for _, player in Players:GetPlayers() do
	onPlayer(player)
end
```

- `debounce[coin] = true` is set before the award, so the other limbs' Touched events that arrive in the same moment see the coin as taken.
- Hiding instead of destroying means the coin keeps its place, tags and effects; respawning is just making it visible again.
- The award is computed on the server from the coin's own attribute; nothing the client sends is involved.
- With hundreds of coins, consider letting each client hide coins it collected locally for snappier feedback, while the server stays the authority on the count.

# Test
```lua
local cs = game:GetService("CollectionService")
local coin = Instance.new("Part")
coin.Name = "Coin"
coin.Anchored = true
coin.Parent = workspace
cs:AddTag(coin, "Coin")
local gem = Instance.new("Part")
gem.Name = "Gem"
gem:SetAttribute("Value", 5)
gem.Parent = workspace
cs:AddTag(gem, "Coin")
```
```lua
local player = __makePlayer(161, "Collector")
local character = __makeCharacter(player)
local coin, gem = workspace.Coin, workspace.Gem
coin.Touched:Fire(character.RightHand)
coin.Touched:Fire(character.Head)
coin.Touched:Fire(character.HumanoidRootPart)
check("several limbs touching awards once", __leaderstat(player, "Coins") == 1)
check("coin hidden after pickup", coin.Transparency == 1 and coin.CanTouch == false)
gem.Touched:Fire(character.Head)
check("value attribute respected", __leaderstat(player, "Coins") == 6)
local npc = __buildRig()
npc.Parent = workspace
__advance(16)
check("coin respawns after the delay", coin.Transparency == 0 and coin.CanTouch == true)
coin.Touched:Fire(npc.Head)
check("NPCs cannot collect", coin.Transparency == 0)
coin.Touched:Fire(character.Head)
check("respawned coin can be collected again", __leaderstat(player, "Coins") == 7)
```
