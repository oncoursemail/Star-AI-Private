---
id: gb-eng-format-duration
category: engineering-algorithm
topics: time formatting, countdown, duration, clock display, os.date
source: original
---
# Request
I need to show durations in three ways: a round timer as `M:SS` (or `H:MM:SS` past an hour), a compact "2d 5h" for event countdowns, and "3 minutes ago" for a last-seen label. How should I write these so they handle zero, negative and fractional seconds?

# Answer
Work in whole seconds (floor once at the top, clamp negatives to zero), split into units with `//` and `%`, and format each style from those parts. Do not use `os.date` for durations: it formats calendar times and is affected by the time zone.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Duration
local Duration = {}

local function parts(seconds: number): (number, number, number, number)
	local s = math.max(0, math.floor(seconds))
	return s // 86400, s % 86400 // 3600, s % 3600 // 60, s % 60
end

function Duration.clock(seconds: number): string
	local days, hours, minutes, secs = parts(seconds)
	hours += days * 24
	if hours > 0 then
		return string.format("%d:%02d:%02d", hours, minutes, secs)
	end
	return string.format("%d:%02d", minutes, secs)
end

function Duration.compact(seconds: number, maxUnits: number?): string
	local days, hours, minutes, secs = parts(seconds)
	local limit = maxUnits or 2
	local out: { string } = {}
	for _, unit in { { days, "d" }, { hours, "h" }, { minutes, "m" }, { secs, "s" } } do
		local amount, label = unit[1] :: number, unit[2] :: string
		if amount > 0 and #out < limit then
			table.insert(out, `{amount}{label}`)
		end
	end
	return if #out == 0 then "0s" else table.concat(out, " ")
end

function Duration.ago(seconds: number): string
	local s = math.max(0, math.floor(seconds))
	local function plural(n: number, word: string): string
		return `{n} {word}{if n == 1 then "" else "s"} ago`
	end
	if s < 60 then
		return "just now"
	elseif s < 3600 then
		return plural(s // 60, "minute")
	elseif s < 86400 then
		return plural(s // 3600, "hour")
	end
	return plural(s // 86400, "day")
end

return Duration
```

- Floor once at the top: a countdown at 59.9 s shows `0:59`, never `0:60` from rounding each part separately.
- `compact` skips zero units and stops at `maxUnits`, so 1 day 0 hours 5 minutes shows as "1d 5m" with the default of two units.
- For a countdown to an event, compute `endUnix - workspace:GetServerTimeNow()` so every client agrees regardless of its local clock.

# Test
```lua
check("clock minutes", item.clock(65) == "1:05" and item.clock(0) == "0:00")
check("clock hours", item.clock(3725) == "1:02:05")
check("clock days fold into hours", item.clock(90061) == "25:01:01")
check("clock floors fractions", item.clock(59.9) == "0:59")
check("negative clamps", item.clock(-5) == "0:00" and item.compact(-5) == "0s")
check("compact two units", item.compact(2 * 86400 + 5 * 3600 + 30) == "2d 5h")
check("compact skips zero units", item.compact(86400 + 300) == "1d 5m")
check("compact more units", item.compact(3661, 3) == "1h 1m 1s")
check("ago phrases", item.ago(10) == "just now" and item.ago(60) == "1 minute ago" and item.ago(7300) == "2 hours ago" and item.ago(3 * 86400) == "3 days ago")
```
