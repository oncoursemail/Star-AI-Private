---
id: gb-ui-display-name-truncate-utf8
category: ui-overflow
topics: utf8, truncation, display names, ellipsis, string.sub
source: original
---
# Request
I shorten long display names for my party list with `name:sub(1, 12) .. "..."`. Some players have names with accented letters or non-Latin scripts and those show up with a broken character at the end. How do I cut names safely?

# Answer
`string.sub` counts bytes, and many characters take two to four bytes in UTF-8, so a cut can land mid-character. Count and cut by code points with `utf8.len` and `utf8.offset`, add a single ellipsis character, and fall back to a byte cut only if the string is not valid UTF-8.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.ShortName
local ShortName = {}

local ELLIPSIS = "\u{2026}"

function ShortName.cut(text: string, maxChars: number): string
	assert(maxChars >= 1, "maxChars must be at least 1")
	local length = utf8.len(text)
	if length == nil then
		return string.sub(text, 1, maxChars)
	end
	if length <= maxChars then
		return text
	end
	-- Byte index where the code point after the kept ones starts.
	local stop = utf8.offset(text, maxChars)
	assert(stop ~= nil)
	return string.sub(text, 1, stop - 1) .. ELLIPSIS
end

return ShortName
```

```lua
--!strict
local ShortName = require(game:GetService("ReplicatedStorage"):WaitForChild("ShortName"))

local function setMemberName(label: TextLabel, player: Player)
	label.Text = ShortName.cut(player.DisplayName, 14)
	label.TextTruncate = Enum.TextTruncate.AtEnd
end

return setMemberName
```

- The kept text is `maxChars - 1` code points plus the ellipsis, so the result never exceeds `maxChars` characters.
- Combining accents count as separate code points; the worst case is an accent dropped from the last letter, never invalid text.
- `TextTruncate = AtEnd` is a second safety net for wide glyphs that need more room than the character count suggests.

# Test
```lua
check("short names untouched", item.cut("Ava", 10) == "Ava")
check("ascii cut with ellipsis", item.cut("SuperLongDisplayName", 8) == "SuperLo\u{2026}")
local cut = item.cut("Ünïcødé_Wårrïør", 6)
check("multibyte names stay valid", utf8.len(cut) == 6)
check("cut keeps leading characters", cut:sub(1, #"Ünïcø") == "Ünïcø")
check("exact length kept", item.cut("Ünïcødé", 7) == "Ünïcødé")
check("invalid bytes fall back to byte cut", item.cut("\255\254abc", 2) == "\255\254")
```
