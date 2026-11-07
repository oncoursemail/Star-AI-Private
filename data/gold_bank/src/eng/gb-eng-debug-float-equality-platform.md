---
id: gb-eng-debug-float-equality-platform
category: engineering-debugging
topics: floating point, equality, moving platform, overshoot, epsilon
source: original
---
# Request
My moving platform is supposed to stop at the target and reverse, but it just keeps going forever past the end. It reverses fine with some speeds and not others.

```lua
local target = pointB.Position
game:GetService("RunService").Heartbeat:Connect(function(dt)
	local dir = (target - platform.Position).Unit
	platform.Position += dir * speed * dt
	if platform.Position == target then
		target = (target == pointB.Position) and pointA.Position or pointB.Position
	end
end)
```

# Answer
Two problems: the platform moves `speed * dt` per frame, which almost never lands exactly on the target, so `==` on floating-point positions stays false; and once it overshoots, `.Unit` points back, so it jitters or drifts instead of stopping. Clamp each step to the remaining distance (so it lands exactly) and compare distances against a small epsilon instead of using `==`.

```lua
--!strict
-- ModuleScript: ServerScriptService.PingPongMover
export type Mover = {
	a: Vector3,
	b: Vector3,
	speed: number,
	position: Vector3,
	goingToB: boolean,
}

local EPSILON = 1e-3

local PingPongMover = {}

function PingPongMover.new(a: Vector3, b: Vector3, speed: number): Mover
	return { a = a, b = b, speed = speed, position = a, goingToB = true }
end

function PingPongMover.step(m: Mover, dt: number): Vector3
	local remaining = dt * m.speed
	-- loop so a large dt that passes the end continues back the other way instead of stopping early
	for _ = 1, 4 do
		local target = if m.goingToB then m.b else m.a
		local offset = target - m.position
		local distance = offset.Magnitude
		if distance <= remaining + EPSILON then
			m.position = target
			m.goingToB = not m.goingToB
			remaining -= distance
			if remaining <= EPSILON then
				break
			end
		else
			m.position += offset / distance * remaining
			break
		end
	end
	return m.position
end

return PingPongMover
```

- Server script: `local mover = PingPongMover.new(pointA.Position, pointB.Position, 10)` and in Heartbeat `platform.CFrame = CFrame.new(PingPongMover.step(mover, dt))`; setting CFrame does not carry riders along, so for players to ride it smoothly use an unanchored platform owned by the server (`SetNetworkOwner(nil)`) driven by a PrismaticConstraint servo or AlignPosition instead.
- Assigning `m.position = target` on arrival removes accumulated error, so the platform does not drift a little further every cycle.
- Never use `==` on computed Vector3/CFrame/number values; use `(a - b).Magnitude < eps` or `math.abs(x - y) < eps`. Exact `==` is fine only for values you assigned directly.

# Test
```lua
local m = item.new(Vector3.new(0, 0, 0), Vector3.new(10, 0, 0), 3)
for _ = 1, 200 do
	item.step(m, 1 / 60)
end
local maxX, minX = -math.huge, math.huge
local reversals = 0
local last = m.goingToB
for _ = 1, 2000 do
	local p = item.step(m, 1 / 60)
	maxX = math.max(maxX, p.X)
	minX = math.min(minX, p.X)
	if m.goingToB ~= last then
		reversals += 1
		last = m.goingToB
	end
end
check("never passes the ends", maxX <= 10 + 1e-9 and minX >= -1e-9)
check("keeps reversing", reversals >= 5)
local exact = item.new(Vector3.new(0, 0, 0), Vector3.new(1, 0, 0), 1)
item.step(exact, 0.9)
item.step(exact, 0.1005)
check("lands exactly on target", exact.position == Vector3.new(1, 0, 0) and exact.goingToB == false)
local big = item.new(Vector3.new(0, 0, 0), Vector3.new(4, 0, 0), 1)
item.step(big, 6)
check("big step bounces back", math.abs(big.position.X - 2) < 1e-9 and big.goingToB == false)
```
