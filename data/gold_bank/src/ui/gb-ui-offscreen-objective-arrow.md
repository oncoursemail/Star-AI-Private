---
id: gb-ui-offscreen-objective-arrow
category: ui-layout
topics: off-screen indicator, edge clamp, WorldToViewportPoint, objective marker, math
source: original
---
# Request
I show a marker over the current objective using `Camera:WorldToViewportPoint`. When the objective is off screen or behind the player, the marker flies off or appears mirrored in the wrong place. I want it to stick to the screen edge and point toward the objective. How do I do the math?

# Answer
If the point is on screen and in front, use it directly. Otherwise take the direction from the screen centre to the projected point (flipped when the point is behind the camera), and scale that direction until it touches a rectangle inset from the edges. The angle of the direction rotates the arrow.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.EdgeMarker
local EdgeMarker = {}

export type Placement = { position: Vector2, onScreen: boolean, angle: number }

function EdgeMarker.place(projected: Vector2, inFront: boolean, screen: Vector2, margin: number): Placement
	local px: number, py: number = projected.X, projected.Y
	local sw: number, sh: number = screen.X, screen.Y
	local inside = px >= margin and px <= sw - margin and py >= margin and py <= sh - margin
	if inFront and inside then
		return { position = Vector2.new(px, py), onScreen = true, angle = 0 }
	end
	local cx, cy = sw / 2, sh / 2
	local dx, dy = px - cx, py - cy
	if not inFront then
		dx, dy = -dx, -dy
	end
	if dx == 0 and dy == 0 then
		dy = 1
	end
	local halfW, halfH = cx - margin, cy - margin
	local scale = math.min(halfW / math.max(math.abs(dx), 1e-6), halfH / math.max(math.abs(dy), 1e-6))
	return {
		position = Vector2.new(cx + dx * scale, cy + dy * scale),
		onScreen = false,
		angle = math.deg(math.atan2(dy, dx)),
	}
end

return EdgeMarker
```

```lua
--!strict
-- LocalScript: drives the marker every frame
local RunService = game:GetService("RunService")
local EdgeMarker = require(game:GetService("ReplicatedStorage"):WaitForChild("EdgeMarker"))

local function track(marker: ImageLabel, target: BasePart)
	return RunService.RenderStepped:Connect(function()
		local camera = workspace.CurrentCamera
		local point, inFront = camera:WorldToViewportPoint(target.Position)
		local p = EdgeMarker.place(Vector2.new(point.X, point.Y), inFront, camera.ViewportSize, 48)
		marker.Position = UDim2.fromOffset(p.position.X, p.position.Y)
		marker.Rotation = if p.onScreen then 0 else p.angle + 90
	end)
end

return track
```

- `WorldToViewportPoint` mirrors points behind the camera, which is why the direction is flipped when `inFront` is false.
- The marker's ScreenGui should use `IgnoreGuiInset = true` so viewport coordinates match GUI coordinates.
- Set the marker's AnchorPoint to (0.5, 0.5) so it rotates around its centre; the +90 assumes the arrow art points up.

# Test
```lua
local screen = Vector2.new(1000, 600)
local p = item.place(Vector2.new(300, 200), true, screen, 40)
check("on-screen point used directly", p.onScreen and p.position.X == 300 and p.position.Y == 200)
p = item.place(Vector2.new(3000, 300), true, screen, 40)
check("far right clamps to right edge", not p.onScreen and math.abs(p.position.X - 960) < 1e-6 and math.abs(p.position.Y - 300) < 1e-6)
check("points right", math.abs(p.angle) < 1e-6)
p = item.place(Vector2.new(700, 300), false, screen, 40)
check("behind the camera flips to the other side", p.position.X < 500 and math.abs(p.position.X - 40) < 1e-6)
p = item.place(Vector2.new(500, -5000), true, screen, 40)
check("above clamps to top margin", math.abs(p.position.Y - 40) < 1e-6 and math.abs(p.angle + 90) < 1e-6)
```
