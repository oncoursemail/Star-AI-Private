---
id: gb-world-build-plot-placement-server
category: building-layout
topics: plot, placement validation, RemoteEvent, GetPartBoundsInBox, grid cells
source: original
---
# Request
Players place furniture on their own plot. Right now the client sends the CFrame where it wants the item and the server just clones it there, so exploiters place items on other people's plots and inside walls. What should the server check?

# Answer
Stop accepting a CFrame. The client sends the item name, a grid cell and a rotation; the server looks the item up in its own catalog, checks the footprint fits inside the sender's plot, computes the CFrame itself and refuses it if anything already occupies that space. Each plot part carries a `Cells` attribute with its size in grid cells.

```lua
--!strict
-- Script: ServerScriptService.PlacementServer
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerStorage = game:GetService("ServerStorage")

local placeItem = ReplicatedStorage:WaitForChild("PlaceItem")
local catalog = ServerStorage:WaitForChild("Placeables")
local plots = workspace:WaitForChild("Plots")

local GRID = 4
local COOLDOWN = 0.2
local lastPlace: { [Player]: number } = {}

local function isCell(value: any, limit: number): boolean
	return type(value) == "number" and value == math.floor(value) and value >= 0 and value < limit
end

placeItem.OnServerEvent:Connect(function(player: Player, itemName: any, cellX: any, cellZ: any, turns: any)
	local now = os.clock()
	if now - (lastPlace[player] or -math.huge) < COOLDOWN then
		return
	end
	local plot = plots:FindFirstChild(tostring(player.UserId))
	if plot == nil or not plot:IsA("BasePart") then
		return
	end
	local cells = plot:GetAttribute("Cells")
	if type(cells) ~= "number" or type(itemName) ~= "string" or not isCell(turns, 4) then
		return
	end
	local template = catalog:FindFirstChild(itemName)
	if template == nil or not template:IsA("Model") then
		return
	end
	local sizeX, sizeZ = template:GetAttribute("CellsX"), template:GetAttribute("CellsZ")
	local height = template:GetAttribute("Height")
	if type(sizeX) ~= "number" or type(sizeZ) ~= "number" or type(height) ~= "number" then
		return
	end
	local footX, footZ = if turns % 2 == 1 then sizeZ else sizeX, if turns % 2 == 1 then sizeX else sizeZ
	if not isCell(cellX, cells - footX + 1) or not isCell(cellZ, cells - footZ + 1) then
		return
	end

	local localX = (cellX + footX / 2) * GRID - cells * GRID / 2
	local localZ = (cellZ + footZ / 2) * GRID - cells * GRID / 2
	local offset = CFrame.new(localX, plot.Size.Y / 2 + height / 2, localZ) * CFrame.Angles(0, math.rad(90 * turns), 0)
	local target = plot.CFrame:ToWorldSpace(offset)

	local placedFolder = plot:FindFirstChild("Placed")
	if placedFolder == nil then
		return
	end
	local params = OverlapParams.new()
	params.FilterType = Enum.RaycastFilterType.Include
	params.FilterDescendantsInstances = { placedFolder }
	-- The box takes the unrotated size because `target` already carries the rotation.
	-- Shrink slightly so items on neighbouring cells, which only touch, do not count as overlapping.
	local probeSize = Vector3.new(sizeX * GRID - 0.2, height - 0.2, sizeZ * GRID - 0.2)
	if #workspace:GetPartBoundsInBox(target, probeSize, params) > 0 then
		return
	end

	lastPlace[player] = now
	local placed = template:Clone()
	placed:PivotTo(target)
	placed:SetAttribute("OwnerUserId", player.UserId)
	placed.Parent = placedFolder
end)

Players.PlayerRemoving:Connect(function(player: Player)
	lastPlace[player] = nil
end)
```

- The plot is found from the sender's own UserId, so there is no plot argument an exploiter could point at someone else's base.
- Cells must be whole numbers inside the plot after accounting for the rotated footprint; NaN fails `value == math.floor(value)`.
- The overlap query only looks inside the plot's Placed folder, so the floor and decorations never block placement while existing furniture does.
- The probe box is oriented by `target`, so it uses the unrotated `CellsX`/`CellsZ` size; passing the already swapped footprint would rotate a 1x3 item twice and check the wrong cells.

# Test
```lua
local rs = game:GetService("ReplicatedStorage")
local remote = Instance.new("RemoteEvent")
remote.Name = "PlaceItem"
remote.Parent = rs
local catalog = Instance.new("Folder")
catalog.Name = "Placeables"
catalog.Parent = game:GetService("ServerStorage")
local crate = Instance.new("Model")
crate.Name = "Crate"
crate:SetAttribute("CellsX", 1)
crate:SetAttribute("CellsZ", 1)
crate:SetAttribute("Height", 4)
local box = Instance.new("Part")
box.Size = Vector3.new(4, 4, 4)
box.Parent = crate
crate.PrimaryPart = box
crate.Parent = catalog
local plots = Instance.new("Folder")
plots.Name = "Plots"
plots.Parent = workspace
local plot = Instance.new("Part")
plot.Name = "21"
plot.Anchored = true
plot.Size = Vector3.new(40, 1, 40)
plot.Position = Vector3.new(0, 0, 0)
plot:SetAttribute("Cells", 10)
plot.Parent = plots
local placed = Instance.new("Folder")
placed.Name = "Placed"
placed.Parent = plot
```
```lua
local owner = __makePlayer(21, "Builder")
local stranger = __makePlayer(22, "NoPlot")
local remote = game:GetService("ReplicatedStorage").PlaceItem
local placed = workspace.Plots["21"].Placed

remote.OnServerEvent:Fire(owner, "Crate", 0, 0, 0)
check("valid placement creates the item", #placed:GetChildren() == 1)
check("server computed the position", (placed.Crate:FindFirstChildWhichIsA("BasePart").Position - Vector3.new(-18, 2.5, -18)).Magnitude < 1e-9)
__advance(1)
remote.OnServerEvent:Fire(owner, "Crate", 0, 0, 0)
check("occupied cell is refused", #placed:GetChildren() == 1)
__advance(1)
remote.OnServerEvent:Fire(owner, "Crate", 1, 0, 0)
check("neighbouring cell is allowed", #placed:GetChildren() == 2)
__advance(1)
remote.OnServerEvent:Fire(owner, "Crate", 10, 0, 0)
remote.OnServerEvent:Fire(owner, "Crate", 2.5, 0, 0)
remote.OnServerEvent:Fire(owner, "Crate", 0 / 0, 0, 0)
remote.OnServerEvent:Fire(owner, "Nuke", 5, 5, 0)
remote.OnServerEvent:Fire(stranger, "Crate", 5, 5, 0)
check("out of bounds, fractional, NaN, unknown item and no plot are refused", #placed:GetChildren() == 2)
remote.OnServerEvent:Fire(owner, "Crate", 5, 5, 0)
remote.OnServerEvent:Fire(owner, "Crate", 6, 6, 0)
check("cooldown blocks rapid placement", #placed:GetChildren() == 3)
```
