---
id: gb-world-phys-buoyancy
category: physics
topics: buoyancy, VectorForce, submerged fraction, damping, floating crates
source: original
---
# Request
I have a water plane made of a transparent part (not terrain water) and I want crates to float on it and bob a little instead of sinking or shooting up. How would I do buoyancy with constraints?

# Answer
Apply an upward `VectorForce` proportional to how much of the crate is under the water line (Archimedes), plus a damping term against vertical velocity so it settles instead of bouncing forever. Choosing a buoyancy factor above 1 at full submersion makes the crate float partly above the surface.

```lua
--!strict
-- ModuleScript: ServerScriptService.Buoyancy
local RunService = game:GetService("RunService")

local Buoyancy = {}

function Buoyancy.submergedFraction(centerY: number, height: number, waterLevel: number): number
	local bottom = centerY - height / 2
	return math.clamp((waterLevel - bottom) / height, 0, 1)
end

-- Upward force in world space: weight * floatiness * submerged fraction, minus vertical damping.
function Buoyancy.force(mass: number, gravity: number, fraction: number, floatiness: number, verticalVelocity: number, damping: number): number
	if fraction <= 0 then
		return 0
	end
	return mass * gravity * floatiness * fraction - verticalVelocity * damping * mass * fraction
end

function Buoyancy.attach(part: BasePart, waterLevel: number, floatiness: number): () -> ()
	local attachment = Instance.new("Attachment")
	attachment.Parent = part
	local vectorForce = Instance.new("VectorForce")
	vectorForce.Attachment0 = attachment
	vectorForce.RelativeTo = Enum.ActuatorRelativeTo.World
	vectorForce.ApplyAtCenterOfMass = true
	vectorForce.Force = Vector3.zero
	vectorForce.Parent = part

	local connection = RunService.Heartbeat:Connect(function()
		local fraction = Buoyancy.submergedFraction(part.Position.Y, part.Size.Y, waterLevel)
		local up = Buoyancy.force(part.AssemblyMass, workspace.Gravity, fraction, floatiness, part.AssemblyLinearVelocity.Y, 2)
		vectorForce.Force = Vector3.new(0, up, 0)
	end)

	return function()
		connection:Disconnect()
		vectorForce:Destroy()
		attachment:Destroy()
	end
end

return Buoyancy
```

Usage: `Buoyancy.attach(crate, waterPart.Position.Y + waterPart.Size.Y / 2, 1.6)`.

- With floatiness 1.6, the crate is in balance when 1 / 1.6 (about 62%) of it is submerged, so it rides visibly above the surface.
- Damping scales with the submerged fraction, so a crate in the air falls freely and only slows once it hits the water.
- Use `AssemblyMass`, not the part's own mass, so crates welded to other parts get enough lift for the whole assembly.
- Run it wherever the crate is simulated; for crates players push around, ownership may move to a client, in which case the same code belongs in a client script for those parts.

# Test
```lua
check("fully above water", item.submergedFraction(10, 2, 5) == 0)
check("fully submerged", item.submergedFraction(0, 2, 5) == 1)
check("half submerged", item.submergedFraction(5, 2, 5) == 0.5)
check("no force out of the water", item.force(10, 196.2, 0, 1.6, -30, 2) == 0)
local equilibrium = 1 / 1.6
check("force balances weight at the float line", math.abs(item.force(10, 196.2, equilibrium, 1.6, 0, 2) - 10 * 196.2) < 1e-9)
check("damping opposes rising", item.force(10, 196.2, 1, 1.6, 5, 2) < item.force(10, 196.2, 1, 1.6, 0, 2))

workspace.Gravity = 196.2
local crate = Instance.new("Part")
crate.Size = Vector3.new(2, 2, 2)
crate.Position = Vector3.new(0, 4, 0)
crate.AssemblyMass = 5
crate.Parent = workspace
local detach = item.attach(crate, 5, 1.6)
__frames(1)
local vf = crate:FindFirstChildOfClass("VectorForce")
check("force updated from the submerged fraction", vf ~= nil and math.abs(vf.Force.Y - 5 * 196.2 * 1.6) < 1e-6)
detach()
check("detach removes the force", crate:FindFirstChildOfClass("VectorForce") == nil)
```
