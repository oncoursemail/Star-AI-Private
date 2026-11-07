---
id: gb-world-light-day-night
category: building-lighting
topics: day-night cycle, Lighting.ClockTime, street lamps, CollectionService, Heartbeat
source: original
---
# Request
I want a day/night cycle where a full day takes 20 minutes, and every street lamp (tagged "StreetLamp") turns on at dusk and off at dawn. My current version does `while true do Lighting.ClockTime += 0.01 task.wait() end` and the lamps are toggled by checking the time in each lamp's own script. Can you clean this up?

# Answer
Drive the clock from elapsed time on the server (so lag never slows the day), write `ClockTime` only when it has moved a game minute, and switch the lamps once per dusk/dawn transition from one place. Lamps that stream in or get built later are set to the current state through the tag's added signal.

```lua
--!strict
-- ModuleScript: ServerScriptService.DayNightCycle
local CollectionService = game:GetService("CollectionService")
local Lighting = game:GetService("Lighting")
local RunService = game:GetService("RunService")

local LAMP_TAG = "StreetLamp"
local MINUTE = 1 / 60

export type Cycle = {
	stopCycle: () -> (),
	isNight: () -> boolean,
}

local DayNightCycle = {}

function DayNightCycle.clockAt(elapsed: number, dayLength: number, startClock: number): number
	return (startClock + elapsed / dayLength * 24) % 24
end

function DayNightCycle.isNightAt(clock: number, dusk: number, dawn: number): boolean
	return clock >= dusk or clock < dawn
end

local function setLamp(lamp: Instance, on: boolean)
	for _, descendant in lamp:GetDescendants() do
		if descendant:IsA("Light") then
			descendant.Enabled = on
		end
	end
end

function DayNightCycle.start(dayLength: number, startClock: number, dusk: number, dawn: number): Cycle
	local elapsed = 0
	local night = DayNightCycle.isNightAt(startClock, dusk, dawn)
	Lighting.ClockTime = startClock
	for _, lamp in CollectionService:GetTagged(LAMP_TAG) do
		setLamp(lamp, night)
	end

	local added = CollectionService:GetInstanceAddedSignal(LAMP_TAG):Connect(function(lamp: Instance)
		setLamp(lamp, night)
	end)

	local heartbeat = RunService.Heartbeat:Connect(function(dt: number)
		elapsed += dt
		local clock = DayNightCycle.clockAt(elapsed, dayLength, startClock)
		-- Writing every frame would replicate 60 property changes a second for no visible gain.
		if math.abs(clock - Lighting.ClockTime) >= MINUTE then
			Lighting.ClockTime = clock
		end
		local nowNight = DayNightCycle.isNightAt(clock, dusk, dawn)
		if nowNight ~= night then
			night = nowNight
			for _, lamp in CollectionService:GetTagged(LAMP_TAG) do
				setLamp(lamp, night)
			end
		end
	end)

	return {
		stopCycle = function()
			added:Disconnect()
			heartbeat:Disconnect()
		end,
		isNight = function(): boolean
			return night
		end,
	}
end

return DayNightCycle
```

Starting it from a server Script: `DayNightCycle.start(20 * 60, 8, 18, 6)` (20-minute days, starting at 8 AM, lamps on from 18:00 to 06:00).

- Time comes from accumulated `dt`, so a server hitch skips ahead instead of stretching the day.
- The `% 24` wrap means the clock passes midnight cleanly; the `abs` check against the current value also handles the wrap because the jump from 23.99 to 0 is larger than a minute.
- One loop over tagged lamps twice per day replaces hundreds of per-lamp scripts polling the clock.
- If clients need smoother sun motion than one-minute steps, tween `ClockTime` locally between server updates.

# Test
```lua
local cs = game:GetService("CollectionService")
local Lighting = game:GetService("Lighting")
local lamp = Instance.new("Model")
local bulb = Instance.new("Part")
bulb.Parent = lamp
local light = Instance.new("PointLight")
light.Parent = bulb
lamp.Parent = workspace
cs:AddTag(lamp, "StreetLamp")

local cycle = item.start(240, 17.5, 18, 6)
check("daytime start turns lamps off", light.Enabled == false and not cycle.isNight())
__frames(12, 0.5)
check("clock advances with elapsed time", math.abs(Lighting.ClockTime - 18.1) < 1 / 60 + 1e-9)
check("dusk turns lamps on", light.Enabled == true and cycle.isNight())
local late = Instance.new("Model")
local lateLight = Instance.new("SpotLight")
lateLight.Enabled = false
lateLight.Parent = late
late.Parent = workspace
cs:AddTag(late, "StreetLamp")
check("lamp added at night switches on", lateLight.Enabled == true)
check("clock wraps past midnight", math.abs(item.clockAt(60, 240, 23) - 5) < 1e-9)
check("dawn boundary", item.isNightAt(5.99, 18, 6) and not item.isNightAt(6, 18, 6))
cycle.stopCycle()
local frozen = Lighting.ClockTime
__frames(10, 1)
check("stop freezes the clock", Lighting.ClockTime == frozen)
```
