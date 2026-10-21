---
id: gb-world-combat-explosion-falloff
category: combat-hitbox
topics: explosion, area damage, distance falloff, line of sight, GetPartBoundsInRadius
source: original
---
# Request
I use `Instance.new("Explosion")` for rockets but it kills people behind walls and always deals full damage. I want damage that decreases with distance and is blocked by walls. How do I write my own explosion damage?

# Answer
Find characters with `GetPartBoundsInRadius`, reduce them to unique humanoids, then for each one cast a ray from the blast centre to its root: if anything other than that character is in the way, it is shielded. Damage falls off linearly from the centre to the edge. Keep a visual-only Explosion (`BlastPressure = 0`, `DestroyJointRadiusPercent = 0`) for the effect if you like the look.

```lua
--!strict
-- ModuleScript: ServerScriptService.BlastDamage
local BlastDamage = {}

function BlastDamage.amountAt(distance: number, radius: number, maxDamage: number, minDamage: number): number
	if distance >= radius then
		return 0
	end
	return maxDamage - (maxDamage - minDamage) * (distance / radius)
end

function BlastDamage.explode(center: Vector3, radius: number, maxDamage: number, minDamage: number, ignore: { Instance }): { [Humanoid]: number }
	local overlap = OverlapParams.new()
	overlap.FilterType = Enum.RaycastFilterType.Exclude
	overlap.FilterDescendantsInstances = ignore

	local dealt: { [Humanoid]: number } = {}
	for _, part in workspace:GetPartBoundsInRadius(center, radius, overlap) do
		local model = part:FindFirstAncestorOfClass("Model")
		local humanoid = if model then model:FindFirstChildOfClass("Humanoid") else nil
		local root = if model then model:FindFirstChild("HumanoidRootPart") else nil
		if model and humanoid and root and dealt[humanoid] == nil and humanoid.Health > 0 then
			local los = RaycastParams.new()
			los.FilterType = Enum.RaycastFilterType.Exclude
			los.FilterDescendantsInstances = { model, table.unpack(ignore) }
			local offset = root.Position - center
			local blocked = workspace:Raycast(center, offset, los) ~= nil
			local amount = if blocked then 0 else BlastDamage.amountAt(offset.Magnitude, radius, maxDamage, minDamage)
			dealt[humanoid] = amount
			if amount > 0 then
				humanoid:TakeDamage(amount)
			end
		end
	end
	return dealt
end

return BlastDamage
```

- Every humanoid is evaluated once (`dealt[humanoid]` is set even when shielded), so a character with many parts in range is not re-tested per part.
- The line-of-sight ray excludes the target itself and the ignore list (the rocket, the shooter if self-damage is off), so only real cover blocks it.
- Distance is measured to the root, which keeps damage stable no matter which limb is nearest; use the closest part instead if you want feet near the blast to count.
- Check from the blast point nudged slightly off the surface it hit (`result.Position + result.Normal * 0.5`), or the wall the rocket struck shields everyone.

# Test
```lua
check("full damage at the centre", item.amountAt(0, 20, 100, 20) == 100)
check("linear falloff", item.amountAt(10, 20, 100, 20) == 60)
check("nothing at the edge", item.amountAt(20, 20, 100, 20) == 0)

local near = __buildRig(Vector3.new(5, 3, 0))
near.Parent = workspace
local covered = __buildRig(Vector3.new(-10, 3, 0))
covered.Parent = workspace
local cover = Instance.new("Part")
cover.Anchored = true
cover.Size = Vector3.new(1, 10, 10)
cover.Position = Vector3.new(-5, 3, 0)
cover.Parent = workspace
local far = __buildRig(Vector3.new(0, 3, 40))
far.Parent = workspace

local dealt = item.explode(Vector3.new(0, 3, 0), 20, 100, 20, {})
check("nearby target damaged with falloff", dealt[near.Humanoid] == 80 and near.Humanoid.Health == 20)
check("target behind cover is shielded", dealt[covered.Humanoid] == 0 and covered.Humanoid.Health == 100)
check("target outside the radius untouched", dealt[far.Humanoid] == nil and far.Humanoid.Health == 100)
local again = item.explode(Vector3.new(0, 3, 0), 20, 100, 20, { near })
check("ignore list excludes characters", again[near.Humanoid] == nil)
```
