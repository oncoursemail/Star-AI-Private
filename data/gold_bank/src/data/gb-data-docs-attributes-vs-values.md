---
id: gb-data-docs-attributes-vs-values
category: docs-question
topics: attributes, ValueObjects, replication, state, ObjectValue
source: original
---
# Request
For replicated player state like "IsStunned", "Level" or "CurrentTarget", should I use attributes or IntValue/BoolValue/ObjectValue objects? What's the difference in practice?

# Answer
Both replicate from server to client and both fire change events. Attributes are lighter (no extra Instances), support more types (numbers, strings, booleans, Vector3, CFrame, Color3, UDim2 and more) and are the default choice today. Use value objects where something needs an Instance: `leaderstats` requires them, and attributes cannot hold Instance references, so a target pointer is an `ObjectValue`.

```lua
--!strict
-- Server: player state as attributes, plus the two cases that need value objects.
local Players = game:GetService("Players")

local function setup(player: Player)
	player:SetAttribute("Level", 1)
	player:SetAttribute("IsStunned", false)

	local stats = Instance.new("Folder")
	stats.Name = "leaderstats" -- the player list only reads value objects here
	local coins = Instance.new("IntValue")
	coins.Name = "Coins"
	coins.Parent = stats
	stats.Parent = player

	local target = Instance.new("ObjectValue") -- attributes cannot reference Instances
	target.Name = "CurrentTarget"
	target.Parent = player
end

local stunEnds: { [Player]: number } = {}

local function stun(player: Player, seconds: number)
	local endsAt = os.clock() + seconds
	if endsAt <= (stunEnds[player] or 0) then
		return
	end
	stunEnds[player] = endsAt
	player:SetAttribute("IsStunned", true)
	task.delay(seconds, function()
		-- a longer stun applied meanwhile moved the end time; only the latest one clears the flag
		if stunEnds[player] == endsAt then
			stunEnds[player] = nil
			if player.Parent then
				player:SetAttribute("IsStunned", false)
			end
		end
	end)
end

Players.PlayerAdded:Connect(setup)
for _, player in Players:GetPlayers() do
	setup(player)
end

return { setup = setup, stun = stun }
```

On the client, `player:GetAttributeChangedSignal("IsStunned"):Connect(...)` updates the UI.

- Neither replicates client to server: a client setting an attribute or a value only changes its own copy, so the server keeps ownership of both.
- Attribute names are limited to letters, numbers and underscores, and setting the same value again does not fire the changed signal.
- An `ObjectValue` pointing at a part the client cannot see (outside its streaming radius) reads as `nil` there until the part streams in.

# Test
```lua
local p = __makePlayer(1, "Fighter")
check("attributes hold simple state", p:GetAttribute("Level") == 1 and p:GetAttribute("IsStunned") == false)
check("leaderstats uses value objects", __leaderstat(p, "Coins") == 0)
local enemy = Instance.new("Model")
p.CurrentTarget.Value = enemy
check("instance references live in an ObjectValue", p.CurrentTarget.Value == enemy)
check("attributes refuse instances", not pcall(function()
	p:SetAttribute("Target", enemy)
end))
local fired = 0
p:GetAttributeChangedSignal("IsStunned"):Connect(function()
	fired += 1
end)
item.stun(p, 2)
check("stun sets the flag and fires the signal", p:GetAttribute("IsStunned") == true and fired == 1)
__advance(2.1)
check("stun wears off", p:GetAttribute("IsStunned") == false and fired == 2)

item.stun(p, 2)
__advance(1)
item.stun(p, 5)
__advance(1.5)
check("a later, longer stun outlasts the first one's end", p:GetAttribute("IsStunned") == true)
item.stun(p, 1)
__advance(4)
check("a shorter stun cannot cut a longer one", p:GetAttribute("IsStunned") == false and fired == 4)
```
