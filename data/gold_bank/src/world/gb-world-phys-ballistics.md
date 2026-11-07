---
id: gb-world-phys-ballistics
category: physics
topics: projectile, ballistics, landing prediction, launch velocity, gravity
source: original
---
# Request
I'm making a mortar and a grenade throw. I need two things: show a marker where a grenade will land given its launch velocity, and for the mortar, compute the launch velocity that lands on a clicked target after a fixed flight time. Gravity is `workspace.Gravity`.

# Answer
Both come from the constant-acceleration equation `p(t) = p0 + v0*t + 0.5*g*t^2` with `g = (0, -Gravity, 0)`. Landing on a flat ground height means solving the quadratic in Y for the later root; aiming for a fixed flight time rearranges the same equation for `v0`.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Ballistics
local Ballistics = {}

function Ballistics.positionAt(origin: Vector3, velocity: Vector3, gravity: number, t: number): Vector3
	return origin + velocity * t + Vector3.new(0, -0.5 * gravity * t * t, 0)
end

-- Time when the projectile comes down to groundY, or nil if it never reaches it.
function Ballistics.timeToGround(originY: number, velocityY: number, gravity: number, groundY: number): number?
	local a = -0.5 * gravity
	local b = velocityY
	local c = originY - groundY
	local discriminant = b * b - 4 * a * c
	if discriminant < 0 then
		return nil
	end
	local root = math.sqrt(discriminant)
	local t = math.max((-b - root) / (2 * a), (-b + root) / (2 * a))
	return if t >= 0 then t else nil
end

function Ballistics.landingPoint(origin: Vector3, velocity: Vector3, gravity: number, groundY: number): Vector3?
	local t = Ballistics.timeToGround(origin.Y, velocity.Y, gravity, groundY)
	return if t then Ballistics.positionAt(origin, velocity, gravity, t) else nil
end

function Ballistics.launchVelocity(origin: Vector3, target: Vector3, gravity: number, flightTime: number): Vector3
	assert(flightTime > 0, "flightTime must be positive")
	return (target - origin) / flightTime + Vector3.new(0, 0.5 * gravity * flightTime, 0)
end

return Ballistics
```

Firing the mortar shell on the server with the computed velocity:

```lua
--!strict
local Ballistics = require(game:GetService("ReplicatedStorage"):WaitForChild("Ballistics"))

local function fireShell(template: BasePart, muzzle: Vector3, target: Vector3)
	local shell = template:Clone()
	shell.Position = muzzle
	shell.Parent = workspace
	shell:SetNetworkOwner(nil)
	shell.AssemblyLinearVelocity = Ballistics.launchVelocity(muzzle, target, workspace.Gravity, 2.5)
end

return fireShell
```

- The later root of the quadratic is the descent; the earlier one is the moment it would cross the same height on the way up (or a time in the past).
- A fixed flight time keeps the arc predictable for the target, and the velocity grows with distance, which suits mortars; for a fixed speed you would solve for the angle instead.
- Default Roblox physics applies no air drag, so these predictions match the simulation as long as nothing else acts on the part (collisions, constraints, or fluid forces if you enable them).

# Test
```lua
local g = 196.2
local t = item.timeToGround(0, 0, g, -19.62)
check("drop time from rest matches sqrt(2h/g)", t ~= nil and math.abs(t - math.sqrt(2 * 19.62 / g)) < 1e-9)
local land = item.landingPoint(Vector3.new(0, 5, 0), Vector3.new(20, 50, 0), g, 0)
local tLand = item.timeToGround(5, 50, g, 0)
check("landing point is on the ground", land ~= nil and math.abs(land.Y) < 1e-9 and math.abs(land.X - 20 * tLand) < 1e-9)
check("never reaches ground above the apex", item.landingPoint(Vector3.new(0, 0, 0), Vector3.new(0, 10, 0), g, 100) == nil)
local origin, target = Vector3.new(0, 2, 0), Vector3.new(80, 10, -30)
local v = item.launchVelocity(origin, target, g, 2.5)
check("launch velocity hits the target at the flight time", (item.positionAt(origin, v, g, 2.5) - target).Magnitude < 1e-9)
check("zero flight time rejected", not pcall(item.launchVelocity, origin, target, g, 0))
```
