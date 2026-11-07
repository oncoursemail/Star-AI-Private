---
id: gb-world-cs-kill-bricks
category: world-collectionservice
topics: CollectionService, kill brick, Touched, tag removal, obby
source: original
---
# Request
My obby has 200 kill bricks, each with its own copy of the same Script. Updating them is a nightmare and some copies are outdated. How do I do this with tags instead, including bricks that get added or removed while the game runs?

# Answer
One server Script handles every part tagged "KillBrick": it connects Touched when a part gets the tag (existing ones at start plus any added later) and disconnects when the tag is removed or the part is destroyed. A short per-character debounce keeps a single death from firing the kill effect for every limb that touches the brick.

```lua
--!strict
-- Script: ServerScriptService.KillBricks
local CollectionService = game:GetService("CollectionService")
local Players = game:GetService("Players")

local TAG = "KillBrick"
local connections: { [Instance]: RBXScriptConnection } = {}
local debounce: { [Model]: boolean } = {}

local function onAdded(instance: Instance)
	if not instance:IsA("BasePart") or connections[instance] then
		return
	end
	connections[instance] = instance.Touched:Connect(function(hit: BasePart)
		local character = hit:FindFirstAncestorOfClass("Model")
		local humanoid = if character then character:FindFirstChildOfClass("Humanoid") else nil
		if character == nil or humanoid == nil or debounce[character] or humanoid.Health <= 0 then
			return
		end
		if Players:GetPlayerFromCharacter(character) == nil then
			return
		end
		debounce[character] = true
		humanoid.Health = 0
		task.delay(1, function()
			debounce[character] = nil
		end)
	end)
end

local function onRemoved(instance: Instance)
	local connection = connections[instance]
	if connection then
		connection:Disconnect()
		connections[instance] = nil
	end
end

CollectionService:GetInstanceAddedSignal(TAG):Connect(onAdded)
CollectionService:GetInstanceRemovedSignal(TAG):Connect(onRemoved)
for _, instance in CollectionService:GetTagged(TAG) do
	onAdded(instance)
end
```

- Tag the bricks with Studio's Tag Editor (Properties > Tags); the script never needs to know where they are in the hierarchy.
- The removed signal also fires when a tagged part is destroyed or leaves the DataModel, so connections never leak as bricks are deleted.
- Only player characters are killed, so NPCs walking an obby course for decoration are unaffected; drop that check if NPCs should die too.
- Connecting added before reading `GetTagged` means a brick tagged in between cannot be missed; the `connections[instance]` check stops it being connected twice.

# Test
```lua
local cs = game:GetService("CollectionService")
local brick = Instance.new("Part")
brick.Anchored = true
brick.Parent = workspace
cs:AddTag(brick, "KillBrick")
```
```lua
local cs = game:GetService("CollectionService")
local brick = workspace.Part
local player = __makePlayer(111, "Jumper")
local character = __makeCharacter(player)
brick.Touched:Fire(character.RightHand)
check("existing tagged brick kills on touch", character.Humanoid.Health == 0)

local npc = __buildRig()
npc.Parent = workspace
brick.Touched:Fire(npc.Head)
check("NPCs are ignored", npc.Humanoid.Health == 100)

local later = Instance.new("Part")
later.Parent = workspace
cs:AddTag(later, "KillBrick")
local second = __makeCharacter(player)
later.Touched:Fire(second.Head)
check("brick tagged at runtime works", second.Humanoid.Health == 0)

cs:RemoveTag(later, "KillBrick")
__advance(1.1)
local third = __makeCharacter(player)
later.Touched:Fire(third.Head)
check("untagged brick is harmless again", third.Humanoid.Health == 100)
brick.Touched:Fire(third.Head)
check("original brick still works", third.Humanoid.Health == 0)
```
