---
id: gb-eng-stream-minimap-markers
category: performance-streaming
topics: StreamingEnabled, minimap, replicated data, attributes, design for stream out
source: original
---
# Request
My minimap draws icons for every capture point by reading the parts in `workspace.CapturePoints`. With streaming on, far-away points vanish from the map because their parts aren't on the client. How should I design this so the minimap works regardless of streaming?

# Answer
Do not make clients depend on streamed parts for global information. The server publishes the small amount of data the minimap needs (name, position, owner) as attributes on a Configuration in ReplicatedStorage, which always replicates; the client builds markers from that data and never touches the faraway parts.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.MapMarkers (server publishes, client reads)
local MapMarkers = {}

export type Marker = { name: string, position: Vector3, owner: string }

function MapMarkers.publish(folder: Instance, points: { BasePart }): ()
	for _, point in points do
		local entry = folder:FindFirstChild(point.Name)
		if entry == nil then
			local config = Instance.new("Configuration")
			config.Name = point.Name
			config.Parent = folder
			entry = config
		end
		entry:SetAttribute("Position", point.Position)
		local owner = point:GetAttribute("Owner")
		entry:SetAttribute("Owner", if type(owner) == "string" then owner else "Neutral")
	end
end

function MapMarkers.read(folder: Instance): { Marker }
	local markers: { Marker } = {}
	for _, entry in folder:GetChildren() do
		local position = entry:GetAttribute("Position")
		local owner = entry:GetAttribute("Owner")
		if typeof(position) == "Vector3" and type(owner) == "string" then
			table.insert(markers, { name = entry.Name, position = position, owner = owner })
		end
	end
	table.sort(markers, function(a: Marker, b: Marker): boolean
		return a.name < b.name
	end)
	return markers
end

function MapMarkers.toMap(position: Vector3, mapCenter: Vector3, worldSize: number): (number, number)
	local offset = position - mapCenter
	local x = math.clamp(offset.X / worldSize + 0.5, 0, 1)
	local y = math.clamp(offset.Z / worldSize + 0.5, 0, 1)
	return x, y
end

return MapMarkers
```

- Server: create `ReplicatedStorage.MapData` once, call `MapMarkers.publish(mapData, capturePoints)` at start and whenever ownership changes. Client: rebuild icons on `mapData.DescendantAdded` and each entry's `AttributeChanged`, positioning them with `UDim2.fromScale(MapMarkers.toMap(...))`.
- ReplicatedStorage is never streamed, and a few attributes per point cost almost nothing compared with keeping the capture-point models persistent.
- The client still uses the real parts for nearby things (effects, prompts) when they stream in; only global information goes through the data folder.

# Test
```lua
local folder = Instance.new("Folder")
folder.Parent = game:GetService("ReplicatedStorage")
local a = Instance.new("Part")
a.Name = "Alpha"
a.Position = Vector3.new(-500, 0, 200)
a:SetAttribute("Owner", "Red")
local b = Instance.new("Part")
b.Name = "Bravo"
b.Position = Vector3.new(300, 0, -100)
item.publish(folder, { b, a })
local markers = item.read(folder)
check("markers from replicated data", #markers == 2 and markers[1].name == "Alpha" and markers[1].owner == "Red" and markers[2].owner == "Neutral")
check("positions published", markers[2].position == Vector3.new(300, 0, -100))
a:SetAttribute("Owner", "Blue")
item.publish(folder, { a, b })
check("republish updates without duplicates", #folder:GetChildren() == 2 and item.read(folder)[1].owner == "Blue")
local x, y = item.toMap(Vector3.new(0, 0, 0), Vector3.zero, 1000)
local cx = item.toMap(Vector3.new(5000, 0, 0), Vector3.zero, 1000)
check("map projection centred and clamped", x == 0.5 and y == 0.5 and cx == 1)
```
