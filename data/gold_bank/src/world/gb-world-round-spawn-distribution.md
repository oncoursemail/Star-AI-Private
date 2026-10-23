---
id: gb-world-round-spawn-distribution
category: round-systems
topics: round start teleport, spawn pads, PivotTo, stacking, shuffle
source: original
---
# Request
At round start I teleport everyone with `character.HumanoidRootPart.CFrame = spawn.CFrame` using a random spawn each. Players sometimes land on the same pad and get stuck inside each other, and dead or loading players cause errors. How should I distribute them?

# Answer
Shuffle the spawn pads once, give each player the next pad in order, and only wrap around when there are more players than pads, in which case later players get a sideways offset so nobody overlaps. Skip players without a living character, and move whole characters with `PivotTo` slightly above the pad.

```lua
--!strict
-- ModuleScript: ServerScriptService.RoundSpawner
local RoundSpawner = {}

function RoundSpawner.teleport(players: { Player }, pads: { BasePart }, random: Random): { [Player]: BasePart }
	assert(#pads > 0, "need at least one spawn pad")
	local order = table.clone(pads)
	random:Shuffle(order)

	local assigned: { [Player]: BasePart } = {}
	local index = 0
	for _, player in players do
		local character = player.Character
		local humanoid = if character then character:FindFirstChildOfClass("Humanoid") else nil
		if character and humanoid and humanoid.Health > 0 then
			local pad = order[index % #order + 1]
			local lap = index // #order
			-- Players beyond the pad count stand in a ring around the pad instead of on top of each other.
			local offset = if lap == 0 then Vector3.zero else CFrame.Angles(0, lap * 2.4, 0):VectorToWorldSpace(Vector3.new(0, 0, -4))
			character:PivotTo(pad.CFrame + offset + Vector3.new(0, pad.Size.Y / 2 + 3, 0))
			assigned[player] = pad
			index += 1
		end
	end
	return assigned
end

return RoundSpawner
```

Usage at round start: `RoundSpawner.teleport(Players:GetPlayers(), maps.spawnPoints(), Random.new())`.

- `PivotTo` moves the whole character model by its pivot, so the code does not depend on a particular part existing; skipping characters without a living Humanoid is what removes the errors.
- A shuffled list hands out every pad once before any repeats, which plain `math.random` per player does not guarantee.
- Spawning 3 studs above the pad top lets the Humanoid settle onto the pad instead of clipping into it.
- Players who are dead or still loading are skipped and should be handled by your join/respawn logic (spectate or spawn in the lobby).

# Test
```lua
local pads = {}
for i = 1, 3 do
	local pad = Instance.new("Part")
	pad.Size = Vector3.new(6, 1, 6)
	pad.Position = Vector3.new(i * 20, 0, 0)
	pad.Parent = workspace
	pads[i] = pad
end
local players = {}
for i = 1, 5 do
	players[i] = __makePlayer(80 + i, "S" .. i)
	__makeCharacter(players[i], Vector3.new(0, 50, 0))
end
local dead = __makePlayer(90, "Dead")
__makeCharacter(dead).Humanoid.Health = 0
local loading = __makePlayer(91, "Loading")
table.insert(players, dead)
table.insert(players, loading)

local assigned = item.teleport(players, pads, Random.new(3))
local used = {}
for i = 1, 3 do
	used[assigned[players[i]]] = true
end
check("first three players get three different pads", used[pads[1]] and used[pads[2]] and used[pads[3]])
check("dead and loading players are skipped", assigned[dead] == nil and assigned[loading] == nil)
local root1 = players[1].Character.HumanoidRootPart.Position
local pad1 = assigned[players[1]]
check("placed above their pad", math.abs(root1.Y - 3.5) < 1e-6 and math.abs(root1.X - pad1.Position.X) < 1e-6)
local p4 = players[4].Character.HumanoidRootPart.Position
local sharing = nil
for i = 1, 3 do
	if assigned[players[i]] == assigned[players[4]] then sharing = players[i] end
end
check("extra players do not stack on the same spot", sharing ~= nil and (sharing.Character.HumanoidRootPart.Position - p4).Magnitude > 3)
check("no pads errors", not pcall(item.teleport, players, {}, Random.new(1)))
```
