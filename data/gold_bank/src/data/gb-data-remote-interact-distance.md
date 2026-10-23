---
id: gb-data-remote-interact-distance
category: remote-security
topics: RemoteEvent, distance check, CollectionService, chest, server validation
source: original
---
# Request
My chests are opened with a RemoteEvent `OpenChest:FireServer(chestModel)`. Exploiters open every chest on the map from spawn. How should the server validate this request?

# Answer
The server checks that the argument is a real chest (a tagged Model in workspace), that the player has a living character close enough to it, and that the chest is not already opened or on cooldown for that player. Only then does the server roll and grant the reward.

```lua
--!strict
-- Script: ServerScriptService.Chests
local CollectionService = game:GetService("CollectionService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local MAX_DISTANCE = 12
local REOPEN_SECONDS = 300

local openChest = Instance.new("RemoteEvent")
openChest.Name = "OpenChest"
openChest.Parent = ReplicatedStorage

local lastOpened: { [Model]: { [number]: number } } = {}

local function validChest(value: unknown): Model?
	local kind = typeof(value)
	if kind ~= "Instance" then
		return nil
	end
	local chest = value :: any
	if chest:IsA("Model") and CollectionService:HasTag(chest, "Chest") and chest:IsDescendantOf(workspace) then
		return chest
	end
	return nil
end

local function withinReach(player: Player, chest: Model): boolean
	local character: Model? = player.Character
	if character == nil then
		return false
	end
	local root: BasePart? = character:FindFirstChild("HumanoidRootPart")
	local humanoid: Humanoid? = character:FindFirstChildOfClass("Humanoid")
	if root == nil or humanoid == nil or humanoid.Health <= 0 then
		return false
	end
	local pivot: CFrame = chest:GetPivot()
	return (root.Position - pivot.Position).Magnitude <= MAX_DISTANCE
end

local function onOpen(player: Player, value: unknown)
	local chest = validChest(value)
	if chest == nil or not withinReach(player, chest) then
		return
	end
	local userId: number = player.UserId
	local openedBy = lastOpened[chest] or {}
	lastOpened[chest] = openedBy
	local now = os.clock()
	local last = openedBy[userId]
	if last and now - last < REOPEN_SECONDS then
		return
	end
	openedBy[userId] = now
	local reward = chest:GetAttribute("Coins")
	player:SetAttribute("Coins", (player:GetAttribute("Coins") or 0) + (if type(reward) == "number" then reward else 5))
end

openChest.OnServerEvent:Connect(onOpen)

CollectionService:GetInstanceRemovedSignal("Chest"):Connect(function(chest: Instance)
	lastOpened[chest :: any] = nil
end)
```

- Use the chest's pivot, not a client-sent position; the client only names which chest, the server measures.
- Allow a little slack in `MAX_DISTANCE` for latency (the server sees the character slightly behind where the client is).
- The reward comes from an attribute you set in Studio on the chest, so exploiters cannot change what a chest is worth.

# Test
```lua
local CollectionService = game:GetService("CollectionService")
local remote = game:GetService("ReplicatedStorage"):WaitForChild("OpenChest")
local chest = Instance.new("Model")
local lid = Instance.new("Part")
lid.Position = Vector3.new(0, 3, 5)
lid.Parent = chest
chest.PrimaryPart = lid
chest:SetAttribute("Coins", 20)
CollectionService:AddTag(chest, "Chest")
chest.Parent = workspace

local near = __makePlayer(1, "Near")
__makeCharacter(near, Vector3.new(0, 3, 0))
local far = __makePlayer(2, "Far")
__makeCharacter(far, Vector3.new(200, 3, 0))

remote.OnServerEvent:Fire(near, chest)
check("nearby player opens the chest", near:GetAttribute("Coins") == 20)
remote.OnServerEvent:Fire(far, chest)
check("distant player is refused", far:GetAttribute("Coins") == nil)
remote.OnServerEvent:Fire(near, chest)
check("cannot reopen during the cooldown", near:GetAttribute("Coins") == 20)
__advance(301)
remote.OnServerEvent:Fire(near, chest)
check("can reopen after the cooldown", near:GetAttribute("Coins") == 40)

local fake = Instance.new("Model")
fake.Parent = workspace
remote.OnServerEvent:Fire(near, fake)
remote.OnServerEvent:Fire(near, nil)
check("untagged models and nil are refused", near:GetAttribute("Coins") == 40)

near.Character.Humanoid.Health = 0
__advance(301)
remote.OnServerEvent:Fire(near, chest)
check("dead characters cannot open chests", near:GetAttribute("Coins") == 40)
```
