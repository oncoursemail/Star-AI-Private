---
id: gb-src-cframe-mount-and-aim
category: rig-prop-alignment
topics: CFrame, ToWorldSpace, CFrame.lookAt, Lerp, fromEulerAnglesXYZ, relative offset
source: adapted
source_id: creator-docs
source_path: content/en-us/workspace/cframes.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I have a turret: a base part that can be placed at any rotation, and a barrel that should sit 2 studs above the base (following its rotation) and point at the nearest enemy. When I set `barrel.Position = base.Position + Vector3.new(0, 2, 0)` it ignores the base's tilt. How do I do this with CFrames, and smoothly turn instead of snapping?

# Answer
Offsets that should follow an object's rotation belong in its local space: `base.CFrame:ToWorldSpace(CFrame.new(0, 2, 0))`. For aiming, build `CFrame.lookAt(mountPosition, target)` and blend toward it each frame with `Lerp`.

```lua
--!strict
local Turret = {}

local MOUNT_OFFSET = CFrame.new(0, 2, 0)

function Turret.mountCFrame(base: BasePart): CFrame
	return base.CFrame:ToWorldSpace(MOUNT_OFFSET)
end

function Turret.aimCFrame(base: BasePart, target: Vector3): CFrame
	local mount = Turret.mountCFrame(base)
	if (target - mount.Position).Magnitude < 1e-3 then
		return mount
	end
	return CFrame.lookAt(mount.Position, target, base.CFrame.UpVector)
end

function Turret.step(barrel: BasePart, base: BasePart, target: Vector3, dt: number, turnRate: number)
	local goal = Turret.aimCFrame(base, target)
	local alpha = 1 - math.exp(-turnRate * dt)
	barrel.CFrame = barrel.CFrame:Lerp(goal, alpha)
end

function Turret.tiltBarrelUp(barrel: BasePart, degrees: number)
	barrel.CFrame = barrel.CFrame:ToWorldSpace(CFrame.fromEulerAnglesXYZ(math.rad(degrees), 0, 0))
end

return Turret
```

Call `Turret.step(barrel, base, enemyRoot.Position, dt, 8)` from `RunService.Heartbeat`.

- `ToWorldSpace` applies the offset in the base's own axes, so a tilted base keeps the barrel on its top face.
- `CFrame.lookAt` points the front (-Z) face at the target; passing the base's up vector keeps the barrel from rolling.
- `1 - exp(-rate * dt)` makes the turn speed independent of frame rate, unlike a fixed Lerp alpha.
- Anchor the barrel, or weld it and rotate a Motor6D instead, so physics does not fight the CFrame writes.

# Test
```lua
local base = Instance.new("Part")
base.CFrame = CFrame.new(10, 0, 0)
local barrel = Instance.new("Part")
barrel.CFrame = CFrame.new(0, 0, 0)
local mount = item.mountCFrame(base)
check("mount is 2 studs above base", (mount.Position - Vector3.new(10, 2, 0)).Magnitude < 1e-4)
local aim = item.aimCFrame(base, Vector3.new(10, 2, -20))
check("aim looks along -Z toward target", (aim.LookVector - Vector3.new(0, 0, -1)).Magnitude < 1e-4)
check("degenerate target returns mount", item.aimCFrame(base, Vector3.new(10, 2, 0)) == mount)
item.step(barrel, base, Vector3.new(10, 2, -20), 1 / 60, 8)
local partway = (barrel.Position - aim.Position).Magnitude
check("one step moves partway", partway > 0.1 and partway < (Vector3.zero - aim.Position).Magnitude)
for _ = 1, 600 do
	item.step(barrel, base, Vector3.new(10, 2, -20), 1 / 60, 8)
end
check("converges on the aim", (barrel.Position - aim.Position).Magnitude < 1e-3)
```
