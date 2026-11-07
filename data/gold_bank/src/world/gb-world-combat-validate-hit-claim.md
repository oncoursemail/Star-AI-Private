---
id: gb-world-combat-validate-hit-claim
category: combat-hitbox
topics: client hit detection, server validation, ping tolerance, cooldown, RemoteEvent
source: original
---
# Request
I detect sword hits on the client for responsiveness and send `HitRemote:FireServer(targetCharacter)`. The server then just deals damage. How do I validate that so exploiters can't hit people across the map, while laggy players don't get their legit hits rejected?

# Answer
Treat the claim as a request. The server checks the target is a living character other than the attacker, the attacker has the sword equipped and is off cooldown, and the target is within reach plus a tolerance that grows with the attacker's ping and the target's speed (where the target was on the attacker's screen). Close targets skip the facing check because at point-blank range body angles are unreliable.

```lua
--!strict
-- Script: ServerScriptService.SwordHitServer
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local hitRemote = ReplicatedStorage:WaitForChild("SwordHit")

local REACH = 7
local BASE_SLACK = 2
local MAX_PING = 0.35
local COOLDOWN = 0.45
local DAMAGE = 20
local lastHit: { [Player]: number } = {}

local function rootOf(model: Model): BasePart?
	local root = model:FindFirstChild("HumanoidRootPart")
	return if root and root:IsA("BasePart") then root else nil
end

hitRemote.OnServerEvent:Connect(function(player: Player, target: any)
	if typeof(target) ~= "Instance" or not target:IsA("Model") then
		return
	end
	local character = player.Character
	if character == nil or target == character or character:FindFirstChild("Sword") == nil then
		return
	end
	local humanoid = character:FindFirstChildOfClass("Humanoid")
	local victim = target:FindFirstChildOfClass("Humanoid")
	local attackerRoot, victimRoot = rootOf(character), rootOf(target)
	if not (humanoid and victim and attackerRoot and victimRoot) or humanoid.Health <= 0 or victim.Health <= 0 then
		return
	end
	local now = os.clock()
	if now - (lastHit[player] or -math.huge) < COOLDOWN then
		return
	end

	local ping = math.min(player:GetNetworkPing(), MAX_PING)
	local slack = BASE_SLACK + victimRoot.AssemblyLinearVelocity.Magnitude * ping
	local offset = victimRoot.Position - attackerRoot.Position
	local distance = offset.Magnitude
	if distance > REACH + slack then
		return
	end
	if distance > 3 and attackerRoot.CFrame.LookVector:Dot(offset.Unit) < 0 then
		return
	end

	lastHit[player] = now
	victim:TakeDamage(DAMAGE)
end)

Players.PlayerRemoving:Connect(function(player: Player)
	lastHit[player] = nil
end)
```

- Damage is a server constant; the client only names a target, never an amount.
- The ping used for tolerance is capped, so faking a huge ping cannot buy unlimited reach.
- Moving targets get extra slack because the attacker saw them where they were one ping ago; standing targets get almost none.
- The cooldown is stamped only after every check passes, so rejected claims cannot be used to desync a real player's swing timing.

# Test
```lua
local remote = Instance.new("RemoteEvent")
remote.Name = "SwordHit"
remote.Parent = game:GetService("ReplicatedStorage")
```
```lua
local attacker = __makePlayer(44, "Duelist")
local character = __makeCharacter(attacker, Vector3.new(0, 3, 0))
local sword = Instance.new("Tool")
sword.Name = "Sword"
sword.Parent = character
local remote = game:GetService("ReplicatedStorage").SwordHit
local near = __buildRig(Vector3.new(0, 3, -5))
near.Parent = workspace
local far = __buildRig(Vector3.new(0, 3, -40))
far.Parent = workspace
local behind = __buildRig(Vector3.new(0, 3, 6))
behind.Parent = workspace

remote.OnServerEvent:Fire(attacker, near)
check("legit hit in front deals damage", near.Humanoid.Health == 80)
remote.OnServerEvent:Fire(attacker, near)
check("cooldown blocks instant repeat", near.Humanoid.Health == 80)
__advance(1)
remote.OnServerEvent:Fire(attacker, far)
remote.OnServerEvent:Fire(attacker, behind)
remote.OnServerEvent:Fire(attacker, character)
remote.OnServerEvent:Fire(attacker, "near")
remote.OnServerEvent:Fire(attacker, Instance.new("Part"))
check("far, behind, self and junk claims rejected", far.Humanoid.Health == 100 and behind.Humanoid.Health == 100 and character.Humanoid.Health == 100)
far.HumanoidRootPart.Position = Vector3.new(0, 3, -9.5)
far.HumanoidRootPart.AssemblyLinearVelocity = Vector3.new(0, 0, -16)
remote.OnServerEvent:Fire(attacker, far)
check("moving target slightly out of reach is accepted with ping slack", far.Humanoid.Health == 80)
__advance(1)
sword.Parent = attacker.Backpack
remote.OnServerEvent:Fire(attacker, near)
check("unequipped sword cannot hit", near.Humanoid.Health == 80)
```
