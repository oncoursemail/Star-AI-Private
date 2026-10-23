The original code, unchanged.

```lua
-- TimeFormat: text for the round timer, the lobby countdown and the match history screen.
local TimeFormat = {}

-- 65 -> "1:05"
function TimeFormat.clock(seconds)
	local whole = math.floor(seconds)
	local minutes = whole // 60
	local rest = whole % 60
	return minutes .. ":" .. rest
end

-- 125 -> "2 min 5 s"
function TimeFormat.words(seconds)
	local whole = math.floor(seconds)
	local minutes = whole // 60
	local rest = whole % 60
	if minutes == 0 then
		return rest .. " s"
	end
	if rest == 0 then
		return minutes .. " min"
	end
	return minutes .. " min " .. rest .. " s"
end

-- "1:05" -> 65; nil for text that is not a clock.
function TimeFormat.parse(text)
	local m, s = string.match(text, "^(%d+):(%d%d)$")
	if m == nil then
		return nil
	end
	return tonumber(m) * 60 + tonumber(s)
end

-- Countdown text with tenths in the last ten seconds: "9.4".
function TimeFormat.countdown(seconds)
	if seconds < 10 then
		return string.format("%.1f", math.max(0, seconds))
	end
	return TimeFormat.clock(seconds)
end

function TimeFormat.ago(seconds)
	if seconds < 60 then
		return "just now"
	end
	return TimeFormat.words(seconds) .. " ago"
end

return TimeFormat
```
