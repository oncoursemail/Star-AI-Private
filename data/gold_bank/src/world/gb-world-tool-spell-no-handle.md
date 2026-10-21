---
id: gb-world-tool-spell-no-handle
category: tool-attachment
topics: RequiresHandle, Tool, RemoteEvent validation, area damage, cooldown
source: original
---
# Request
I'm making a fire spell as a Tool with no Handle (RequiresHandle off). The LocalScript sends the mouse hit position to the server on Activated and the server damages everyone near that point. How should the server side look so exploiters can't nuke the whole map with it?

# Answer
The client only gets to say where it aimed. The server checks the value is a real finite Vector3, that the caster is alive and actually holding the spell, that the point is within range of their character, and that the cooldown has passed; only then does it query the blast radius and damage each humanoid once.

```lua
--!strict
-- Script: ServerScriptService.FireSpellServer
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local castSpell = ReplicatedStorage:WaitForChild("CastSpell")

local TOOL_NAME = "FireSpell"
local MAX_RANGE = 80
local RADIUS = 8
local DAMAGE = 30
local COOLDOWN = 1.5

local lastCast: { [Player]: number } = {}

local function isFiniteVector(value: any): boolean
	local kind = typeof(value)
	if kind ~= "Vector3" then
		return false
	end
	for _, component in { value.X, value.Y, value.Z } do
		if component ~= component or math.abs(component) > 1e6 then
			return false
		end
	end
	return true
end

castSpell.OnServerEvent:Connect(function(player: Player, target: any)
	if not isFiniteVector(target) then
		return
	end
	local now = os.clock()
	if now - (lastCast[player] or -math.huge) < COOLDOWN then
		return
	end
	local character = player.Character
	if character == nil or character:FindFirstChild(TOOL_NAME) == nil then
		return
	end
	local humanoid = character:FindFirstChildOfClass("Humanoid")
	if humanoid == nil or humanoid.Health <= 0 then
		return
	end
	if player:DistanceFromCharacter(target) > MAX_RANGE then
		return
	end
	lastCast[player] = now

	local params = OverlapParams.new()
	params.FilterType = Enum.RaycastFilterType.Exclude
	params.FilterDescendantsInstances = { character }
	local damaged: { [Humanoid]: boolean } = {}
	for _, part in workspace:GetPartBoundsInRadius(target, RADIUS, params) do
		local model = part:FindFirstAncestorOfClass("Model")
		local victim = if model then model:FindFirstChildOfClass("Humanoid") else nil
		if victim and not damaged[victim] then
			damaged[victim] = true
			victim:TakeDamage(DAMAGE)
		end
	end
end)

Players.PlayerRemoving:Connect(function(player: Player)
	lastCast[player] = nil
end)
```

The LocalScript in the tool only reports the aim point:

```lua
--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local tool = script.Parent
local mouse = Players.LocalPlayer:GetMouse()
local castSpell = ReplicatedStorage:WaitForChild("CastSpell")

tool.Activated:Connect(function()
	castSpell:FireServer(mouse.Hit.Position)
end)
```

- Checking `character:FindFirstChild(TOOL_NAME)` means the spell must be equipped (an equipped Tool is parented to the character), so firing the remote from the backpack does nothing.
- NaN fails `component ~= component`, and huge values are refused before they reach the spatial query.
- The cooldown is stamped only after every check passes, so rejected spam cannot lock out a legitimate cast.
- `damaged` keys on the Humanoid so a target whose six parts are all in the radius still takes damage once.

# Test
```lua
local remote = Instance.new("RemoteEvent")
remote.Name = "CastSpell"
remote.Parent = game:GetService("ReplicatedStorage")
```
```lua
local caster = __makePlayer(7, "Mage")
local character = __makeCharacter(caster, Vector3.new(0, 3, 0))
local spell = Instance.new("Tool")
spell.Name = "FireSpell"
spell.Parent = character
local dummy = __buildRig(Vector3.new(20, 3, 0))
dummy.Parent = workspace
local remote = game:GetService("ReplicatedStorage").CastSpell

remote.OnServerEvent:Fire(caster, Vector3.new(20, 3, 0))
check("valid cast damages once", dummy.Humanoid.Health == 70)
remote.OnServerEvent:Fire(caster, Vector3.new(20, 3, 0))
check("cooldown blocks a second cast", dummy.Humanoid.Health == 70)
__advance(2)
remote.OnServerEvent:Fire(caster, Vector3.new(0 / 0, 3, 0))
remote.OnServerEvent:Fire(caster, "boom")
remote.OnServerEvent:Fire(caster, Vector3.new(500, 3, 0))
check("NaN, wrong type and out of range are rejected", dummy.Humanoid.Health == 70)
check("caster is never hit by their own blast", character.Humanoid.Health == 100)
spell.Parent = caster.Backpack
remote.OnServerEvent:Fire(caster, Vector3.new(20, 3, 0))
check("unequipped spell does nothing", dummy.Humanoid.Health == 70)
spell.Parent = character
remote.OnServerEvent:Fire(caster, Vector3.new(20, 3, 0))
check("re-equipped cast works after cooldown", dummy.Humanoid.Health == 40)
```
