---
id: gb-world-phys-throw-server
category: physics
topics: thrown object, SetNetworkOwner, AssemblyLinearVelocity, RemoteEvent, aim validation
source: original
---
# Request
My snowball tool sends the throw velocity from the client and the server sets it on a new part. Exploiters send huge velocities, and normal throws sometimes hang in the air for a split second before moving. How should the server handle the throw?

# Answer
Have the client send only an aim direction; the server checks it is a finite, roughly unit vector, applies its own fixed speed, and spawns the snowball in front of the thrower's root. Set the network owner to the server before giving it velocity: the "hang" is ownership being handed over to a nearby client mid-flight.

```lua
--!strict
-- Script: ServerScriptService.SnowballServer
local Debris = game:GetService("Debris")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerStorage = game:GetService("ServerStorage")

local throwRemote = ReplicatedStorage:WaitForChild("ThrowSnowball")
local template = ServerStorage:WaitForChild("Snowball")

local SPEED = 90
local COOLDOWN = 0.5
local LIFETIME = 6
local MAX_INHERIT = 40
local lastThrow: { [Player]: number } = {}

throwRemote.OnServerEvent:Connect(function(player: Player, aim: any)
	if typeof(aim) ~= "Vector3" or aim.Magnitude ~= aim.Magnitude or math.abs(aim.Magnitude - 1) > 0.05 then
		return
	end
	local now = os.clock()
	if now - (lastThrow[player] or -math.huge) < COOLDOWN then
		return
	end
	local character = player.Character
	local root = if character then character:FindFirstChild("HumanoidRootPart") else nil
	local humanoid = if character then character:FindFirstChildOfClass("Humanoid") else nil
	if root == nil or humanoid == nil or humanoid.Health <= 0 then
		return
	end
	lastThrow[player] = now

	local direction: Vector3 = aim.Unit
	local snowball = template:Clone()
	snowball.CFrame = CFrame.new(root.Position + direction * 3 + Vector3.new(0, 1.5, 0))
	snowball.Parent = workspace
	snowball:SetNetworkOwner(nil)
	-- The character's velocity is reported by its own client, so only a plausible running speed is inherited.
	local inherited = root.AssemblyLinearVelocity
	if not (inherited.Magnitude <= MAX_INHERIT) then
		inherited = Vector3.zero
	end
	snowball.AssemblyLinearVelocity = direction * SPEED + inherited
	snowball:SetAttribute("ThrowerUserId", player.UserId)
	Debris:AddItem(snowball, LIFETIME)
end)

Players.PlayerRemoving:Connect(function(player: Player)
	lastThrow[player] = nil
end)
```

- The client controls only the direction; speed, spawn point and lifetime are server constants, so a modified client cannot launch a snowball across the map.
- `SetNetworkOwner(nil)` keeps the server simulating the projectile, which also makes its collisions authoritative for hit detection.
- Adding the thrower's own velocity makes throws while running feel right instead of the ball lagging behind; it is capped (and NaN dropped) because an exploiter can set their own character's velocity to anything.
- If you prefer client-smooth visuals, render a cosmetic copy on the thrower's client and keep this server part invisible.

# Test
```lua
local rs = game:GetService("ReplicatedStorage")
local remote = Instance.new("RemoteEvent")
remote.Name = "ThrowSnowball"
remote.Parent = rs
local ball = Instance.new("Part")
ball.Name = "Snowball"
ball.Size = Vector3.new(1, 1, 1)
ball.Parent = game:GetService("ServerStorage")
```
```lua
local player = __makePlayer(32, "Thrower")
local character = __makeCharacter(player, Vector3.new(0, 3, 0))
local remote = game:GetService("ReplicatedStorage").ThrowSnowball
local function balls()
	local n = 0
	for _, c in workspace:GetChildren() do
		if c.Name == "Snowball" then n += 1 end
	end
	return n
end

remote.OnServerEvent:Fire(player, Vector3.new(0, 0, -1))
local thrown = workspace:FindFirstChild("Snowball")
check("valid throw spawns a server-owned snowball", thrown ~= nil and thrown:GetNetworkOwner() == nil)
check("server speed is applied", (thrown.AssemblyLinearVelocity - Vector3.new(0, 0, -90)).Magnitude < 1e-9)
check("spawned in front of the thrower", (thrown.Position - Vector3.new(0, 4.5, -3)).Magnitude < 1e-9)
__advance(1)
remote.OnServerEvent:Fire(player, Vector3.new(0, 0, -5000))
remote.OnServerEvent:Fire(player, Vector3.new(0 / 0, 0, 0))
remote.OnServerEvent:Fire(player, "fast")
check("oversized, NaN and wrong-type aims are rejected", balls() == 1)
__advance(1)
character.HumanoidRootPart.AssemblyLinearVelocity = Vector3.new(0, 0, -5000)
remote.OnServerEvent:Fire(player, Vector3.new(0, 0, -1))
local fast
for _, c in workspace:GetChildren() do
	if c.Name == "Snowball" and c ~= thrown then fast = c end
end
check("a faked character velocity is not inherited", fast ~= nil and (fast.AssemblyLinearVelocity - Vector3.new(0, 0, -90)).Magnitude < 1e-9)
character.HumanoidRootPart.AssemblyLinearVelocity = Vector3.zero
__advance(1)
remote.OnServerEvent:Fire(player, Vector3.new(1, 0, 0))
remote.OnServerEvent:Fire(player, Vector3.new(1, 0, 0))
check("cooldown limits the throw rate", balls() == 3)
__advance(7)
check("snowballs are cleaned up", balls() == 0)
```
