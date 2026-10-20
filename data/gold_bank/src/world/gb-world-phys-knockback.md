---
id: gb-world-phys-knockback
category: physics
topics: knockback, LinearVelocity, network ownership, AssemblyLinearVelocity, characters
source: original
---
# Request
When my hammer hits someone I set `target.HumanoidRootPart.AssemblyLinearVelocity = direction * 80` on the server. It works on NPCs but players barely move, or snap back. Why, and how do I do knockback that works on both?

# Answer
Player characters are simulated by their own client (it owns the assembly), so a velocity the server writes is immediately overwritten by the owner. A short-lived `LinearVelocity` constraint created on the server does replicate and is obeyed by whoever simulates the character, so the same code works for players and NPCs. The push direction is computed from attacker to target, flattened, with an upward component.

```lua
--!strict
-- ModuleScript: ServerScriptService.Knockback
local Debris = game:GetService("Debris")

local Knockback = {}

function Knockback.velocity(from: Vector3, to: Vector3, horizontalSpeed: number, upSpeed: number, fallback: Vector3): Vector3
	local flat = Vector3.new(to.X - from.X, 0, to.Z - from.Z)
	local direction = if flat.Magnitude > 1e-3 then flat.Unit else Vector3.new(fallback.X, 0, fallback.Z).Unit
	return direction * horizontalSpeed + Vector3.new(0, upSpeed, 0)
end

function Knockback.apply(targetRoot: BasePart, velocity: Vector3, duration: number): LinearVelocity
	local old = targetRoot:FindFirstChild("KnockbackVelocity")
	if old then
		old:Destroy()
	end
	local attachment = targetRoot:FindFirstChild("RootAttachment") or Instance.new("Attachment")
	attachment.Parent = targetRoot

	local push = Instance.new("LinearVelocity")
	push.Name = "KnockbackVelocity"
	push.Attachment0 = attachment
	push.RelativeTo = Enum.ActuatorRelativeTo.World
	push.VelocityConstraintMode = Enum.VelocityConstraintMode.Vector
	push.VectorVelocity = velocity
	push.MaxForce = targetRoot.AssemblyMass * 4000
	push.Parent = targetRoot
	Debris:AddItem(push, duration)
	return push
end

return Knockback
```

From the hit handler: `Knockback.apply(targetRoot, Knockback.velocity(attackerRoot.Position, targetRoot.Position, 60, 25, attackerRoot.CFrame.LookVector), 0.2)`.

- The fallback direction (the attacker's facing) covers attacker and target standing at the same spot, where `Unit` of a zero vector would be NaN.
- A new hit replaces the previous push instead of stacking two constraints fighting each other.
- `MaxForce` scales with the assembly's mass, so heavy bosses and light players react to the same speed instead of the same force.
- Keep the duration short (0.15-0.3 s); after the constraint is removed, normal physics and the Humanoid take over and the target lands naturally.

# Test
```lua
local v = item.velocity(Vector3.new(0, 3, 0), Vector3.new(10, 5, 0), 60, 25, Vector3.new(0, 0, -1))
check("push points away from the attacker, flattened, with lift", (v - Vector3.new(60, 25, 0)).Magnitude < 1e-9)
local same = item.velocity(Vector3.new(0, 3, 0), Vector3.new(0, 3, 0), 60, 0, Vector3.new(0, 0, -1))
check("same position falls back to the facing direction", (same - Vector3.new(0, 0, -60)).Magnitude < 1e-9)

local rig = __buildRig(Vector3.new(5, 3, 0))
rig.Parent = workspace
local root = rig.HumanoidRootPart
root.AssemblyMass = 10
local push = item.apply(root, v, 0.2)
check("linear velocity configured on the root", push.Parent == root and push.VectorVelocity == v and push.Attachment0.Parent == root)
check("force scales with mass", push.MaxForce == 40000)
item.apply(root, v, 0.2)
local count = 0
for _, c in root:GetChildren() do
	if c.Name == "KnockbackVelocity" then count += 1 end
end
check("a second hit replaces the first push", count == 1)
__advance(0.3)
check("push removed after its duration", root:FindFirstChild("KnockbackVelocity") == nil)
```
