---
id: gb-ui-richtext-escape-chat
category: ui-text
topics: RichText, escaping, user text, font color, injection
source: original
---
# Request
My kill feed uses RichText so the player names are coloured, but someone named their pet `<font size="90">` and it blew up the whole feed. How do I safely put player-provided text inside RichText?

# Answer
Escape the five markup characters in every piece of user text before it goes between tags, and build the tags only from values you control. Keep the escaping in one helper so no call site can forget it.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.RichText
local RichText = {}

local ESCAPES: { [string]: string } = {
	["&"] = "&amp;",
	["<"] = "&lt;",
	[">"] = "&gt;",
	['"'] = "&quot;",
	["'"] = "&apos;",
}

function RichText.escape(text: string): string
	return (string.gsub(text, "[&<>\"']", ESCAPES))
end

function RichText.colored(text: string, color: Color3): string
	return string.format('<font color="#%s">%s</font>', color:ToHex(), RichText.escape(text))
end

function RichText.bold(text: string): string
	return "<b>" .. RichText.escape(text) .. "</b>"
end

function RichText.feedLine(killer: string, killerColor: Color3, victim: string, victimColor: Color3, weapon: string): string
	return string.format("%s  %s  %s", RichText.colored(killer, killerColor), RichText.bold(weapon),
		RichText.colored(victim, victimColor))
end

return RichText
```

- `&` must be in the set, or a name typed as `&lt;b&gt;` would display as `<b>` instead of what the player typed.
- Wrapping `gsub` in parentheses drops its second return value (the count), so the function returns a single string.
- Escaping is not filtering: names and pet names typed by players still go through `TextService:FilterStringAsync` on the server before anyone else sees them.
- Set `RichText = true` on the label; without it the escapes show up literally.

# Test
```lua
check("tags are neutralised", item.escape('<font size="90">') == "&lt;font size=&quot;90&quot;&gt;")
check("ampersand escaped first", item.escape("&lt;") == "&amp;lt;")
check("plain text unchanged", item.escape("Builder_42") == "Builder_42")
local line = item.feedLine("<b>Evil", Color3.new(1, 0, 0), "Bob's", Color3.new(0, 0, 1), "Sword")
check("killer colour tag is ours", line:sub(1, 22) == '<font color="#FF0000">')
check("user markup cannot open tags", line:find("<b>Evil", 1, true) == nil and line:find("&lt;b&gt;Evil", 1, true) ~= nil)
check("apostrophe escaped", line:find("Bob&apos;s", 1, true) ~= nil)
```
