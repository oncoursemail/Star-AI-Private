---
id: gb-data-remote-fix-give-cash
category: remote-security
topics: RemoteEvent, leaderstats, obby, server authority, checkpoint reward
source: original
---
# Request
In my obby a LocalScript notices when you step on a stage's finish pad and tells the server how much to pay you. Someone told me this is exploitable. Is it, and what is the proper setup?

```lua
StageDone.OnServerEvent:Connect(function(plr, reward)
	local stats = plr:WaitForChild("leaderstats")
	stats.Cash.Value += reward
end)
```

# Answer
Yes: any client can fire `StageDone` with any amount, as often as it likes. Remove the remote entirely. The server can see the touch itself: each stage-end part has a `Stage` number and a `Reward` attribute, and the server pays a player once per stage, only in order, only for a living character.

```lua
--!strict
-- Script: ServerScriptService.StageRewards
local CollectionService = game:GetService("CollectionService")
local Players = game:GetService("Players")

local reachedStage: { [Player]: number } = {}

local function setupStats(player: Player)
	local stats = Instance.new("Folder")
	stats.Name = "leaderstats"
	local cash = Instance.new("IntValue")
	cash.Name = "Cash"
	cash.Parent = stats
	stats.Parent = player
	reachedStage[player] = 0
end

local function payStage(stagePart: BasePart, hit: BasePart)
	local character = hit.Parent
	local player = character and Players:GetPlayerFromCharacter(character)
	if player == nil then
		return
	end
	local humanoid: Humanoid? = (character :: Model):FindFirstChildOfClass("Humanoid")
	local stage = stagePart:GetAttribute("Stage")
	local reward = stagePart:GetAttribute("Reward")
	if humanoid == nil or humanoid.Health <= 0 or type(stage) ~= "number" or type(reward) ~= "number" then
		return
	end
	-- the stage table is the debounce: each stage pays once, and only right after the previous one
	if reachedStage[player] ~= stage - 1 then
		return
	end
	reachedStage[player] = stage
	local stats: Instance? = player:FindFirstChild("leaderstats")
	local cash: Instance? = if stats then stats:FindFirstChild("Cash") else nil
	if cash and cash:IsA("IntValue") then
		(cash :: IntValue).Value += reward
	end
end

local function stageHandler(stagePart: BasePart): (BasePart) -> ()
	return function(hit: BasePart)
		payStage(stagePart, hit)
	end
end

Players.PlayerRemoving:Connect(function(player: Player)
	reachedStage[player] = nil
end)
Players.PlayerAdded:Connect(setupStats)
for _, player in Players:GetPlayers() do
	setupStats(player)
end
for _, stagePart in CollectionService:GetTagged("StageEnd") do
	stagePart.Touched:Connect(stageHandler(stagePart))
end
```

- `Reward` and `Stage` are attributes you set in Studio on the parts tagged `StageEnd`; clients cannot change server-side attributes.
- Requiring stage N-1 before N stops teleport exploits from collecting the last stage's reward directly.
- Save `reachedStage` with the player's data if stages should stay completed between sessions.

# Test
```lua
local CollectionService = game:GetService("CollectionService")
local function stageEnd(n, reward)
	local part = Instance.new("Part")
	part:SetAttribute("Stage", n)
	part:SetAttribute("Reward", reward)
	CollectionService:AddTag(part, "StageEnd")
	part.Parent = workspace
	return part
end
local s1 = stageEnd(1, 10)
local s2 = stageEnd(2, 25)
local s3 = stageEnd(3, 50)
```
```lua
local runner = __makePlayer(1, "Runner")
local character = __makeCharacter(runner)
local foot = character.HumanoidRootPart
local stages = {}
for _, part in game:GetService("CollectionService"):GetTagged("StageEnd") do
	stages[part:GetAttribute("Stage")] = part
end

stages[1].Touched:Fire(foot)
check("finishing stage 1 pays its reward", __leaderstat(runner, "Cash") == 10)
stages[1].Touched:Fire(foot)
stages[1].Touched:Fire(foot)
check("touching again pays nothing", __leaderstat(runner, "Cash") == 10)
stages[3].Touched:Fire(foot)
check("skipping ahead pays nothing", __leaderstat(runner, "Cash") == 10)
stages[2].Touched:Fire(foot)
stages[3].Touched:Fire(foot)
check("stages in order pay in full", __leaderstat(runner, "Cash") == 85)

local loose = Instance.new("Part")
loose.Parent = workspace
stages[1].Touched:Fire(loose)
check("touches from non-characters are ignored", __leaderstat(runner, "Cash") == 85)
```
