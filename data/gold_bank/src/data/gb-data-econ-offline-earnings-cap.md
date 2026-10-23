---
id: gb-data-econ-offline-earnings-cap
category: economy-simulation
topics: idle game, offline earnings, server time, cap, clock skew
source: original
---
# Request
My idle game should give players coins for the time they were offline, at half their normal rate, up to 8 hours. I save `lastOnline` when they leave. How do I compute this safely?

# Answer
Compute everything on the server from `os.time()` and the saved timestamp: clamp the elapsed time to `[0, cap]` (a negative value means a clock problem, not free coins), multiply by the saved income rate and the offline efficiency, and floor to whole coins. Stamp `lastOnline` again right after granting so the same time is never paid twice.

```lua
--!strict
-- ModuleScript: ServerScriptService.OfflineEarnings
export type IdleData = { lastOnline: number, ratePerSecond: number }

local CAP_SECONDS = 8 * 3600
local EFFICIENCY = 0.5
local MIN_SECONDS = 60 -- ignore quick rejoins

local OfflineEarnings = {}

-- Returns the coins to grant and the seconds that were counted. `now` is the server's os.time().
function OfflineEarnings.collect(data: IdleData, now: number): (number, number)
	local last = data.lastOnline
	data.lastOnline = now
	if type(last) ~= "number" or last <= 0 then
		return 0, 0 -- first session
	end
	local elapsed = math.clamp(now - last, 0, CAP_SECONDS)
	if elapsed < MIN_SECONDS then
		return 0, 0
	end
	local rate = if data.ratePerSecond == data.ratePerSecond then math.max(0, data.ratePerSecond) else 0
	return math.floor(elapsed * rate * EFFICIENCY), elapsed
end

-- Call on leave and in autosave so a crash does not pay for the time the player was online.
function OfflineEarnings.stamp(data: IdleData, now: number)
	data.lastOnline = now
end

return OfflineEarnings
```

On join, after loading: `local coins, seconds = OfflineEarnings.collect(profile.idle, os.time())`, add the coins through your currency module and show "You earned X while away (Y h)".

- Stamping in autosave matters: if a server crashes, the last stamp is at most one autosave old, so the player is not paid offline income for time they were actually playing.
- The rate is the server's saved value from their upgrades, never a number from the client.
- The cap is a design lever: a short cap brings players back more often, a long one is friendlier to casual players.

# Test
```lua
local now = 1700000000
local data = { lastOnline = now - 3600, ratePerSecond = 10 }
local coins, seconds = item.collect(data, now)
check("an hour away pays half rate", coins == 18000 and seconds == 3600)
check("timestamp is refreshed so it cannot be collected twice", item.collect(data, now) == 0)

local long = { lastOnline = now - 3 * 86400, ratePerSecond = 10 }
local capped, capSeconds = item.collect(long, now)
check("earnings are capped at 8 hours", capSeconds == 8 * 3600 and capped == 8 * 3600 * 10 * 0.5)

local future = { lastOnline = now + 5000, ratePerSecond = 10 }
check("a timestamp in the future pays nothing", item.collect(future, now) == 0)
check("first session pays nothing", item.collect({ lastOnline = 0, ratePerSecond = 10 }, now) == 0)
check("quick rejoins pay nothing", item.collect({ lastOnline = now - 30, ratePerSecond = 10 }, now) == 0)
check("a corrupt NaN rate pays nothing", item.collect({ lastOnline = now - 3600, ratePerSecond = 0 / 0 }, now) == 0)
```
