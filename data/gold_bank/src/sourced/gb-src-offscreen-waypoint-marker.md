---
id: gb-src-offscreen-waypoint-marker
category: ui-layout
topics: Camera, WorldToViewportPoint, ViewportSize, screen edge clamp, waypoint marker, RenderStepped
source: adapted
source_id: creator-docs
source_path: content/en-us/reference/engine/classes/Camera.yaml
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I want a quest marker icon that sits over the objective when it's on screen, and sticks to the edge of the screen pointing toward it when it's off screen or behind me. `WorldToScreenPoint` gives weird positions when the objective is behind the camera. How do I do this?

# Answer
Use `Camera:WorldToViewportPoint`, which returns the point in pixels plus its depth (`Z`, negative when behind the camera). If it is on screen, place the marker there; otherwise take the direction from the screen center (flipped when behind) and push it to the screen edge with a margin.

```lua
--!strict
local Marker = {}

function Marker.screenPosition(viewportPoint: Vector3, viewportSize: Vector2, margin: number): (Vector2, boolean)
	local center = viewportSize / 2
	local point = Vector2.new(viewportPoint.X, viewportPoint.Y)
	local inFront = viewportPoint.Z > 0
	local inside = point.X >= margin and point.X <= viewportSize.X - margin
		and point.Y >= margin and point.Y <= viewportSize.Y - margin
	if inFront and inside then
		return point, true
	end

	local direction = point - center
	if not inFront then
		direction = -direction
	end
	if direction.Magnitude < 1e-3 then
		direction = Vector2.new(0, 1)
	end
	local halfX = center.X - margin
	local halfY = center.Y - margin
	local scale = math.min(halfX / math.abs(direction.X + 1e-9), halfY / math.abs(direction.Y + 1e-9))
	return center + direction * scale, false
end

function Marker.bind(camera: Camera, icon: GuiObject, target: BasePart, margin: number): RBXScriptConnection
	local RunService = game:GetService("RunService")
	icon.AnchorPoint = Vector2.new(0.5, 0.5)
	return RunService.RenderStepped:Connect(function()
		local viewportPoint = camera:WorldToViewportPoint(target.Position)
		local position, onScreen = Marker.screenPosition(viewportPoint, camera.ViewportSize, margin)
		icon.Position = UDim2.fromOffset(position.X, position.Y)
		icon.Rotation = if onScreen then 0 else math.deg(math.atan2(position.Y - camera.ViewportSize.Y / 2, position.X - camera.ViewportSize.X / 2)) + 90
	end)
end

return Marker
```

- `WorldToViewportPoint` ignores the top bar inset, matching a ScreenGui with `IgnoreGuiInset = true`; use `WorldToScreenPoint` if your ScreenGui keeps the inset.
- Points behind the camera project mirrored, so the direction is flipped before clamping; otherwise the arrow points the wrong way.
- Scaling the direction by the smaller of the two edge ratios lands it exactly on the nearest screen edge.

# Test
```lua
local size = Vector2.new(1000, 600)
local p, on = item.screenPosition(Vector3.new(300, 200, 10), size, 40)
check("on-screen point used directly", on and p == Vector2.new(300, 200))
local right, onRight = item.screenPosition(Vector3.new(5000, 300, 10), size, 40)
check("off to the right clamps to right edge", not onRight and math.abs(right.X - 960) < 1e-3 and math.abs(right.Y - 300) < 1e-3)
local behind = item.screenPosition(Vector3.new(800, 300, -10), size, 40)
check("behind the camera flips to the other side", behind.X < 500)
local above = item.screenPosition(Vector3.new(500, -900, 10), size, 40)
check("above the screen clamps to top edge", math.abs(above.Y - 40) < 1e-3)
```
