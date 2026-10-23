---
id: gb-src-day-night-streetlights
category: building-lighting
topics: Lighting, ClockTime, day night cycle, CollectionService, street lights, Heartbeat
source: adapted
source_id: creator-docs
source_path: content/en-us/reference/engine/classes/Lighting.yaml
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I want a day/night cycle where a full day takes 12 real minutes, and all the street lamps (tagged "StreetLamp", each with a PointLight inside) switch on at dusk (18:00) and off at dawn (6:00). How do I drive that from the server?

# Answer
Advance `Lighting.ClockTime` (hours, 0-24) on the server by `dt * 24 / dayLengthSeconds` each Heartbeat; it replicates to clients. Check the hour each step and toggle the lamps only when night starts or ends, not every frame.

```lua
--!strict
local CollectionService = game:GetService("CollectionService")
local Lighting = game:GetService("Lighting")
local RunService = game:GetService("RunService")

local DayCycle = {}

DayCycle.DUSK = 18
DayCycle.DAWN = 6

function DayCycle.isNight(clockTime: number): boolean
	return clockTime >= DayCycle.DUSK or clockTime < DayCycle.DAWN
end

function DayCycle.setLamps(on: boolean)
	for _, lamp in CollectionService:GetTagged("StreetLamp") do
		local light = lamp:FindFirstChildWhichIsA("PointLight", true)
		if light then
			light.Enabled = on
		end
		if lamp:IsA("BasePart") then
			lamp.Material = if on then Enum.Material.Neon else Enum.Material.SmoothPlastic
		end
	end
end

function DayCycle.start(dayLengthSeconds: number): RBXScriptConnection
	local hoursPerSecond = 24 / dayLengthSeconds
	local night = DayCycle.isNight(Lighting.ClockTime)
	DayCycle.setLamps(night)
	return RunService.Heartbeat:Connect(function(dt: number)
		Lighting.ClockTime = (Lighting.ClockTime + dt * hoursPerSecond) % 24
		local nowNight = DayCycle.isNight(Lighting.ClockTime)
		if nowNight ~= night then
			night = nowNight
			DayCycle.setLamps(night)
		end
	end)
end

return DayCycle
```

Server usage: `DayCycle.start(12 * 60)`.

- `ClockTime` is a number, easier to do math with than the `TimeOfDay` string ("18:00:00").
- Lamps change only on the dusk and dawn transitions, so the loop does almost no work most frames.
- Lamps that stream in later on clients still have the right state, because `Enabled` is set on the server and replicates.

# Test
```lua
local CollectionService = game:GetService("CollectionService")
local Lighting = game:GetService("Lighting")
local lamp = Instance.new("Part")
local light = Instance.new("PointLight")
light.Parent = lamp
lamp.Parent = workspace
CollectionService:AddTag(lamp, "StreetLamp")
check("night detection", item.isNight(23) and item.isNight(2) and not item.isNight(12))
Lighting.ClockTime = 17.5
local conn = item.start(24)
check("lamps off before dusk", light.Enabled == false)
__frames(40, 1 / 60)
check("lamps on after dusk", Lighting.ClockTime >= 18 and light.Enabled == true and lamp.Material == Enum.Material.Neon)
__frames(760, 1 / 60)
check("lamps off again after dawn", Lighting.ClockTime >= 6 and Lighting.ClockTime < 18 and light.Enabled == false)
conn:Disconnect()
```
