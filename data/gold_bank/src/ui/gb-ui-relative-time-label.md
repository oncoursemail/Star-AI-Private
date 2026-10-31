---
id: gb-ui-relative-time-label
category: ui-text
topics: relative time, time ago, os.date, DateTime, label formatting
source: original
---
# Request
My friends list and trade log show raw Unix timestamps. I want "just now", "5m ago", "3h ago", "2d ago", and an actual date for anything older than a week. What's a clean formatter?

# Answer
Take the difference between now and the timestamp in seconds and walk fixed thresholds; past a week, print a calendar date in UTC so all players see the same value. Future timestamps (clock skew) are treated as "just now" instead of showing negative times.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.TimeAgo
local TimeAgo = {}

local MINUTE, HOUR, DAY = 60, 3600, 86400

function TimeAgo.format(timestamp: number, now: number): string
	local diff = math.floor(now - timestamp)
	if diff < 45 then
		return "just now"
	elseif diff < HOUR then
		return string.format("%dm ago", math.max(1, diff // MINUTE))
	elseif diff < DAY then
		return string.format("%dh ago", diff // HOUR)
	elseif diff < 7 * DAY then
		return string.format("%dd ago", diff // DAY)
	end
	return os.date("!%Y-%m-%d", math.floor(timestamp)) :: string
end

function TimeAgo.label(label: TextLabel, timestamp: number)
	label.Text = TimeAgo.format(timestamp, DateTime.now().UnixTimestamp)
end

return TimeAgo
```

- Integer division (`//`) floors, so 59 minutes reads "59m ago" rather than rounding up to an hour early.
- Refresh visible labels once a minute; per-frame updates are wasted work for minute-level text.
- The ISO-style date is unambiguous across regions; switch to a localized date if you add translations.

# Test
```lua
local now = 1700000000
check("just now", item.format(now - 10, now) == "just now")
check("minutes", item.format(now - 300, now) == "5m ago")
check("floors to the lower unit", item.format(now - 3599, now) == "59m ago")
check("hours", item.format(now - 3 * 3600, now) == "3h ago")
check("days", item.format(now - 2 * 86400, now) == "2d ago")
check("old dates printed", item.format(0, now) == "1970-01-01")
check("future timestamps are just now", item.format(now + 500, now) == "just now")
```
