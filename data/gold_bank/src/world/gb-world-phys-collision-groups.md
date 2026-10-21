---
id: gb-world-phys-collision-groups
category: physics
topics: PhysicsService, RegisterCollisionGroup, CollisionGroup, player collisions, characters
source: original
---
# Request
I want players to walk through each other (my obby gets clogged at checkpoints), but they should still collide with the map. Old tutorials use `PhysicsService:CreateCollisionGroup` and `SetPartCollisionGroup`, which give deprecation warnings. What's the current way?

# Answer
Register a "Players" group once with `RegisterCollisionGroup`, make it non-collidable with itself, and set each character part's `CollisionGroup` property. Characters gain parts after spawning (accessories, tools), so new descendants are assigned too.

```lua
--!strict
-- Script: ServerScriptService.PlayerCollisions
local Players = game:GetService("Players")
local PhysicsService = game:GetService("PhysicsService")

local GROUP = "Players"

if not PhysicsService:IsCollisionGroupRegistered(GROUP) then
	PhysicsService:RegisterCollisionGroup(GROUP)
end
PhysicsService:CollisionGroupSetCollidable(GROUP, GROUP, false)

local function assign(instance: Instance)
	if instance:IsA("BasePart") then
		instance.CollisionGroup = GROUP
	end
end

local function onCharacter(character: Model)
	for _, descendant in character:GetDescendants() do
		assign(descendant)
	end
	-- Connected on the character itself, so it is cleaned up when the character is destroyed.
	character.DescendantAdded:Connect(assign)
end

local function onPlayer(player: Player)
	player.CharacterAdded:Connect(onCharacter)
	if player.Character then
		onCharacter(player.Character)
	end
end

Players.PlayerAdded:Connect(onPlayer)
for _, player in Players:GetPlayers() do
	onPlayer(player)
end
```

- `CollisionGroup` is a plain property now; setting it replaces `SetPartCollisionGroup`.
- The group still collides with "Default", so the map, doors and moving platforms behave as before.
- Registering is limited to a fixed number of groups per place; register them once at startup, never per player.
- Collision groups only change physical collisions; raycasts and spatial queries still see the parts unless their params name a group.

# Test
```lua
local PhysicsService = game:GetService("PhysicsService")
check("group registered", PhysicsService:IsCollisionGroupRegistered("Players"))
check("players do not collide with each other", PhysicsService:CollisionGroupsAreCollidable("Players", "Players") == false)
check("players still collide with the map", PhysicsService:CollisionGroupsAreCollidable("Players", "Default") == true)
local player = __makePlayer(31, "Runner")
local character = __makeCharacter(player)
check("existing character parts assigned", character.HumanoidRootPart.CollisionGroup == "Players" and character.Head.CollisionGroup == "Players")
local hat = Instance.new("Part")
hat.Parent = character
check("parts added later are assigned", hat.CollisionGroup == "Players")
local respawned = __makeCharacter(player)
check("respawned character assigned", respawned.RightHand.CollisionGroup == "Players")
local floor = Instance.new("Part")
floor.Parent = workspace
check("map parts untouched", floor.CollisionGroup == "Default")
```
