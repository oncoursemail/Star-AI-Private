---
id: gb-world-game-obby-checkpoints
category: gameplay-systems
topics: checkpoints, obby stage, DataStore, UpdateAsync, respawn location
source: original
---
# Request
I need obby checkpoints: touching checkpoint N+1 advances your stage (no skipping ahead by flinging to a later pad), you respawn at your current stage, and the stage is saved so you continue next time you join. What's a solid server script for that?

# Answer
Keep each player's stage on the server, advance it only when the touched checkpoint is exactly the next one, and move the character to its checkpoint on every spawn. The stage is loaded with retries on join and saved with `UpdateAsync` on leave and on shutdown, never lowering a saved value.

```lua
--!strict
-- Script: ServerScriptService.Checkpoints
local DataStoreService = game:GetService("DataStoreService")
local Players = game:GetService("Players")

local store = DataStoreService:GetDataStore("ObbyStage_v1")
local checkpoints = workspace:WaitForChild("Checkpoints")

local stage: { [Player]: number } = {}
local cooldown: { [Player]: number } = {}

-- `call` returns pcall's results; retried with backoff on failure.
local function withRetries(label: string, call: () -> (boolean, any)): (boolean, any)
	for try = 1, 3 do
		local ok, result = call()
		if ok then
			return true, result
		end
		warn(string.format("%s failed (try %d): %s", label, try, tostring(result)))
		task.wait(2 ^ try)
	end
	return false, nil
end

local function keyFor(player: Player): string
	return "u_" .. player.UserId
end

local function spawnAtStage(player: Player, character: Model)
	local pad = checkpoints:FindFirstChild(tostring(stage[player] or 1))
	if pad and pad:IsA("BasePart") then
		character:PivotTo(pad.CFrame + Vector3.new(0, pad.Size.Y / 2 + 3, 0))
	end
end

local function save(player: Player)
	local value = stage[player]
	if value == nil then
		return
	end
	withRetries("save stage", function()
		return pcall(store.UpdateAsync, store, keyFor(player), function(old: any)
			return math.max(if type(old) == "number" then old else 1, value)
		end)
	end)
end

local function onPlayer(player: Player)
	local ok, value = withRetries("load stage", function()
		return pcall(store.GetAsync, store, keyFor(player))
	end)
	local saved = 1
	if ok and type(value) == "number" and value >= 1 then
		saved = math.floor(value)
	end
	stage[player] = saved

	local leaderstats = Instance.new("Folder")
	leaderstats.Name = "leaderstats"
	local stat = Instance.new("IntValue")
	stat.Name = "Stage"
	stat.Value = saved
	stat.Parent = leaderstats
	leaderstats.Parent = player

	player.CharacterAdded:Connect(function(character: Model)
		spawnAtStage(player, character)
	end)
	if player.Character then
		spawnAtStage(player, player.Character)
	end
end

for _, pad in checkpoints:GetChildren() do
	local number = tonumber(pad.Name)
	if pad:IsA("BasePart") and number then
		pad.Touched:Connect(function(hit: BasePart)
			local character = hit:FindFirstAncestorOfClass("Model")
			local player = if character then Players:GetPlayerFromCharacter(character) else nil
			if player == nil or stage[player] == nil or os.clock() - (cooldown[player] or 0) < 0.25 then
				return
			end
			cooldown[player] = os.clock()
			if number == stage[player] + 1 then
				stage[player] = number
				local leaderstats = player:FindFirstChild("leaderstats")
				local stat = leaderstats and leaderstats:FindFirstChild("Stage")
				if stat then
					stat.Value = number
				end
			end
		end)
	end
end

Players.PlayerAdded:Connect(onPlayer)
for _, player in Players:GetPlayers() do
	task.spawn(onPlayer, player)
end

Players.PlayerRemoving:Connect(function(player: Player)
	save(player)
	stage[player] = nil
	cooldown[player] = nil
end)

game:BindToClose(function()
	for _, player in Players:GetPlayers() do
		task.spawn(save, player)
	end
	task.wait(5)
end)
```

- "Exactly the next checkpoint" is the anti-skip rule: a flung player touching pad 40 from stage 3 gets nothing.
- `UpdateAsync` with `math.max` means a stale server that saves late can never overwrite newer progress with a lower stage.
- Checkpoint pads are named "1", "2", ... inside a `Checkpoints` folder, so adding a stage is just adding a part.
- The short per-player cooldown skips the dozens of Touched events a player standing on a pad fires each second.

# Test
```lua
local folder = Instance.new("Folder")
folder.Name = "Checkpoints"
for i = 1, 3 do
	local pad = Instance.new("Part")
	pad.Name = tostring(i)
	pad.Anchored = true
	pad.Size = Vector3.new(6, 1, 6)
	pad.Position = Vector3.new(i * 30, 0, 0)
	pad.Parent = folder
end
folder.Parent = workspace
```
```lua
local store = game:GetService("DataStoreService"):GetDataStore("ObbyStage_v1")
local pads = workspace.Checkpoints
local player = __makePlayer(131, "Climber")
local character = __makeCharacter(player)
check("new player starts at stage 1 on pad 1", __leaderstat(player, "Stage") == 1 and math.abs(character.HumanoidRootPart.Position.X - 30) < 1e-6)
pads["3"].Touched:Fire(character.RightHand)
check("skipping ahead is ignored", __leaderstat(player, "Stage") == 1)
__advance(0.5)
pads["2"].Touched:Fire(character.RightHand)
check("next checkpoint advances", __leaderstat(player, "Stage") == 2)
local respawned = __makeCharacter(player)
check("respawn at the current stage", math.abs(respawned.HumanoidRootPart.Position.X - 60) < 1e-6)
__removePlayer(player)
__advance(1)
check("stage saved on leave", store:GetAsync("u_131") == 2)
game:GetService("DataStoreService").__failNext = 1
local back = __makePlayer(131, "Climber")
__advance(5)
check("rejoining loads the saved stage despite a failed first read", __leaderstat(back, "Stage") == 2)
store:SetAsync("u_131", 5)
__close()
check("shutdown save never lowers progress", store:GetAsync("u_131") == 5)
```
