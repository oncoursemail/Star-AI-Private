---
id: gb-data-msg-global-event-sync
category: messaging
topics: MessagingService, global event, synchronized start, duplicate messages, task.delay
source: original
---
# Request
I want to trigger a "meteor shower" event in every server at the same moment, about a minute after I start it. If I just publish "start now", servers receive it at slightly different times. How do I get them in sync?

# Answer
Publish a start time instead of a command: an event id plus `startsAt` in Unix seconds from `workspace:GetServerTimeNow()`, which has sub-second precision (`os.time()` is whole seconds, so two servers could fire up to a second apart). Each server schedules the event with `task.delay(startsAt - now)`, so small delivery differences do not matter. Remember ids already scheduled so a repeated message is ignored, and drop messages whose start time is long past.

```lua
--!strict
-- ModuleScript: ServerScriptService.GlobalEvents
local MessagingService = game:GetService("MessagingService")
local HttpService = game:GetService("HttpService")

local TOPIC = "GlobalEvents"
local LATE_TOLERANCE = 10 -- seconds; a message older than this is ignored

export type Handler = (eventName: string) -> ()

local GlobalEvents = {}
local handlers: { [string]: Handler } = {}
local scheduled: { [string]: boolean } = {}

function GlobalEvents.on(eventName: string, handler: Handler)
	handlers[eventName] = handler
end

local function onMessage(message: { Data: any })
	local data = message.Data
	if type(data) ~= "table" or type(data.id) ~= "string" or type(data.name) ~= "string" or type(data.startsAt) ~= "number" then
		return
	end
	local handler = handlers[data.name]
	if handler == nil or scheduled[data.id] then
		return
	end
	local delay = data.startsAt - workspace:GetServerTimeNow()
	if delay < -LATE_TOLERANCE then
		return
	end
	scheduled[data.id] = true
	task.delay(math.max(0, delay), handler, data.name)
end

-- Schedules eventName in every server `leadSeconds` from now.
function GlobalEvents.schedule(eventName: string, leadSeconds: number): boolean
	local payload = { id = HttpService:GenerateGUID(false), name = eventName, startsAt = workspace:GetServerTimeNow() + leadSeconds }
	local ok = pcall(function()
		MessagingService:PublishAsync(TOPIC, payload)
	end)
	return ok
end

task.spawn(function()
	for attempt = 1, 5 do
		local ok = pcall(function()
			MessagingService:SubscribeAsync(TOPIC, onMessage)
		end)
		if ok then
			return
		end
		task.wait(2 ^ attempt)
	end
	warn("GlobalEvents could not subscribe; this server will miss global events")
end)

return GlobalEvents
```

Usage: `GlobalEvents.on("MeteorShower", startMeteors)` in every server, and an admin command calls `GlobalEvents.schedule("MeteorShower", 60)`.

- Server clocks are synchronised closely enough for gameplay events; a 60-second lead also covers slow message delivery.
- Servers that start after the message was sent never see it; if late joiners matter, also store the next event time in a MemoryStore key that new servers read on startup.
- Show a countdown to players using the same `startsAt` and `workspace:GetServerTimeNow()` on the client, which estimates server time, so every UI agrees.

# Test
```lua
local started = {}
item.on("MeteorShower", function(name)
	table.insert(started, { name = name, at = workspace:GetServerTimeNow() })
end)
local t0 = workspace:GetServerTimeNow()
check("scheduling publishes the event", item.schedule("MeteorShower", 60))
__advance(59)
check("nothing happens before the start time", #started == 0)
__advance(1.5)
check("the event starts at the agreed time", #started == 1 and math.abs(started[1].at - t0 - 60) < 1e-6)

local ms = game:GetService("MessagingService")
ms:PublishAsync("GlobalEvents", { id = "fixed-id", name = "MeteorShower", startsAt = workspace:GetServerTimeNow() + 5 })
ms:PublishAsync("GlobalEvents", { id = "fixed-id", name = "MeteorShower", startsAt = workspace:GetServerTimeNow() + 5 })
__advance(6)
check("a duplicate message only schedules once", #started == 2)

ms:PublishAsync("GlobalEvents", { id = "old", name = "MeteorShower", startsAt = workspace:GetServerTimeNow() - 120 })
ms:PublishAsync("GlobalEvents", { id = "bad", name = "Unknown", startsAt = workspace:GetServerTimeNow() })
ms:PublishAsync("GlobalEvents", { id = "bad2", name = "MeteorShower", startsAt = "soon" })
__advance(1)
check("stale, unknown and malformed events are ignored", #started == 2)

ms:PublishAsync("GlobalEvents", { id = "half", name = "MeteorShower", startsAt = workspace:GetServerTimeNow() + 2.5 })
__advance(2.4)
local early = #started
__advance(0.2)
check("fractional start times are honoured", early == 2 and #started == 3)
```
