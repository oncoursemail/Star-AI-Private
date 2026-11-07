---
id: gb-ui-currency-thousands-separator
category: ui-text
topics: number formatting, thousands separator, currency label, locale, LocalizationService
source: original
---
# Request
For the shop prices and the bank balance I want full numbers with separators (12,450,000), not abbreviations, and German players expect dots instead of commas. My gsub trick puts a comma at the front for numbers like 450,000. Can you write it properly?

# Answer
Format the whole part as digits, take the first group of 1-3 digits, then every following group of exactly three, and join them with the separator. Choose the separator from the player's locale (`LocalizationService.RobloxLocaleId`) with a small table, defaulting to a comma.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.NumberText
local NumberText = {}

local SEPARATORS: { [string]: string } = {
	["de-de"] = ".",
	["es-es"] = ".",
	["pt-br"] = ".",
	["it-it"] = ".",
	["id-id"] = ".",
	["fr-fr"] = "\u{202F}",
}

function NumberText.separatorFor(localeId: string): string
	return SEPARATORS[string.lower(localeId)] or ","
end

function NumberText.grouped(value: number, separator: string?): string
	if value ~= value or value == math.huge or value == -math.huge then
		return "0"
	end
	local sep = separator or ","
	local sign = if value < 0 then "-" else ""
	local digits = string.format("%d", math.floor(math.abs(value)))
	local head = #digits % 3
	if head == 0 then
		head = 3
	end
	local parts = { string.sub(digits, 1, head) }
	for i = head + 1, #digits, 3 do
		table.insert(parts, string.sub(digits, i, i + 2))
	end
	return sign .. table.concat(parts, sep)
end

return NumberText
```

```lua
--!strict
-- LocalScript: balance label
local LocalizationService = game:GetService("LocalizationService")
local NumberText = require(game:GetService("ReplicatedStorage"):WaitForChild("NumberText"))

local separator = NumberText.separatorFor(LocalizationService.RobloxLocaleId)

local function showBalance(label: TextLabel, coins: number)
	label.Text = NumberText.grouped(coins, separator)
end

return showBalance
```

- French uses a narrow no-break space so the number never wraps across two lines.
- `%d` with `math.floor` always prints plain digits, while `tostring` switches to exponent form (such as `1e+16`) for very large balances.
- The label is display only; the server stores and compares the integer.

# Test
```lua
check("millions", item.grouped(12450000) == "12,450,000")
check("no leading separator", item.grouped(450000) == "450,000" and item.grouped(999) == "999")
check("one leading digit", item.grouped(1000) == "1,000")
check("negative and fractional", item.grouped(-1234.9) == "-1,234")
check("German uses dots", item.grouped(1234567, item.separatorFor("de-DE")) == "1.234.567")
check("unknown locale falls back to comma", item.separatorFor("en-us") == ",")
check("NaN is safe", item.grouped(0 / 0) == "0")
```
