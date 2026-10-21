---
id: gb-world-game-spawn-protection
category: gameplay-systems
topics: spawn protection, ForceField, spawn camping, tool Activated, zone exit
source: original
---
# Request
Players get spawn-killed. I want 5 seconds of spawn protection, but it should end early if the protected player attacks (activates a tool) or walks more than 30 studs from where they spawned, so it can't be abused for free kills.

# Answer
On each spawn give the character a ForceField and watch three things: a 5-second timer, the character's tools being activated, and the distance from the spawn point (checked a few times per second). The first one to fire removes the ForceField and cancels the rest.

```lua
--!strict
-- ModuleScript: ServerScriptService.SpawnProtection
export type Options = { duration: number, maxDistance: number }

local SpawnProtection = {}

function SpawnProtection.protect(player: Player, character: Model, options: Options): () -> ()
	local root = character:FindFirstChild("HumanoidRootPart")
	if root == nil or not root:IsA("BasePart") then
		return function() end
	end
	local origin = root.Position
	local shield = Instance.new("ForceField")
	shield.Visible = true
	shield.Parent = character

	local connections: { RBXScriptConnection } = {}
	local active = true

	local function endProtection()
		if not active then
			return
		end
		active = false
		for _, connection in connections do
			connection:Disconnect()
		end
		shield:Destroy()
	end

	local function watchTool(child: Instance)
		if child:IsA("Tool") then
			connections[#connections + 1] = child.Activated:Connect(endProtection)
		end
	end
	for _, child in character:GetChildren() do
		watchTool(child)
	end
	connections[#connections + 1] = character.ChildAdded:Connect(watchTool)

	task.spawn(function()
		local started = os.clock()
		while active and os.clock() - started < options.duration do
			if root.Parent == nil or (root.Position - origin).Magnitude > options.maxDistance then
				break
			end
			task.wait(0.2)
		end
		endProtection()
	end)

	return endProtection
end

return SpawnProtection
```

Hooking it to spawns:

```lua
--!strict
local Players = game:GetService("Players")
local SpawnProtection = require(script.Parent:WaitForChild("SpawnProtection"))

local OPTIONS = { duration = 5, maxDistance = 30 }

local function onPlayer(player: Player)
	player.CharacterAdded:Connect(function(character)
		character:WaitForChild("HumanoidRootPart")
		SpawnProtection.protect(player, character, OPTIONS)
	end)
	if player.Character then
		SpawnProtection.protect(player, player.Character, OPTIONS)
	end
end

Players.PlayerAdded:Connect(onPlayer)
for _, player in Players:GetPlayers() do
	onPlayer(player)
end
```

- `Humanoid:TakeDamage` already skips characters with a ForceField, so weapons that use it respect the protection automatically; weapons that set `Health` directly do not.
- Set `SpawnLocation.Duration` to 0 so the engine's own ForceField does not overlap with this one.
- Tool `Activated` fires on the server for equipped tools, so attacking with any tool ends the protection, including tools equipped after spawning.

# Test
```lua
local player = __makePlayer(151, "Spawner")
local character = __makeCharacter(player, Vector3.new(0, 3, 0))
local options = { duration = 5, maxDistance = 30 }

item.protect(player, character, options)
check("forcefield on spawn", character:FindFirstChildOfClass("ForceField") ~= nil)
character.Humanoid:TakeDamage(50)
check("protected from damage", character.Humanoid.Health == 100)
__advance(5.3)
check("protection ends after the duration", character:FindFirstChildOfClass("ForceField") == nil)

local c2 = __makeCharacter(player, Vector3.new(0, 3, 0))
item.protect(player, c2, options)
local sword = Instance.new("Tool")
sword.Parent = c2
sword:Activate()
check("attacking ends protection early", c2:FindFirstChildOfClass("ForceField") == nil)

local c3 = __makeCharacter(player, Vector3.new(0, 3, 0))
item.protect(player, c3, options)
c3.HumanoidRootPart.Position = Vector3.new(50, 3, 0)
__advance(0.3)
check("leaving the spawn area ends protection", c3:FindFirstChildOfClass("ForceField") == nil)
local c4 = __makeCharacter(player, Vector3.new(0, 3, 0))
local stopEarly = item.protect(player, c4, options)
stopEarly()
check("manual end works and is idempotent", c4:FindFirstChildOfClass("ForceField") == nil and pcall(stopEarly))
```
