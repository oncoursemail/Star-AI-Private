---
id: gb-src-player-collision-group
category: physics
topics: PhysicsService, collision groups, CollisionGroup, characters, DescendantAdded, player collisions
source: adapted
source_id: creator-docs
source_path: content/en-us/workspace/collisions.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
Players keep pushing each other off the narrow obby platforms. How do I make player characters pass through each other but still collide with the map?

# Answer
Register a "Characters" collision group that does not collide with itself, and put every BasePart of each character in it. Accessories and tools are added after spawn, so also handle `DescendantAdded`.

```lua
--!strict
local Players = game:GetService("Players")
local PhysicsService = game:GetService("PhysicsService")

local GROUP = "Characters"

PhysicsService:RegisterCollisionGroup(GROUP)
PhysicsService:CollisionGroupSetCollidable(GROUP, GROUP, false)

local function setGroup(descendant: Instance)
	if descendant:IsA("BasePart") then
		descendant.CollisionGroup = GROUP
	end
end

local function onCharacterAdded(character: Model)
	for _, descendant in character:GetDescendants() do
		setGroup(descendant)
	end
	character.DescendantAdded:Connect(setGroup)
end

local function onPlayerAdded(player: Player)
	player.CharacterAdded:Connect(onCharacterAdded)
	if player.Character then
		onCharacterAdded(player.Character)
	end
end

Players.PlayerAdded:Connect(onPlayerAdded)
for _, player in Players:GetPlayers() do
	onPlayerAdded(player)
end
```

- The group still collides with "Default", so characters stand on the map as before.
- The `DescendantAdded` connection belongs to the character model and is cleaned up when the character is destroyed on respawn.
- Register groups once at server start; the limit is 32 groups per experience.

# Test
```lua
local PhysicsService = game:GetService("PhysicsService")
check("group registered", PhysicsService:IsCollisionGroupRegistered("Characters"))
check("characters do not collide with each other", PhysicsService:CollisionGroupsAreCollidable("Characters", "Characters") == false)
check("characters still collide with the map", PhysicsService:CollisionGroupsAreCollidable("Characters", "Default") == true)
local p = __makePlayer(1, "Runner")
local character = __makeCharacter(p)
check("existing parts moved to group", character.HumanoidRootPart.CollisionGroup == "Characters" and character.Head.CollisionGroup == "Characters")
local hat = Instance.new("Part")
hat.Parent = character
check("parts added later are grouped", hat.CollisionGroup == "Characters")
```
