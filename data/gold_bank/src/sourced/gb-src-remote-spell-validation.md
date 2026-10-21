---
id: gb-src-remote-spell-validation
category: remote-security
topics: RemoteEvent, OnServerEvent, NaN check, cooldown, range check, FireAllClients
source: adapted
source_id: creator-docs
source_path: content/en-us/scripting/security/client-server-boundary.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
My lightning spell works like this: the client fires `CastLightning` with a target position, and the server just does `castLightning:FireAllClients(position)` so everyone sees the strike. Exploiters are spamming it across the whole map. What should the server check?

# Answer
Treat the position as untrusted input: check its type, reject NaN and infinite components, enforce a per-player cooldown, check the player actually has the spell, and limit the distance from their character. Only then broadcast.

```lua
--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local COOLDOWN_SECONDS = 3
local MAX_RANGE = 100

local castLightning = ReplicatedStorage:WaitForChild("CastLightning") :: RemoteEvent
local lastCast: { [Player]: number } = {}

local function isFiniteVector(v: Vector3): boolean
	for _, n in { v.X, v.Y, v.Z } do
		if n ~= n or math.abs(n) == math.huge then
			return false
		end
	end
	return true
end

castLightning.OnServerEvent:Connect(function(player: Player, strikePosition: unknown)
	if typeof(strikePosition) ~= "Vector3" or not isFiniteVector(strikePosition) then
		return
	end
	local now = os.clock()
	if now - (lastCast[player] or -math.huge) < COOLDOWN_SECONDS then
		return
	end
	if not player:GetAttribute("HasLightningSpell") then
		return
	end
	local character = player.Character
	local root = if character then character:FindFirstChild("HumanoidRootPart") else nil
	if not root or not root:IsA("BasePart") then
		return
	end
	if (root.Position - strikePosition).Magnitude > MAX_RANGE then
		return
	end

	lastCast[player] = now
	castLightning:FireAllClients(player, strikePosition)
end)

Players.PlayerRemoving:Connect(function(player: Player)
	lastCast[player] = nil
end)
```

- `typeof(x) == "number"` is true for NaN, and NaN fails every comparison, so range checks alone let it through; `n ~= n` catches it.
- The cooldown is recorded only after every check passes, so rejected spam does not reset an honest player's timer.
- The permission comes from a server-set attribute; the client never says what spells it has.
- `PlayerRemoving` clears the cooldown table so it does not grow forever.

# Test
```lua
local remote = Instance.new("RemoteEvent")
remote.Name = "CastLightning"
remote.Parent = game:GetService("ReplicatedStorage")
```

```lua
local remote = game:GetService("ReplicatedStorage").CastLightning
local mage = __makePlayer(1, "Mage")
__makeCharacter(mage, Vector3.new(0, 3, 0))
mage:SetAttribute("HasLightningSpell", true)
local muggle = __makePlayer(2, "Muggle")
__makeCharacter(muggle, Vector3.new(0, 3, 0))

remote.OnServerEvent:Fire(mage, "not a vector")
remote.OnServerEvent:Fire(mage, Vector3.new(0 / 0, 0, 0))
check("bad types and NaN rejected", #remote.__sent == 0)
remote.OnServerEvent:Fire(mage, Vector3.new(500, 0, 0))
check("out of range rejected", #remote.__sent == 0)
remote.OnServerEvent:Fire(muggle, Vector3.new(10, 0, 0))
check("player without spell rejected", #remote.__sent == 0)
remote.OnServerEvent:Fire(mage, Vector3.new(10, 0, 0))
check("valid cast broadcast", #remote.__sent == 1 and remote.__sent[1][2] == mage)
remote.OnServerEvent:Fire(mage, Vector3.new(10, 0, 0))
check("cooldown blocks second cast", #remote.__sent == 1)
__advance(3.1)
remote.OnServerEvent:Fire(mage, Vector3.new(10, 0, 0))
check("allowed after cooldown", #remote.__sent == 2)
```
