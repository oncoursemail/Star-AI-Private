---
id: gb-data-remote-unreliable-look-direction
category: remote-security
topics: UnreliableRemoteEvent, replication, rate limit, head look, cosmetic state
source: original
---
# Request
I want other players to see where each player's head is looking. I'm firing a normal RemoteEvent every frame with the camera direction and the server forwards it to everyone, and the game gets laggy with a full server. What's the right way to do this?

# Answer
This is cosmetic state that changes constantly, so send it over an `UnreliableRemoteEvent` (a dropped update is replaced by the next one), throttle it on the client, and have the server accept at most ~15 updates a second, sanitise the two angles, and forward them to everyone except the sender.

```lua
--!strict
-- Script: ServerScriptService.LookRelay
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local look = Instance.new("UnreliableRemoteEvent")
look.Name = "LookDirection"
look.Parent = ReplicatedStorage

local MIN_INTERVAL = 1 / 15
local lastAccepted: { [Player]: number } = {}

local function finite(n: unknown): boolean
	return type(n) == "number" and n == n and math.abs(n) ~= math.huge
end

local function onLook(player: Player, pitchArg: unknown, yawArg: unknown)
	if not finite(pitchArg) or not finite(yawArg) then
		return
	end
	local now = os.clock()
	local last = lastAccepted[player]
	if last and now - last < MIN_INTERVAL then
		return
	end
	lastAccepted[player] = now
	local pitch = math.clamp(pitchArg :: number, -80, 80)
	local yaw = (yawArg :: number) % 360
	for _, other in Players:GetPlayers() do
		if other ~= player then
			look:FireClient(other, player, pitch, yaw)
		end
	end
end

look.OnServerEvent:Connect(onLook)
Players.PlayerRemoving:Connect(function(player: Player)
	lastAccepted[player] = nil
end)
```

Client sender (only when the angle changed noticeably, at most 10 times a second):

```lua
--!strict
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local look = ReplicatedStorage:WaitForChild("LookDirection") :: UnreliableRemoteEvent
local camera = workspace.CurrentCamera

local SEND_INTERVAL = 0.1
local lastSent = 0
local lastPitch, lastYaw = 0, 0

RunService.Heartbeat:Connect(function()
	local now = os.clock()
	if now - lastSent < SEND_INTERVAL then
		return
	end
	local direction: Vector3 = camera.CFrame.LookVector
	local pitch = math.deg(math.asin(direction.Y))
	local yaw = math.deg(math.atan2(-direction.X, -direction.Z))
	if math.abs(pitch - lastPitch) > 2 or math.abs(yaw - lastYaw) > 2 then
		lastSent, lastPitch, lastYaw = now, pitch, yaw
		look:FireServer(pitch, yaw)
	end
end)
```

- Unreliable events can arrive out of order or not at all, so never send anything that must add up (damage, currency, inventory) this way.
- Two numbers are far below the unreliable payload limit (about 900 bytes); what made your version heavy is a reliable message every frame from every player, each forwarded to everyone.
- Receivers should smooth toward the latest angles instead of snapping, which hides dropped packets.

# Test
```lua
local remote = game:GetService("ReplicatedStorage"):WaitForChild("LookDirection")
local a = __makePlayer(1, "A")
local b = __makePlayer(2, "B")
local c = __makePlayer(3, "C")

remote.OnServerEvent:Fire(a, 30, 90)
local sentTo = {}
for _, entry in remote.__sent do
	sentTo[entry[1]] = entry
end
check("forwarded to the other players only", sentTo[b] ~= nil and sentTo[c] ~= nil and sentTo[a] == nil)
check("payload names the sender and angles", sentTo[b][2] == a and sentTo[b][3] == 30 and sentTo[b][4] == 90)

local count = #remote.__sent
remote.OnServerEvent:Fire(a, 31, 91)
check("updates faster than the limit are dropped", #remote.__sent == count)

__advance(0.1)
remote.OnServerEvent:Fire(a, 500, 725)
local last = remote.__sent[#remote.__sent]
check("angles are clamped and wrapped", last[3] == 80 and last[4] == 5)

__advance(0.1)
count = #remote.__sent
remote.OnServerEvent:Fire(a, 0 / 0, 10)
remote.OnServerEvent:Fire(a, math.huge, 10)
remote.OnServerEvent:Fire(a, "up", 10)
check("NaN, infinity and strings are rejected", #remote.__sent == count)
```
