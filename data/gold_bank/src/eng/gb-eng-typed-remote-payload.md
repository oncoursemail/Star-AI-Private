---
id: gb-eng-typed-remote-payload
category: luau-typing
topics: RemoteEvent, payload typing, validation, unknown type, strict mode
source: original
---
# Request
My `OnServerEvent` handler for placing furniture takes `(player, data)` and I just access `data.itemId`, `data.position` and `data.rotation` directly. It's untyped and I know exploiters can send anything. How do I type the payload properly on the server?

# Answer
Treat what the client sends as `unknown`, and write one parser that checks every field and returns a typed `PlacePayload?`. The handler only touches the typed value, so a missing check shows up as a type error.

```lua
--!strict
-- ModuleScript: ServerScriptService.PlacementPayload
export type PlacePayload = {
	itemId: string,
	position: Vector3,
	rotationSteps: number, -- quarter turns, 0..3
}

local MAX_ID_LENGTH = 40
local BUILD_LIMIT = 512

local PlacementPayload = {}

local function finiteVector(v: Vector3): boolean
	for _, n in { v.X, v.Y, v.Z } do
		if n ~= n or math.abs(n) > BUILD_LIMIT then
			return false
		end
	end
	return true
end

function PlacementPayload.parse(raw: unknown): PlacePayload?
	if type(raw) ~= "table" then
		return nil
	end
	local data = raw :: { [unknown]: unknown }
	local itemId, position, rotation = data.itemId, data.position, data.rotationSteps
	if type(itemId) ~= "string" or #itemId == 0 or #itemId > MAX_ID_LENGTH then
		return nil
	end
	local positionType = typeof(position)
	if positionType ~= "Vector3" or not finiteVector(position :: Vector3) then
		return nil
	end
	if type(rotation) ~= "number" or rotation % 1 ~= 0 or rotation < 0 or rotation > 3 then
		return nil
	end
	return { itemId = itemId, position = position :: Vector3, rotationSteps = rotation }
end

return PlacementPayload
```

```lua
--!strict
-- Script: ServerScriptService.PlacementServer
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerScriptService = game:GetService("ServerScriptService")
local PlacementPayload = require(ServerScriptService.PlacementPayload)

local ServerStorage = game:GetService("ServerStorage")

local placeRemote = ReplicatedStorage:WaitForChild("PlaceFurniture") :: RemoteEvent
local furniture = ServerStorage:WaitForChild("Furniture")
local plots = workspace:WaitForChild("Plots")

local function insideOwnPlot(player: Player, position: Vector3): boolean
	local plot = plots:FindFirstChild(tostring(player.UserId))
	if plot == nil or not plot:IsA("BasePart") then
		return false
	end
	local offset = plot.CFrame:PointToObjectSpace(position)
	return math.abs(offset.X) <= plot.Size.X / 2 and math.abs(offset.Z) <= plot.Size.Z / 2
end

placeRemote.OnServerEvent:Connect(function(player: Player, raw: unknown)
	local payload = PlacementPayload.parse(raw)
	if payload == nil or not insideOwnPlot(player, payload.position) then
		return
	end
	local template = furniture:FindFirstChild(payload.itemId)
	if template == nil or not template:IsA("Model") then
		return
	end
	local model = template:Clone()
	model:PivotTo(CFrame.new(payload.position) * CFrame.Angles(0, math.rad(90 * payload.rotationSteps), 0))
	model.Parent = plots
end)
```

- `unknown` forces a check before every use, unlike `any`, which lets `raw.itemId.Name` compile and crash.
- `typeof` (not `type`) is needed for Roblox datatypes: `type` reports every Instance, CFrame and Color3 as `"userdata"` (a Vector3 as `"vector"`), so it cannot tell those apart.
- The NaN test `n ~= n` and the build limit stop a client from placing at `Vector3.new(0/0, 0, 0)` or a huge coordinate.
- The parser checks shape; game rules (inside the player's own plot, item exists) are checked after it. Add an owned-items check if furniture is bought, and cap furniture per plot plus a per-player cooldown on the remote, or a client can spam thousands of models into its own plot.

# Test
```lua
local ok = item.parse({ itemId = "chair", position = Vector3.new(4, 0, 8), rotationSteps = 2 })
check("valid payload parsed", ok ~= nil and ok.itemId == "chair" and ok.rotationSteps == 2)
check("non-table rejected", item.parse("chair") == nil and item.parse(nil) == nil)
check("NaN position rejected", item.parse({ itemId = "chair", position = Vector3.new(0 / 0, 0, 0), rotationSteps = 0 }) == nil)
check("far position rejected", item.parse({ itemId = "chair", position = Vector3.new(1e6, 0, 0), rotationSteps = 0 }) == nil)
check("fractional rotation rejected", item.parse({ itemId = "chair", position = Vector3.zero, rotationSteps = 1.5 }) == nil)
check("table instead of Vector3 rejected", item.parse({ itemId = "chair", position = { X = 1, Y = 2, Z = 3 }, rotationSteps = 0 }) == nil)
check("overlong id rejected", item.parse({ itemId = string.rep("a", 41), position = Vector3.zero, rotationSteps = 0 }) == nil)
```
