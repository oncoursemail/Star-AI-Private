---
id: gb-src-smoothdamp-spring
category: engineering-algorithm
topics: critically damped spring, SmoothDamp, frame-rate independence, camera smoothing, impulse, generics
source: adapted
source_id: rbxutil
source_path: modules/spring/init.luau
source_commit: 31f9120fca021e3dec275b42bc7047d626962082
---
# Request
My camera offset and UI bars use `value = value + (target - value) * 0.1` every frame. It feels different at 30 and 144 FPS and overshoot/bounce is impossible to tune. I'd like a spring that reaches the target in about a given time, works for numbers and Vector3s, and supports a "kick" for recoil.

# Answer
Use a critically damped spring (the SmoothDamp formula): it keeps a velocity, reaches the target in roughly `smoothTime` seconds without overshooting, and uses `dt` so results match at any frame rate. An impulse just adds to the velocity.

```lua
--!strict
export type Spring<T> = {
	current: T,
	target: T,
	velocity: T,
	smoothTime: number,
}

local Spring = {}

function Spring.new<T>(initial: T, smoothTime: number): Spring<T>
	assert(smoothTime > 0, "smoothTime must be positive")
	return {
		current = initial,
		target = initial,
		velocity = (initial :: any) * 0,
		smoothTime = smoothTime,
	}
end

function Spring.update<T>(spring: Spring<T>, dt: number): T
	local omega = 2 / spring.smoothTime
	local x = omega * dt
	local decay = 1 / (1 + x + 0.48 * x * x + 0.235 * x * x * x)
	local current: any = spring.current
	local target: any = spring.target
	local velocity: any = spring.velocity
	local change = current - target
	local temp = (velocity + change * omega) * dt
	spring.velocity = (velocity - temp * omega) * decay
	spring.current = target + (change + temp) * decay
	return spring.current
end

function Spring.impulse<T>(spring: Spring<T>, velocity: T)
	local current: any = spring.velocity
	local kick: any = velocity
	spring.velocity = current + kick
end

return Spring
```

Recoil usage: `Spring.impulse(recoil, Vector3.new(0, 2, 0))` on fire, then each frame `camera.CFrame *= CFrame.new(Spring.update(recoil, dt))` with the target left at zero.

- The decay polynomial approximates `exp(-omega * dt)`, so a 30 FPS step and two 60 FPS steps land almost in the same place.
- Critical damping never overshoots a fixed target, but an impulse still gives a natural kick-and-settle motion.
- The generic `T` works for anything with `+`, `-` and `* number`: numbers, Vector2, Vector3 (use separate springs for rotation).

# Test
```lua
local s = item.new(0, 0.3)
s.target = 10
for _ = 1, 120 do
	item.update(s, 1 / 60)
end
check("reaches the target", math.abs(s.current - 10) < 0.01)
local a = item.new(0, 0.3)
a.target = 10
local b = item.new(0, 0.3)
b.target = 10
item.update(a, 1 / 30)
item.update(b, 1 / 60)
item.update(b, 1 / 60)
check("frame-rate independent within tolerance", math.abs(a.current - b.current) < 0.05)
local peak = 0
local c = item.new(0, 0.2)
c.target = 5
for _ = 1, 200 do
	peak = math.max(peak, item.update(c, 1 / 60))
end
check("no overshoot for a fixed target", peak <= 5 + 1e-6)
local v = item.new(Vector3.zero, 0.2)
item.impulse(v, Vector3.new(0, 20, 0))
item.update(v, 1 / 60)
check("impulse moves a Vector3 spring", v.current.Y > 0)
```
