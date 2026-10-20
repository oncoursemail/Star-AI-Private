---
id: gb-world-combat-projectile-stepper
category: combat-hitbox
topics: projectile, hit registration, segment raycast, gravity, server simulation
source: original
---
# Request
My arrows are physical parts with a Touched event. Fast arrows pass straight through thin targets, and Touched sometimes fires on the shooter. I'd like arrows simulated on the server with proper hit detection. How do I do that without physics parts?

# Answer
Represent each arrow as data (position, velocity, age) and advance all of them every Heartbeat. Each step raycasts the exact segment the arrow travels that frame, so no speed can tunnel through a target, and the shooter's character is excluded from that arrow's ray. Visuals are left to clients.

```lua
--!strict
-- ModuleScript: ServerScriptService.ProjectileStepper
export type Projectile = {
	position: Vector3,
	velocity: Vector3,
	age: number,
	params: RaycastParams,
	onHit: (result: RaycastResult) -> (),
}
export type Stepper = {
	fire: (origin: Vector3, velocity: Vector3, shooter: Instance, onHit: (result: RaycastResult) -> ()) -> (),
	step: (dt: number) -> (),
	count: () -> number,
}

local ProjectileStepper = {}

function ProjectileStepper.new(gravity: number, maxAge: number): Stepper
	local live: { Projectile } = {}
	local acceleration = Vector3.new(0, -gravity, 0)

	local function step(dt: number)
		for index = #live, 1, -1 do
			local projectile = live[index]
			local displacement = projectile.velocity * dt + acceleration * (0.5 * dt * dt)
			local result = workspace:Raycast(projectile.position, displacement, projectile.params)
			if result then
				table.remove(live, index)
				projectile.onHit(result)
			else
				projectile.position += displacement
				projectile.velocity += acceleration * dt
				projectile.age += dt
				if projectile.age >= maxAge then
					table.remove(live, index)
				end
			end
		end
	end

	return {
		fire = function(origin: Vector3, velocity: Vector3, shooter: Instance, onHit: (result: RaycastResult) -> ())
			local params = RaycastParams.new()
			params.FilterType = Enum.RaycastFilterType.Exclude
			params.FilterDescendantsInstances = { shooter }
			table.insert(live, { position = origin, velocity = velocity, age = 0, params = params, onHit = onHit })
		end,
		step = step,
		count = function(): number
			return #live
		end,
	}
end

return ProjectileStepper
```

Running it on the server:

```lua
--!strict
local RunService = game:GetService("RunService")
local ProjectileStepper = require(script.Parent:WaitForChild("ProjectileStepper"))

local arrows = ProjectileStepper.new(workspace.Gravity, 4)
RunService.Heartbeat:Connect(arrows.step)

return arrows
```

- The displacement uses the exact constant-acceleration formula, so the server path matches the arc clients draw for the same launch velocity.
- Iterating backwards lets finished projectiles be removed in place without skipping the next one.
- `maxAge` bounds both memory and how far a missed shot can travel.
- Inside `onHit`, look up the Humanoid from `result.Instance` and send damage through your damage service; send `origin`/`velocity` to clients once at fire time so they can animate the arrow themselves.

# Test
```lua
local wall = Instance.new("Part")
wall.Anchored = true
wall.Size = Vector3.new(20, 20, 0.2)
wall.Position = Vector3.new(0, 5, -50)
wall.Parent = workspace
local shooter = __buildRig(Vector3.new(0, 3, 0))
shooter.Parent = workspace

local stepper = item.new(0, 2)
local hitAt = nil
stepper.fire(Vector3.new(0, 5, 0), Vector3.new(0, 0, -100), shooter, function(result)
	hitAt = result
end)
for _ = 1, 4 do
	stepper.step(0.1)
end
check("not hit before reaching the wall", hitAt == nil and stepper.count() == 1)
stepper.step(0.1)
stepper.step(0.1)
check("hits the wall at the right place", hitAt ~= nil and hitAt.Instance == wall and math.abs(hitAt.Position.Z + 49.9) < 1e-6)
check("projectile removed after the hit", stepper.count() == 0)

local fastHit = false
stepper.fire(Vector3.new(0, 5, 0), Vector3.new(0, 0, -2000), shooter, function()
	fastHit = true
end)
stepper.step(0.1)
check("very fast projectile does not tunnel through a thin wall", fastHit)

local selfHit = false
stepper.fire(Vector3.new(0, 3, 2), Vector3.new(0, 0, -50), shooter, function(result)
	selfHit = result.Instance:IsDescendantOf(shooter)
end)
stepper.step(0.1)
check("the shooter is never hit by their own arrow", not selfHit)
stepper.fire(Vector3.new(0, 5, 0), Vector3.new(0, 0, 50), shooter, function() end)
for _ = 1, 25 do
	stepper.step(0.1)
end
check("missed shots expire", stepper.count() == 0)
```
