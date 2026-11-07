---
id: gb-ui-abbreviate-big-numbers
category: ui-text
topics: number formatting, abbreviation, K M B suffix, simulator, label
source: original
---
# Request
My simulator's coin label shows numbers like 18493021774 and overflows. I want 18.4B style abbreviations, but my current version shows "1000.0K" for 999,999 and "1.0K" instead of "1K". Can you write a correct formatter?

# Answer
Divide by 1000 while the value is at least 1000 and a larger suffix exists, then truncate (not round) to the wanted decimals so a value never displays as the next tier's "1000". Strip a trailing ".0" and handle the sign, NaN and infinity separately.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Abbreviate
local Abbreviate = {}

local SUFFIXES = { "", "K", "M", "B", "T", "Qa", "Qi" }

function Abbreviate.format(value: number, decimals: number?): string
	if value ~= value then
		return "0"
	elseif value == math.huge or value == -math.huge then
		return if value > 0 then "inf" else "-inf"
	end
	local places = decimals or 1
	local sign = if value < 0 then "-" else ""
	local n = math.abs(value)
	local tier = 1
	while n >= 1000 and tier < #SUFFIXES do
		n /= 1000
		tier += 1
	end
	if tier == 1 then
		return sign .. tostring(math.floor(n))
	end
	local factor = 10 ^ places
	local truncated = math.floor(n * factor + 1e-9) / factor
	local text = string.format("%." .. places .. "f", truncated)
	if places > 0 then
		text = string.gsub(text, "0+$", "")
		text = string.gsub(text, "%.$", "")
	end
	return sign .. text .. SUFFIXES[tier]
end

return Abbreviate
```

- Truncation keeps the label honest: a player with 999,999 coins has not got a million, so it reads "999.9K".
- The `1e-9` nudge absorbs float error: 1,150 with two decimals computes `1.15 * 100`, which is 114.99999999999999 and would otherwise read "1.14K".
- Only the label is abbreviated; the server keeps the exact integer and the shop compares against that.

# Test
```lua
check("small numbers stay whole", item.format(999) == "999" and item.format(12.7) == "12")
check("thousands", item.format(1234) == "1.2K")
check("no rounding up into the next tier", item.format(999999) == "999.9K")
check("trailing zero stripped", item.format(1000) == "1K" and item.format(2000000) == "2M")
check("billions", item.format(18493021774) == "18.4B")
check("negative", item.format(-2500) == "-2.5K")
check("two decimals", item.format(1234567, 2) == "1.23M")
check("float error does not drop a digit", item.format(1150, 2) == "1.15K")
check("zero decimals keeps integer zeros", item.format(10000, 0) == "10K")
check("NaN shows zero", item.format(0 / 0) == "0")
```
