---
id: gb-world-light-interior-zones
category: building-lighting
topics: interior lighting, zones, PointToObjectSpace, nested rooms, client polling
source: original
---
# Request
When players walk into a building I want the lighting to switch to a darker indoor preset, and back when they leave. Buildings have invisible zone parts (some rotated, and some rooms are inside bigger halls). Touched/TouchEnded on the zones flickers constantly. What's a reliable way?

# Answer
Poll instead of relying on touch events: a few times per second, find which zone contains the camera subject's position. Containment is a local-space box test (so rotated zones work), and when zones are nested the smallest containing one wins. The callback fires only when the zone actually changes.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.InteriorZones
local CollectionService = game:GetService("CollectionService")

local InteriorZones = {}

function InteriorZones.contains(zone: BasePart, point: Vector3): boolean
	local localPoint = zone.CFrame:PointToObjectSpace(point)
	local half = zone.Size / 2
	return math.abs(localPoint.X) <= half.X and math.abs(localPoint.Y) <= half.Y and math.abs(localPoint.Z) <= half.Z
end

function InteriorZones.zoneAt(point: Vector3, zones: { Instance }): BasePart?
	local best: BasePart? = nil
	local bestVolume = math.huge
	for _, zone in zones do
		if zone:IsA("BasePart") and InteriorZones.contains(zone, point) then
			local volume = zone.Size.X * zone.Size.Y * zone.Size.Z
			if volume < bestVolume then
				best, bestVolume = zone, volume
			end
		end
	end
	return best
end

function InteriorZones.track(tag: string, getPoint: () -> Vector3?, onChange: (zone: BasePart?) -> (), interval: number?): () -> ()
	local running = true
	local current: BasePart? = nil
	task.spawn(function()
		while running do
			local point = getPoint()
			local zone = if point then InteriorZones.zoneAt(point, CollectionService:GetTagged(tag)) else nil
			if zone ~= current then
				current = zone
				onChange(zone)
			end
			task.wait(interval or 0.25)
		end
	end)
	return function()
		running = false
	end
end

return InteriorZones
```

Hooking it to lighting presets in a LocalScript, with each zone naming its preset in an attribute:

```lua
--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local InteriorZones = require(ReplicatedStorage:WaitForChild("InteriorZones"))
local LightingPresets = require(ReplicatedStorage:WaitForChild("LightingPresets"))

InteriorZones.track("InteriorZone", function(): Vector3?
	local character = Players.LocalPlayer.Character
	local root = if character then character:FindFirstChild("HumanoidRootPart") else nil
	return if root and root:IsA("BasePart") then root.Position else nil
end, function(zone: BasePart?)
	local preset = if zone then zone:GetAttribute("Preset") else nil
	LightingPresets.apply(if type(preset) == "string" then preset else "Clear", 1)
end)
```

- Touched events depend on physics contacts and fire repeatedly as limbs move, which is the flicker; a point-in-box test has no such noise.
- Zone parts should be Anchored, CanCollide/CanTouch/CanQuery off and fully transparent; the script only reads their CFrame and Size.
- Smallest-volume-wins lets a closet inside a hall use its own darker preset without any priority settings.

# Test
```lua
local cs = game:GetService("CollectionService")
local hall = Instance.new("Part")
hall.Size = Vector3.new(40, 20, 40)
hall.CFrame = CFrame.new(0, 10, 0)
cs:AddTag(hall, "InteriorZone")
local closet = Instance.new("Part")
closet.Size = Vector3.new(4, 8, 10)
closet.CFrame = CFrame.new(10, 4, 0) * CFrame.Angles(0, math.rad(90), 0)
cs:AddTag(closet, "InteriorZone")

check("rotated zone uses local axes", item.contains(closet, Vector3.new(14, 4, 0)) and not item.contains(closet, Vector3.new(10, 4, 4)))
check("smallest containing zone wins", item.zoneAt(Vector3.new(12, 3, 0), { hall, closet }) == closet)
check("outside every zone is nil", item.zoneAt(Vector3.new(100, 3, 0), { hall, closet }) == nil)

local position = Vector3.new(100, 3, 0)
local changes = {}
local stop = item.track("InteriorZone", function()
	return position
end, function(zone)
	table.insert(changes, zone or "outside")
end)
__advance(1)
check("no change while staying outside", #changes == 0)
position = Vector3.new(0, 3, 0)
__advance(0.3)
check("entering the hall fires once", #changes == 1 and changes[1] == hall)
position = Vector3.new(12, 3, 0)
__advance(1)
check("moving into the closet fires once more", #changes == 2 and changes[2] == closet)
stop()
position = Vector3.new(100, 3, 0)
__advance(1)
check("stopped tracker stays quiet", #changes == 2)
```
