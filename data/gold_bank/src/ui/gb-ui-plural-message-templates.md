---
id: gb-ui-plural-message-templates
category: ui-text
topics: pluralisation, message templates, localization-friendly, string building, labels
source: original
---
# Request
My UI says "1 players online" and "You found 1 eggs". I fixed it with `if n == 1` checks all over the place, but I'm also planning translations and heard string concatenation like `"You have " .. n .. " coins"` is bad for that. What's a better pattern?

# Answer
Keep whole sentences as templates with named placeholders and pick the form by a plural category, never by gluing pieces together. Word order then lives inside each template, so a translation can put the number wherever its grammar needs. The rule function is per language; English needs only "one" and "other".

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Messages
local Messages = {}

export type Forms = { one: string, other: string, zero: string? }

local CATALOG: { [string]: Forms } = {
	playersOnline = { zero = "Nobody else is online", one = "{count} player online", other = "{count} players online" },
	eggsFound = { one = "You found {count} egg in {zone}", other = "You found {count} eggs in {zone}" },
}

function Messages.category(count: number): string
	if count == 1 then
		return "one"
	end
	return "other"
end

function Messages.format(key: string, count: number, args: { [string]: string | number }?): string
	local forms = CATALOG[key]
	assert(forms ~= nil, "unknown message " .. key)
	local template: string = forms.other
	if count == 0 and forms.zero ~= nil then
		template = forms.zero
	elseif Messages.category(count) == "one" then
		template = forms.one
	end
	return (string.gsub(template, "{(%w+)}", function(name: string): string
		if name == "count" then
			return tostring(count)
		end
		local value = args and args[name]
		return if value ~= nil then tostring(value) else "{" .. name .. "}"
	end))
end

return Messages
```

- The optional `zero` form allows friendlier copy ("Nobody else is online") instead of "0 players".
- Other languages need more categories (Russian and Polish have three or four); keep `category` swappable per locale and extend `Forms` with the extra keys.
- Format numbers (separators, abbreviations) before passing them in as args if the count shown differs from the one used for the plural choice.

# Test
```lua
check("singular", item.format("playersOnline", 1) == "1 player online")
check("plural", item.format("playersOnline", 5) == "5 players online")
check("zero form", item.format("playersOnline", 0) == "Nobody else is online")
check("named args in any order", item.format("eggsFound", 3, { zone = "Meadow" }) == "You found 3 eggs in Meadow")
check("zero falls back to other when no zero form", item.format("eggsFound", 0, { zone = "Cave" }) == "You found 0 eggs in Cave")
check("unknown key errors", not pcall(item.format, "nope", 1))
```
