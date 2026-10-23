The original code, unchanged.

```lua
-- Projectile: client-side paintball flight. Vectors are plain {x, y, z} tables so the server can share it.
local Projectile = {}
Projectile.__index = Projectile

Projectile.GRAVITY = -60
Projectile.MAX_RANGE = 300

local function length(v)
	return math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
end

function Projectile.new(origin, velocity)
	local self = setmetatable({}, Projectile)
	self.position = { x = origin.x, y = origin.y, z = origin.z }
	self.velocity = { x = velocity.x, y = velocity.y, z = velocity.z }
	self.travelled = 0
	self.alive = true
	return self
end

-- Advances the ball by dt seconds. Returns true while the ball is still flying.
function Projectile:step(dt)
	if not self.alive then
		return false
	end
	self.velocity.y += Projectile.GRAVITY
	local move = {
		x = self.velocity.x * dt,
		y = self.velocity.y * dt,
		z = self.velocity.z * dt,
	}
	self.position.x += move.x
	self.position.y += move.y
	self.position.z += move.z
	self.travelled += length(move)
	return true
end

function Projectile:speed()
	return length(self.velocity)
end

function Projectile:kill()
	self.alive = false
end

-- Simulates until the ball dies or `seconds` pass; returns the positions for a debug beam.
function Projectile:trace(seconds, dt)
	local points = {}
	local t = 0
	while t < seconds and self:step(dt) do
		table.insert(points, { x = self.position.x, y = self.position.y, z = self.position.z })
		t += dt
	end
	return points
end

return Projectile
```
