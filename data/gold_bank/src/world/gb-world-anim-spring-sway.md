---
id: gb-world-anim-spring-sway
category: animation
topics: spring, procedural animation, viewmodel sway, RenderStepped, CFrame
source: original
---
# Request
I want my first-person gun to lag behind and wobble a bit when I turn the camera, like weapon sway in shooters. Lerping the offset looks stiff. Can you write a spring I can use for this, and show how to drive the viewmodel with it?

# Answer
A damped spring gives overshoot and settle that a lerp cannot. Step it with small fixed substeps so a long frame (alt-tab, a hitch) cannot make it explode, then feed mouse movement into it as velocity kicks and turn its output into a rotation.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Spring
export type Spring = {
	position: number,
	velocity: number,
	target: number,
	stiffness: number,
	damping: number,
}

local SUBSTEP = 1 / 240
local MAX_FRAME = 0.1

local Spring = {}

function Spring.new(stiffness: number, damping: number, initial: number?): Spring
	local start = initial or 0
	return { position = start, velocity = 0, target = start, stiffness = stiffness, damping = damping }
end

function Spring.step(spring: Spring, dt: number): number
	local remaining = math.min(dt, MAX_FRAME)
	while remaining > 0 do
		local h = math.min(remaining, SUBSTEP)
		local acceleration = (spring.target - spring.position) * spring.stiffness - spring.velocity * spring.damping
		spring.velocity += acceleration * h
		spring.position += spring.velocity * h
		remaining -= h
	end
	return spring.position
end

function Spring.impulse(spring: Spring, amount: number)
	spring.velocity += amount
end

return Spring
```

Driving a viewmodel from a LocalScript:

```lua
--!strict
local RunService = game:GetService("RunService")
local UserInputService = game:GetService("UserInputService")
local Spring = require(game:GetService("ReplicatedStorage"):WaitForChild("Spring"))

local camera = workspace.CurrentCamera
local viewmodel = workspace:WaitForChild("Viewmodel")
local holdOffset = CFrame.new(0.6, -0.8, -1.4)

local pitch = Spring.new(180, 18)
local yaw = Spring.new(180, 18)

RunService.RenderStepped:Connect(function(dt: number)
	local delta = UserInputService:GetMouseDelta()
	Spring.impulse(yaw, -delta.X * 0.02)
	Spring.impulse(pitch, -delta.Y * 0.02)
	local sway = CFrame.Angles(math.rad(Spring.step(pitch, dt)), math.rad(Spring.step(yaw, dt)), 0)
	viewmodel:PivotTo(camera.CFrame * holdOffset * sway)
end)
```

- Damping near `2 * math.sqrt(stiffness)` settles without wobble; lower it for a looser, bouncier gun.
- Capping the frame at 0.1 s and substepping keeps the spring stable no matter how long a frame takes.
- Springs hold plain numbers, so the same module drives recoil kick, bob or FOV punches with one instance per value.

# Test
```lua
local s = item.new(100, 20)
s.target = 1
for _ = 1, 120 do
	item.step(s, 1 / 60)
end
check("settles on the target", math.abs(s.position - 1) < 0.01)

local loose = item.new(200, 4)
loose.target = 1
local peak = 0
for _ = 1, 120 do
	peak = math.max(peak, item.step(loose, 1 / 60))
end
check("low damping overshoots", peak > 1.1)

local hitch = item.new(500, 10)
hitch.target = 10
local after = item.step(hitch, 5)
check("a long frame stays finite and bounded", after == after and math.abs(after) < 50)

local kicked = item.new(100, 20)
item.impulse(kicked, 5)
item.step(kicked, 1 / 60)
check("impulse moves the spring", kicked.position > 0)
```
