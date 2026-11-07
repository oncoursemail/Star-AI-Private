---
id: gb-world-combat-box-hitbox
category: combat-hitbox
topics: GetPartBoundsInBox, OverlapParams, melee hitbox, team check, server
source: original
---
# Request
I use a Touched event on an invisible hitbox part welded in front of the player for punches. It misses a lot and sometimes hits the same enemy 5 times in one punch. What should a server-side melee hitbox look like?

# Answer
Query the space once (or once per active frame) with `GetPartBoundsInBox` at a CFrame in front of the attacker's root, excluding the attacker. Collapse the returned parts to unique living humanoids, skip teammates, and remember who was already hit this swing so each target is hit once.

```lua
--!strict
-- ModuleScript: ServerScriptService.MeleeHitbox
local Players = game:GetService("Players")

export type HitboxSpec = { size: Vector3, offset: CFrame }

local MeleeHitbox = {}

function MeleeHitbox.query(attacker: Model, spec: HitboxSpec, alreadyHit: { [Humanoid]: boolean }): { Humanoid }
	local root = attacker:FindFirstChild("HumanoidRootPart")
	if root == nil or not root:IsA("BasePart") then
		return {}
	end
	local params = OverlapParams.new()
	params.FilterType = Enum.RaycastFilterType.Exclude
	params.FilterDescendantsInstances = { attacker }

	local attackerPlayer = Players:GetPlayerFromCharacter(attacker)
	local hits: { Humanoid } = {}
	for _, part in workspace:GetPartBoundsInBox(root.CFrame * spec.offset, spec.size, params) do
		local model = part:FindFirstAncestorOfClass("Model")
		local humanoid = if model then model:FindFirstChildOfClass("Humanoid") else nil
		if humanoid and humanoid.Health > 0 and not alreadyHit[humanoid] then
			local victimPlayer = Players:GetPlayerFromCharacter(model)
			local teammate = attackerPlayer ~= nil
				and victimPlayer ~= nil
				and attackerPlayer.Team ~= nil
				and attackerPlayer.Team == victimPlayer.Team
			if not teammate then
				alreadyHit[humanoid] = true
				table.insert(hits, humanoid)
			end
		end
	end
	return hits
end

return MeleeHitbox
```

Using it during the active frames of a punch:

```lua
--!strict
local MeleeHitbox = require(script.Parent:WaitForChild("MeleeHitbox"))

local PUNCH = { size = Vector3.new(4, 5, 4), offset = CFrame.new(0, 0, -3) }

local function punch(attacker: Model)
	local alreadyHit: { [Humanoid]: boolean } = {}
	for _ = 1, 4 do
		for _, humanoid in MeleeHitbox.query(attacker, PUNCH, alreadyHit) do
			humanoid:TakeDamage(12)
		end
		task.wait(0.05)
	end
end

return punch
```

- Spatial queries see everything currently overlapping, including targets that were already inside the box when the swing started, which Touched misses.
- A box is reduced to humanoids before anything else, so a target with 15 body parts in the box still counts once.
- Pass the same `alreadyHit` table for every query of one swing and a fresh table for the next swing.
- The offset is in the attacker's root space, so `CFrame.new(0, 0, -3)` is always in front of them.

# Test
```lua
local attackerPlayer = __makePlayer(41, "Puncher")
local attacker = __makeCharacter(attackerPlayer, Vector3.new(0, 3, 0))
local enemy = __buildRig(Vector3.new(0, 3, -4))
enemy.Parent = workspace
local behind = __buildRig(Vector3.new(0, 3, 8))
behind.Parent = workspace
local mate = __makePlayer(42, "Teammate")
local mateChar = __makeCharacter(mate, Vector3.new(1, 3, -3))
local red = Instance.new("Team")
red.Parent = game:GetService("Teams")
attackerPlayer.Team = red
mate.Team = red

local spec = { size = Vector3.new(4, 5, 4), offset = CFrame.new(0, 0, -3) }
local seen = {}
local hits = item.query(attacker, spec, seen)
check("enemy in front is hit once", #hits == 1 and hits[1] == enemy.Humanoid)
check("teammate and target behind are skipped", seen[mateChar.Humanoid] == nil and seen[behind.Humanoid] == nil)
check("same swing does not hit again", #item.query(attacker, spec, seen) == 0)
mate.Team = nil
check("non-teammate in range is hit", #item.query(attacker, spec, {}) == 2)
enemy.Humanoid.Health = 0
check("dead targets are ignored", #item.query(attacker, spec, { [mateChar.Humanoid] = true }) == 0)
```
