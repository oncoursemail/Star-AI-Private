---
id: gb-src-leaderstats-gold-pickup
category: economy-simulation
topics: leaderstats, IntValue, Touched, GetPlayerFromCharacter, pickups, server authority
source: adapted
source_id: creator-docs
source_path: content/en-us/players/leaderboards.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I want a Gold column on the player list and gold nuggets around the map worth 10 each. Sometimes one nugget gives 20 or 30 gold because Touched fires for several body parts before it disappears. How do I set up leaderstats and make each nugget pay exactly once?

# Answer
Create a `leaderstats` folder with an `IntValue` per player on the server; the player list shows it automatically. For pickups, find the player from the touching part's model, and switch the nugget off before paying, so later Touched events in the same frame are ignored.

```lua
--!strict
local CollectionService = game:GetService("CollectionService")
local Players = game:GetService("Players")

local NUGGET_TAG = "GoldNugget"
local NUGGET_VALUE = 10

local function setupLeaderstats(player: Player)
	local leaderstats = Instance.new("Folder")
	leaderstats.Name = "leaderstats"
	local gold = Instance.new("IntValue")
	gold.Name = "Gold"
	gold.Value = 0
	gold.Parent = leaderstats
	leaderstats.Parent = player
end

local function getGoldStat(player: Player): IntValue?
	local leaderstats = player:FindFirstChild("leaderstats")
	local gold = if leaderstats then leaderstats:FindFirstChild("Gold") else nil
	if gold and gold:IsA("IntValue") then
		return gold
	end
	return nil
end

local function setupNugget(nugget: Instance)
	if not nugget:IsA("BasePart") then
		return
	end
	local active = true
	nugget.Touched:Connect(function(otherPart: BasePart)
		if not active then
			return
		end
		local player = Players:GetPlayerFromCharacter(otherPart.Parent)
		local gold = if player then getGoldStat(player) else nil
		if not gold then
			return
		end
		active = false
		gold.Value += NUGGET_VALUE
		nugget:Destroy()
	end)
end

Players.PlayerAdded:Connect(setupLeaderstats)
for _, player in Players:GetPlayers() do
	setupLeaderstats(player)
end
for _, nugget in CollectionService:GetTagged(NUGGET_TAG) do
	setupNugget(nugget)
end
CollectionService:GetInstanceAddedSignal(NUGGET_TAG):Connect(setupNugget)
```

- The folder must be named exactly `leaderstats` and parented to the Player for the default player list to show it.
- Clearing `active` before paying makes the pickup pay once even when several limbs touch in one frame.
- All of this runs on the server; a client changing its own `Gold` value only changes its local copy.

# Test
```lua
local CollectionService = game:GetService("CollectionService")
local nugget = Instance.new("Part")
nugget.Parent = workspace
CollectionService:AddTag(nugget, "GoldNugget")
```

```lua
local nugget = workspace:FindFirstChildOfClass("Part")
local p = __makePlayer(1, "Miner")
local character = __makeCharacter(p)
local gold = p.leaderstats.Gold
check("leaderstats created with zero gold", gold.Value == 0)
local stray = Instance.new("Part")
stray.Parent = workspace
nugget.Touched:Fire(stray)
check("non-character touch ignored", gold.Value == 0)
nugget.Touched:Fire(character.HumanoidRootPart)
nugget.Touched:Fire(character.Head)
nugget.Touched:Fire(character.RightHand)
check("pays exactly once", gold.Value == 10)
check("nugget removed", nugget.Parent == nil)
```
