---
id: gb-eng-fixed-timestep-accumulator
category: engineering-algorithm
topics: fixed timestep, accumulator, Heartbeat, determinism, simulation
source: original
---
# Request
My custom projectile/ball simulation runs in Heartbeat with `dt`, and the results differ between a 60 FPS and a 240 FPS client and when the server lags. How do I run game logic at a fixed rate regardless of frame rate?

# Answer
Use an accumulator: add each frame's `dt`, run the simulation in fixed steps while enough time is banked, and keep the remainder for next frame. Cap the steps per frame so a long hitch cannot cause a spiral of catch-up work, and expose the leftover fraction for render interpolation.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.FixedStep
export type FixedStep = {
	step: number,
	maxSteps: number,
	accumulator: number,
	ticks: number,
}

local FixedStep = {}

function FixedStep.new(hz: number, maxSteps: number?): FixedStep
	assert(hz > 0, "rate must be positive")
	return { step = 1 / hz, maxSteps = maxSteps or 5, accumulator = 0, ticks = 0 }
end

-- Returns the interpolation alpha in [0, 1) between the last two simulated states.
function FixedStep.advance(self: FixedStep, dt: number, simulate: (step: number, tick: number) -> ()): number
	self.accumulator += math.max(dt, 0)
	local steps = 0
	while self.accumulator >= self.step and steps < self.maxSteps do
		self.accumulator -= self.step
		self.ticks += 1
		steps += 1
		simulate(self.step, self.ticks)
	end
	if steps == self.maxSteps and self.accumulator >= self.step then
		-- too far behind: drop the backlog instead of trying to catch up forever
		self.accumulator %= self.step
	end
	return self.accumulator / self.step
end

return FixedStep
```

```lua
--!strict
-- LocalScript usage: a ball simulated at 60 Hz, rendered every frame
local RunService = game:GetService("RunService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local FixedStep = require(ReplicatedStorage.FixedStep)

local ball = workspace:WaitForChild("Ball") :: BasePart
local clock = FixedStep.new(60)
local gravity = Vector3.new(0, -workspace.Gravity, 0)
local position, velocity = ball.Position, Vector3.new(20, 40, 0)
local previous = position

RunService.Heartbeat:Connect(function(dt: number)
	local alpha = FixedStep.advance(clock, dt, function(step: number)
		previous = position
		velocity += gravity * step
		position += velocity * step
	end)
	ball.Position = previous:Lerp(position, alpha)
end)
```

- Every machine runs exactly the same sequence of 1/60 s steps, so the trajectory matches across frame rates.
- `maxSteps` bounds the work per frame; after a long freeze the simulation slows down briefly instead of locking up while running hundreds of steps.
- Rendering `previous:Lerp(position, alpha)` removes the stutter you would see at 144 Hz when some frames run zero steps and others run one.

# Test
```lua
local clock = item.new(60)
local ticks = 0
for _ = 1, 240 do
	item.advance(clock, 1 / 240, function()
		ticks += 1
	end)
end
check("240 fps frames give 60 ticks per second", ticks == 60 or ticks == 59)
local slow = item.new(60)
local slowTicks = 0
for _ = 1, 30 do
	item.advance(slow, 1 / 30, function()
		slowTicks += 1
	end)
end
check("30 fps frames give 60 ticks per second", slowTicks == 60 or slowTicks == 59)
local hitch = item.new(60, 5)
local hitchTicks = 0
local alpha = item.advance(hitch, 3, function()
	hitchTicks += 1
end)
check("hitch capped at max steps", hitchTicks == 5)
check("backlog dropped and alpha in range", hitch.accumulator < hitch.step and alpha >= 0 and alpha < 1)
check("negative dt ignored", item.advance(item.new(60), -1, function() end) == 0)
```
