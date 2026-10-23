---
id: gb-ui-translator-fallback
category: ui-text
topics: LocalizationService, GetTranslatorForPlayerAsync, FormatByKey, fallback, localization
source: original
---
# Request
I'm adding translations with a localization table. Sometimes `GetTranslatorForPlayerAsync` errors when the player joins and my whole shop UI script breaks. How should I load the translator and format strings like "Buy for {price}" safely?

# Answer
Load the translator in `pcall` with a few retries and backoff; if it never arrives, use your source-language table so the UI still works. Wrap `FormatByKey` too, since a missing key errors. Expose one `t(key, args)` function for the rest of your UI.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Localize
local LocalizationService = game:GetService("LocalizationService")

local Localize = {}

export type Args = { [string]: string | number }
export type T = (key: string, args: Args?) -> string

local SOURCE: { [string]: string } = {
	["Shop.Buy"] = "Buy for {price}",
	["Shop.Owned"] = "Owned",
	["Shop.NotEnough"] = "You need {missing} more coins",
}

function Localize.fill(template: string, args: Args?): string
	return (string.gsub(template, "{(%w+)}", function(name: string): string
		local value = args and args[name]
		return if value ~= nil then tostring(value) else "{" .. name .. "}"
	end))
end

local function fallback(key: string, args: Args?): string
	local template = SOURCE[key]
	return if template then Localize.fill(template, args) else key
end

function Localize.load(player: Player, attempts: number?): T
	local translator: any = nil
	for attempt = 1, attempts or 3 do
		local ok, result = pcall(LocalizationService.GetTranslatorForPlayerAsync, LocalizationService, player)
		if ok then
			translator = result
			break
		end
		task.wait(attempt)
	end
	if translator == nil then
		return fallback
	end
	return function(key: string, args: Args?): string
		local ok, text = pcall(translator.FormatByKey, translator, key, args or {})
		if ok and type(text) == "string" then
			return text
		end
		return fallback(key, args)
	end
end

return Localize
```

```lua
--!strict
-- LocalScript: shop button text
local Players = game:GetService("Players")
local Localize = require(game:GetService("ReplicatedStorage"):WaitForChild("Localize"))

local t = Localize.load(Players.LocalPlayer)

local function setBuyLabel(button: TextButton, price: number)
	button.AutomaticSize = Enum.AutomaticSize.X
	button.Text = t("Shop.Buy", { price = price })
end

return setBuyLabel
```

- Keep the keys and English text in the localization table too; the SOURCE table is only the safety net.
- Unknown placeholders are left as `{name}`, which makes a missing argument easy to spot in testing.
- Buttons with `AutomaticSize = X` grow for German or Portuguese, which often run 30% longer than English.

# Test
```lua
local LS = game:GetService("LocalizationService")
local player = __makePlayer(1, "Lena")
check("fill named args", item.fill("Buy for {price}", { price = 50 }) == "Buy for 50")
check("unknown placeholder kept", item.fill("Hi {name}", {}) == "Hi {name}")
LS.GetTranslatorForPlayerAsync = function()
	error("HTTP 503")
end
local t
task.spawn(function()
	t = item.load(player, 2)
end)
__advance(5)
check("falls back to source text", t ~= nil and t("Shop.Buy", { price = 75 }) == "Buy for 75")
check("unknown keys show the key", t("Shop.Missing") == "Shop.Missing")
LS.GetTranslatorForPlayerAsync = function()
	return { FormatByKey = function(_, key, args)
		if key == "Shop.Buy" then
			return "Kaufen für " .. tostring(args.price)
		end
		error("missing key")
	end }
end
local de = item.load(player)
check("translator used when available", de("Shop.Buy", { price = 10 }) == "Kaufen für 10")
check("missing translation falls back", de("Shop.Owned") == "Owned")
```
