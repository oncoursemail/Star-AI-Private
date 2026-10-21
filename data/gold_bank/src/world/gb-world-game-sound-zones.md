---
id: gb-world-game-sound-zones
category: gameplay-systems
topics: ambient sound zones, crossfade, TweenService, priority, client audio
source: original
---
# Request
I want ambient audio that changes by area: forest birds outside, cave drips in the cave, and a tavern song inside the tavern (which is inside the town zone). Sounds should crossfade, not cut. Zones are invisible parts with a Sound inside each.

# Answer
A few times per second, ask which zone parts contain the listener using an overlap query limited to the zone folder, and pick the one with the highest `Priority` attribute. When the winner changes, tween the old zone's sound down and the new one up; sounds keep playing at volume 0 so a crossfade back is seamless.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.SoundZones
local TweenService = game:GetService("TweenService")

export type Controller = {
	refresh: (listener: Vector3) -> BasePart?,
	current: () -> BasePart?,
}

local SoundZones = {}

local function priorityOf(zone: BasePart): number
	local value = zone:GetAttribute("Priority")
	return if type(value) == "number" then value else 0
end

function SoundZones.new(folder: Instance, fadeTime: number): Controller
	local params = OverlapParams.new()
	params.FilterType = Enum.RaycastFilterType.Include
	params.FilterDescendantsInstances = { folder }
	local info = TweenInfo.new(fadeTime, Enum.EasingStyle.Linear)
	local active: BasePart? = nil

	local function fade(zone: BasePart?, volume: number)
		local sound = if zone then zone:FindFirstChildOfClass("Sound") else nil
		if sound == nil then
			return
		end
		if volume > 0 and not sound.Playing then
			sound.Volume = 0
			sound.Looped = true
			sound:Play()
		end
		local target = if volume > 0 then sound:GetAttribute("ZoneVolume") or 0.5 else 0
		TweenService:Create(sound, info, { Volume = target }):Play()
	end

	return {
		refresh = function(listener: Vector3): BasePart?
			local best: BasePart? = nil
			for _, zone in workspace:GetPartBoundsInRadius(listener, 0.1, params) do
				if best == nil or priorityOf(zone) > priorityOf(best) then
					best = zone
				end
			end
			if best ~= active then
				fade(active, 0)
				fade(best, 1)
				active = best
			end
			return best
		end,
		current = function(): BasePart?
			return active
		end,
	}
end

return SoundZones
```

Driving it from the camera in a LocalScript:

```lua
--!strict
local SoundZones = require(game:GetService("ReplicatedStorage"):WaitForChild("SoundZones"))

local zones = SoundZones.new(workspace:WaitForChild("SoundZones"), 1.5)
local camera = workspace.CurrentCamera

while true do
	zones.refresh(camera.Focus.Position)
	task.wait(0.3)
end
```

- Include-filtering on the zone folder makes the overlap query ignore the whole map, so it costs almost nothing.
- Priority settles nesting: tavern 3 inside town 2 inside world 0, without any special cases.
- The zone parts need `CanQuery` on (overlap queries use it) but can have `CanCollide` and `CanTouch` off.
- Using the camera focus means spectators and players in a vehicle hear the area they are looking at.

# Test
```lua
local folder = Instance.new("Folder")
folder.Name = "SoundZones"
folder.Parent = workspace
local function zone(name, pos, size, priority)
	local z = Instance.new("Part")
	z.Name = name
	z.Anchored = true
	z.CanCollide = false
	z.Position = pos
	z.Size = size
	z:SetAttribute("Priority", priority)
	local s = Instance.new("Sound")
	s:SetAttribute("ZoneVolume", 0.8)
	s.Parent = z
	z.Parent = folder
	return z
end
local town = zone("Town", Vector3.new(0, 10, 0), Vector3.new(100, 20, 100), 1)
local tavern = zone("Tavern", Vector3.new(20, 5, 20), Vector3.new(10, 10, 10), 3)
local stray = Instance.new("Part")
stray.Size = Vector3.new(500, 500, 500)
stray.Parent = workspace

local zones = item.new(folder, 1)
check("listener in town hears town", zones.refresh(Vector3.new(0, 3, 0)) == town)
__advance(1.1)
check("town sound faded in and looping", town.Sound.Playing and town.Sound.Volume == 0.8 and town.Sound.Looped)
check("nested tavern wins by priority", zones.refresh(Vector3.new(20, 3, 20)) == tavern)
__advance(1.1)
check("crossfade: town down, tavern up", town.Sound.Volume == 0 and tavern.Sound.Volume == 0.8)
check("leaving every zone fades out", zones.refresh(Vector3.new(400, 3, 0)) == nil)
__advance(1.1)
check("non-zone parts are ignored", tavern.Sound.Volume == 0 and zones.current() == nil)
```
