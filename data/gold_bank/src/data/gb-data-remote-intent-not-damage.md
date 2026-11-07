---
id: gb-data-remote-intent-not-damage
category: remote-security
topics: RemoteEvent, server authority, damage, cooldown, melee
source: original
---
# Request
My melee hits are detected on the client and reported like this. Someone with an exploit is killing whole lobbies in one click from spawn. How do I fix the server side?

```lua
HitRemote.OnServerEvent:Connect(function(plr, hitModel, dmg)
	local hum = hitModel:FindFirstChild("Humanoid")
	if hum then
		hum.Health -= dmg
	end
end)
```

# Answer
The client is deciding the result (who and how much). Let it send only the intent, "I swung at this character", and let the server decide the rest: the damage comes from the weapon's server config, the swing rate is limited by a cooldown, and the target must be a living character in reach and not the attacker.

```lua
--!strict
-- Script: ServerScriptService.SwordServer
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local SWORD = { damage = 20, range = 8, cooldown = 0.6 }

local swing = Instance.new("RemoteEvent")
swing.Name = "SwordSwing"
swing.Parent = ReplicatedStorage

local lastSwing: { [Player]: number } = {}

local function livingHumanoid(model: Model): Humanoid?
	local humanoid: Humanoid? = model:FindFirstChildOfClass("Humanoid")
	if humanoid and humanoid.Health > 0 then
		return humanoid
	end
	return nil
end

local function onSwing(player: Player, targetArg: unknown)
	local now = os.clock()
	local last = lastSwing[player]
	if last and now - last < SWORD.cooldown then
		return
	end
	local kind = typeof(targetArg)
	if kind ~= "Instance" or not (targetArg :: any):IsA("Model") then
		return
	end
	local target = targetArg :: Model
	local character: Model? = player.Character
	if character == nil or target == character or livingHumanoid(character) == nil then
		return
	end
	local humanoid = livingHumanoid(target)
	local myRoot: BasePart? = character:FindFirstChild("HumanoidRootPart")
	local theirRoot: BasePart? = target:FindFirstChild("HumanoidRootPart")
	if humanoid == nil or myRoot == nil or theirRoot == nil then
		return
	end
	if (myRoot.Position - theirRoot.Position).Magnitude > SWORD.range then
		return
	end
	lastSwing[player] = now
	humanoid:TakeDamage(SWORD.damage)
end

swing.OnServerEvent:Connect(onSwing)
Players.PlayerRemoving:Connect(function(player: Player)
	lastSwing[player] = nil
end)
```

- The cooldown is recorded only for valid swings, so a laggy miss does not eat the next real hit, but spam still cannot beat `SWORD.cooldown`.
- `range` should be a bit larger than the visual reach to absorb latency. Distance uses the positions the server sees, not a value in the request, but the attacker's character position still replicates from their own client, so pair this with server-side movement checks if teleport-and-hit matters.
- For teams, add a check that `Players:GetPlayerFromCharacter(target)` is not on the attacker's team before applying damage.

# Test
```lua
local remote = game:GetService("ReplicatedStorage"):WaitForChild("SwordSwing")
local attacker = __makePlayer(1, "Attacker")
local victim = __makePlayer(2, "Victim")
local farAway = __makePlayer(3, "Far")
local a = __makeCharacter(attacker, Vector3.new(0, 3, 0))
local v = __makeCharacter(victim, Vector3.new(5, 3, 0))
local f = __makeCharacter(farAway, Vector3.new(300, 3, 0))

remote.OnServerEvent:Fire(attacker, v, 9999)
check("server damage is used, not the client's number", v.Humanoid.Health == 80)
remote.OnServerEvent:Fire(attacker, v)
check("swings inside the cooldown are ignored", v.Humanoid.Health == 80)
__advance(0.7)
remote.OnServerEvent:Fire(attacker, f)
check("targets out of range are refused", f.Humanoid.Health == 100)
remote.OnServerEvent:Fire(attacker, v)
check("a missed swing does not start the cooldown", v.Humanoid.Health == 60)
__advance(0.7)
remote.OnServerEvent:Fire(attacker, a)
check("cannot hit yourself", a.Humanoid.Health == 100)
remote.OnServerEvent:Fire(attacker, workspace)
remote.OnServerEvent:Fire(attacker, "Victim")
check("non-character arguments are refused", v.Humanoid.Health == 60)
```
