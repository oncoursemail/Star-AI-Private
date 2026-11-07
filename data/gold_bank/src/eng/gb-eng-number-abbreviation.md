---
id: gb-eng-number-abbreviation
category: engineering-algorithm
topics: number formatting, abbreviation, suffixes, simulator, rounding
source: original
---
# Request
My simulator's coin counter needs 1.2K / 3.45M / 7B style numbers and comma-separated full values for the shop tooltip. My version shows things like "1000K" instead of "1M" and breaks on negatives. Can you write both formatters?

# Answer
Pick the suffix from the exponent, round to the wanted decimals, and if rounding pushed the value to 1000 move up one suffix (the "1000K" bug). Trailing zeros are stripped so 2.50K shows as 2.5K. The comma formatter works on the integer digits as a string.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.NumberFormat
local SUFFIXES = { "", "K", "M", "B", "T", "Qa", "Qi", "Sx", "Sp", "Oc", "No", "Dc" }

local NumberFormat = {}

local function trimZeros(s: string): string
	if string.find(s, "%.") then
		s = string.gsub(s, "0+$", "")
		s = string.gsub(s, "%.$", "")
	end
	return s
end

function NumberFormat.abbreviate(value: number, decimals: number?): string
	if value ~= value then
		return "0"
	end
	local places = decimals or 2
	local sign = if value < 0 then "-" else ""
	local n = math.abs(value)
	if n < 1000 then
		return sign .. trimZeros(string.format(`%.{places}f`, math.floor(n * 10 ^ places) / 10 ^ places))
	end
	local tier = math.min(math.floor(math.log10(n) / 3), #SUFFIXES - 1)
	local scaled = n / 10 ^ (tier * 3)
	local factor = 10 ^ places
	scaled = math.floor(scaled * factor + 0.5) / factor
	if scaled >= 1000 and tier < #SUFFIXES - 1 then
		tier += 1
		scaled /= 1000
	end
	return sign .. trimZeros(string.format(`%.{places}f`, scaled)) .. SUFFIXES[tier + 1]
end

function NumberFormat.commas(value: number): string
	local sign = if value < 0 then "-" else ""
	local digits = string.format("%d", math.floor(math.abs(value)))
	local formatted = string.reverse((string.gsub(string.reverse(digits), "(%d%d%d)", "%1,")))
	if string.sub(formatted, 1, 1) == "," then
		formatted = string.sub(formatted, 2)
	end
	return sign .. formatted
end

return NumberFormat
```

- `999999` rounds to `1000.00K`, which the post-rounding check turns into `1M`.
- Values below 1000 are floored, not rounded, so a player with 9.999 coins never sees "10" and then fails to buy a 10-coin item.
- Numbers above about 2^53 lose integer precision in Luau, so `commas` on huge values shows rounded digits; switch big economies to the abbreviated form only.

# Test
```lua
check("small numbers", item.abbreviate(0) == "0" and item.abbreviate(999) == "999")
check("thousands", item.abbreviate(1200) == "1.2K" and item.abbreviate(1000) == "1K")
check("millions with decimals", item.abbreviate(3456789) == "3.46M")
check("rollover fixed", item.abbreviate(999999) == "1M" and item.abbreviate(999999999) == "1B")
check("negative", item.abbreviate(-25000) == "-25K")
check("decimals option", item.abbreviate(1234567, 1) == "1.2M")
check("small value floored", item.abbreviate(9.999) == "9.99")
check("NaN safe", item.abbreviate(0 / 0) == "0")
check("commas", item.commas(1234567) == "1,234,567" and item.commas(100) == "100" and item.commas(100000) == "100,000")
check("commas negative", item.commas(-9876543) == "-9,876,543")
```
