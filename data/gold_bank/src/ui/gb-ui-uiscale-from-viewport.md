---
id: gb-ui-uiscale-from-viewport
category: ui-layout
topics: UIScale, ViewportSize, Camera, responsive, offset-based UI
source: original
---
# Request
My whole menu was designed in Offset at 1280x720 and redoing it in Scale would take days. Is there a way to make it shrink on phones and grow a bit on big monitors without rewriting every frame?

# Answer
Put one UIScale in the menu's root frame and set its `Scale` from the camera's ViewportSize compared with your design resolution, clamped so it never gets unreadably small or comically big. Recompute when the viewport changes (window resize, phone rotation) and when the current camera is replaced.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.ViewportScale
local ViewportScale = {}

local DESIGN = Vector2.new(1280, 720)

function ViewportScale.scaleFor(viewport: Vector2, minScale: number, maxScale: number): number
	local s = math.min(viewport.X / DESIGN.X, viewport.Y / DESIGN.Y)
	return math.clamp(s, minScale, maxScale)
end

function ViewportScale.attach(uiScale: UIScale, minScale: number?, maxScale: number?): () -> ()
	local lo, hi = minScale or 0.6, maxScale or 1.5
	local viewportConnection: RBXScriptConnection? = nil

	local function update()
		local camera = workspace.CurrentCamera
		if camera then
			uiScale.Scale = ViewportScale.scaleFor(camera.ViewportSize, lo, hi)
		end
	end

	local function watchCamera()
		if viewportConnection then
			viewportConnection:Disconnect()
			viewportConnection = nil
		end
		local camera = workspace.CurrentCamera
		if camera then
			viewportConnection = camera:GetPropertyChangedSignal("ViewportSize"):Connect(update)
		end
		update()
	end

	local cameraConnection = workspace:GetPropertyChangedSignal("CurrentCamera"):Connect(watchCamera)
	watchCamera()

	return function()
		cameraConnection:Disconnect()
		if viewportConnection then
			viewportConnection:Disconnect()
		end
	end
end

return ViewportScale
```

- `math.min` of both ratios fits the design inside the screen on both axes, so nothing is pushed off the edge in portrait or ultrawide.
- UIScale also scales the fixed TextSize of every label inside it, which converting sizes to Scale would not do.
- Anchor and position the root frame with Scale (for example centred) so it stays in place while its contents scale.

# Test
```lua
local camera = workspace.CurrentCamera
check("design resolution is 1", item.scaleFor(Vector2.new(1280, 720), 0.6, 1.5) == 1)
check("phone clamps to the minimum", item.scaleFor(Vector2.new(844, 390), 0.6, 1.5) == 0.6)
check("4K clamps to the maximum", item.scaleFor(Vector2.new(3840, 2160), 0.6, 1.5) == 1.5)
local uiScale = Instance.new("UIScale")
local detach = item.attach(uiScale)
check("applied on attach", uiScale.Scale == 1)
camera.ViewportSize = Vector2.new(1024, 576)
check("follows viewport changes", math.abs(uiScale.Scale - 0.8) < 1e-9)
detach()
camera.ViewportSize = Vector2.new(1280, 720)
check("detached scales stop updating", math.abs(uiScale.Scale - 0.8) < 1e-9)
```
