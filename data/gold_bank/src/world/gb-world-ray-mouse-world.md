---
id: gb-world-ray-mouse-world
category: world-raycast
topics: mouse ray, ViewportPointToRay, camera, world position, client targeting
source: original
---
# Request
I'm using `mouse.Hit` for aiming but it hits my own character, invisible parts and my placement preview, and when I aim at the sky it gives a weird far point. How do I get the world point under the cursor with control over what it ignores?

# Answer
Build the ray yourself from the camera with `ViewportPointToRay`, cast it with your own RaycastParams, and when it hits nothing return a point at a fixed distance along the ray so aiming at the sky still gives a sensible direction. The casting part is a plain function, so it can be reused for touch input or a gamepad crosshair.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.CursorRay
local UserInputService = game:GetService("UserInputService")

export type Target = { position: Vector3, instance: BasePart?, normal: Vector3? }

local CursorRay = {}

function CursorRay.cast(origin: Vector3, direction: Vector3, maxDistance: number, params: RaycastParams): Target
	local unit = direction.Unit
	local result = workspace:Raycast(origin, unit * maxDistance, params)
	if result then
		return { position = result.Position, instance = result.Instance, normal = result.Normal }
	end
	return { position = origin + unit * maxDistance, instance = nil, normal = nil }
end

function CursorRay.fromScreen(camera: Camera, screenX: number, screenY: number, maxDistance: number, params: RaycastParams): Target
	local ray = camera:ViewportPointToRay(screenX, screenY)
	return CursorRay.cast(ray.Origin, ray.Direction, maxDistance, params)
end

function CursorRay.underMouse(maxDistance: number, params: RaycastParams): Target
	local location = UserInputService:GetMouseLocation()
	return CursorRay.fromScreen(workspace.CurrentCamera, location.X, location.Y, maxDistance, params)
end

return CursorRay
```

Setting up the filter once on the client:

```lua
--!strict
local Players = game:GetService("Players")
local CursorRay = require(game:GetService("ReplicatedStorage"):WaitForChild("CursorRay"))

local params = RaycastParams.new()
params.FilterType = Enum.RaycastFilterType.Exclude
params.RespectCanCollide = true

local function aimPoint(): Vector3
	params.FilterDescendantsInstances = { Players.LocalPlayer.Character, workspace:FindFirstChild("PlacementPreview") }
	return CursorRay.underMouse(1000, params).position
end

return aimPoint
```

- `GetMouseLocation` includes the top bar inset, which is exactly what `ViewportPointToRay` expects; `ScreenPointToRay` is the variant for coordinates that exclude the inset.
- `RespectCanCollide` skips invisible non-collidable parts such as triggers and zones; parts that should never be hit can also set `CanQuery = false`.
- The fallback point at `maxDistance` keeps weapons firing toward the crosshair when aiming at the sky instead of toward a point near the world origin.

# Test
```lua
local wall = Instance.new("Part")
wall.Anchored = true
wall.Size = Vector3.new(20, 20, 1)
wall.Position = Vector3.new(0, 5, -40)
wall.Parent = workspace
local trigger = Instance.new("Part")
trigger.Anchored = true
trigger.CanQuery = false
trigger.Size = Vector3.new(20, 20, 1)
trigger.Position = Vector3.new(0, 5, -20)
trigger.Parent = workspace
local params = RaycastParams.new()
params.FilterType = Enum.RaycastFilterType.Exclude

local hit = item.cast(Vector3.new(0, 5, 0), Vector3.new(0, 0, -3), 1000, params)
check("hits the wall through a non-queryable trigger", hit.instance == wall and math.abs(hit.position.Z + 39.5) < 1e-9)
check("normal faces the camera", hit.normal == Vector3.new(0, 0, 1))
local sky = item.cast(Vector3.new(0, 5, 0), Vector3.new(0, 1, 0), 500, params)
check("sky gives a point at max distance", sky.instance == nil and (sky.position - Vector3.new(0, 505, 0)).Magnitude < 1e-9)
params.FilterDescendantsInstances = { wall }
local through = item.cast(Vector3.new(0, 5, 0), Vector3.new(0, 0, -1), 100, params)
check("excluded instances are ignored", through.instance == nil)
```
