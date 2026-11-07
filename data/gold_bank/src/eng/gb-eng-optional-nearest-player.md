---
id: gb-eng-optional-nearest-player
category: luau-typing
topics: optional types, nil handling, refinement, nearest player, strict mode
source: original
---
# Request
Strict mode complains "Value of type 'Model?' could be nil" all over my NPC script when I look up a player's character and root part. I don't want to sprinkle `::` casts everywhere. What is the clean way to handle optionals? Example: find the nearest player within a range of a point.

# Answer
Narrow optionals once at the boundary: a small helper returns `BasePart?`, callers early-`continue` or early-return on nil, and after that check the analyzer treats the value as non-nil. The final result is itself optional so the caller must handle "nobody in range".

```lua
--!strict
-- ModuleScript: ServerScriptService.Targeting
local Players = game:GetService("Players")

local Targeting = {}

local function rootOf(player: Player): BasePart?
	local character = player.Character
	if character == nil then
		return nil
	end
	local humanoid = character:FindFirstChildOfClass("Humanoid")
	if humanoid == nil or humanoid.Health <= 0 then
		return nil
	end
	local root = character:FindFirstChild("HumanoidRootPart")
	if root and root:IsA("BasePart") then
		return root
	end
	return nil
end

function Targeting.nearestPlayer(origin: Vector3, maxRange: number): (Player?, number)
	local best: Player? = nil
	local bestDistance = maxRange
	for _, player in Players:GetPlayers() do
		local root = rootOf(player)
		if root == nil then
			continue
		end
		local distance = (root.Position - origin).Magnitude
		if distance <= bestDistance then
			best, bestDistance = player, distance
		end
	end
	return best, bestDistance
end

return Targeting
```

- `root and root:IsA("BasePart")` both removes nil and refines the Instance to a BasePart, so `.Position` needs no cast.
- Casting with `::` only silences the analyzer and does nothing at runtime; when the character is mid-respawn the next `.Position` read still errors. Refinement handles that case.
- Caller pattern: `local target = Targeting.nearestPlayer(npcPos, 60); if target then ... end`. Dead players are skipped so NPCs do not chase a corpse.

# Test
```lua
local near = __makePlayer(1, "Near")
local far = __makePlayer(2, "Far")
local nochar = __makePlayer(3, "NoChar")
__makeCharacter(near, Vector3.new(10, 3, 0))
__makeCharacter(far, Vector3.new(40, 3, 0))
local p, d = item.nearestPlayer(Vector3.new(0, 3, 0), 100)
check("picks nearest", p == near and math.abs(d - 10) < 1e-6)
check("nobody in short range", item.nearestPlayer(Vector3.new(0, 3, 0), 5) == nil)
near.Character:FindFirstChildOfClass("Humanoid").Health = 0
check("dead player skipped", item.nearestPlayer(Vector3.new(0, 3, 0), 100) == far)
check("player without character ignored", nochar.Character == nil)
```
