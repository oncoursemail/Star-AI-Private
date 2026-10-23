---
id: gb-world-build-grid-snap
category: building-layout
topics: grid placement, snapping, rotation, footprint, building system
source: original
---
# Request
I'm making a tycoon-style building system with a 4-stud grid. Snapping with `math.floor(x / 4) * 4` works for 1x1 items, but my 1x2 and 3x3 items end up half a cell off, and rotating a 1x2 item makes it hang outside the cell lines. How do I snap correctly for any footprint and rotation?

# Answer
Snap the item's centre, not its corner: footprints with an odd number of cells centre on a cell's middle, even ones centre on a grid line. Rotating by 90 or 270 degrees swaps the footprint's X and Z cell counts before snapping. The functions are pure, so the client preview and the server check use the exact same maths.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.GridPlacement
local GridPlacement = {}

function GridPlacement.snapAxis(value: number, grid: number, cells: number): number
	if cells % 2 == 1 then
		return (math.floor(value / grid) + 0.5) * grid
	end
	return math.round(value / grid) * grid
end

function GridPlacement.footprint(cellsX: number, cellsZ: number, quarterTurns: number): (number, number)
	if quarterTurns % 2 == 1 then
		return cellsZ, cellsX
	end
	return cellsX, cellsZ
end

function GridPlacement.cframeFor(
	hit: Vector3,
	cellsX: number,
	cellsZ: number,
	height: number,
	quarterTurns: number,
	grid: number
): CFrame
	local turns = quarterTurns % 4
	local footX, footZ = GridPlacement.footprint(cellsX, cellsZ, turns)
	local x = GridPlacement.snapAxis(hit.X, grid, footX)
	local z = GridPlacement.snapAxis(hit.Z, grid, footZ)
	return CFrame.new(x, hit.Y + height / 2, z) * CFrame.Angles(0, math.rad(90 * turns), 0)
end

return GridPlacement
```

A minimal preview loop in a LocalScript (R rotates, the server re-validates on click):

```lua
--!strict
local RunService = game:GetService("RunService")
local UserInputService = game:GetService("UserInputService")
local GridPlacement = require(game:GetService("ReplicatedStorage"):WaitForChild("GridPlacement"))

local camera = workspace.CurrentCamera
local preview = workspace:WaitForChild("PlacementPreview")
local turns = 0
local params = RaycastParams.new()
params.FilterType = Enum.RaycastFilterType.Exclude
params.FilterDescendantsInstances = { preview }

UserInputService.InputBegan:Connect(function(input, processed)
	if not processed and input.KeyCode == Enum.KeyCode.R then
		turns = (turns + 1) % 4
	end
end)

RunService.RenderStepped:Connect(function()
	local mouse = UserInputService:GetMouseLocation()
	local ray = camera:ViewportPointToRay(mouse.X, mouse.Y)
	local result = workspace:Raycast(ray.Origin, ray.Direction * 500, params)
	if result then
		preview:PivotTo(GridPlacement.cframeFor(result.Position, 1, 2, 3, turns, 4))
	end
end)
```

- `% 4` in Luau always returns 0-3, even for negative turn counts, so rotating left past zero needs no special case.
- Keep the cell counts on the item (attributes such as `CellsX`/`CellsZ`) so the same function serves every item.
- The server must run the same `cframeFor` on the cell and rotation the client asks for; never accept a client-sent CFrame.

# Test
```lua
check("odd footprint centres on a cell", item.snapAxis(5.3, 4, 1) == 6)
check("even footprint centres on a grid line", item.snapAxis(5.3, 4, 2) == 4)
check("negative coordinates snap the same way", item.snapAxis(-0.5, 4, 1) == -2)

local cf = item.cframeFor(Vector3.new(5.3, 0, 7.9), 1, 2, 3, 0, 4)
check("1x2 unrotated snaps both axes and sits on the floor", cf.Position == Vector3.new(6, 1.5, 8))
local turned = item.cframeFor(Vector3.new(5.3, 0, 7.9), 1, 2, 3, 1, 4)
check("rotation swaps the footprint", turned.Position == Vector3.new(4, 1.5, 6))
check("rotation is applied in 90 degree steps", (turned.LookVector - Vector3.new(-1, 0, 0)).Magnitude < 1e-9)
local x, z = item.footprint(1, 2, -1)
check("negative turns wrap", x == 2 and z == 1)
```
