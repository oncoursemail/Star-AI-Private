---
id: gb-src-richtext-kill-feed
category: ui-text
topics: RichText, escaping, font color tags, TextLabel, kill feed, player names
source: adapted
source_id: creator-docs
source_path: content/en-us/ui/rich-text.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
My kill feed uses RichText to color names by team: `label.Text = '<font color="#ff0000">' .. killer.DisplayName .. '</font> eliminated ' .. victim.DisplayName`. Some names break the formatting and once a player's name with `<` made the whole line show raw tags. How do I build rich text safely?

# Answer
Escape every piece of user text before inserting it into markup: `&`, `<`, `>`, `"` and `'` must become entities, otherwise they are read as tags. Build the colored spans with a helper that escapes the text and formats the color as hex.

```lua
--!strict
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

function RichText.killLine(killerName: string, killerColor: Color3, victimName: string, victimColor: Color3, weapon: string): string
	return `{RichText.colored(killerName, killerColor)} <b>[{RichText.escape(weapon)}]</b> {RichText.colored(victimName, victimColor)}`
end

return RichText
```

Usage: `label.RichText = true; label.Text = RichText.killLine(killer.DisplayName, killer.TeamColor.Color, victim.DisplayName, victim.TeamColor.Color, "Sword")`.

- `string.gsub` replaces each character in one pass, so the `&` inside the entities it writes is never escaped again.
- The outer parentheses around `string.gsub` drop its second return value (the match count).
- Escape any text you did not write yourself (names, pet names, clan tags); escaping only fixes formatting, so player-written text still needs `TextService` filtering.

# Test
```lua
check("markup characters escaped", item.escape("<b>&\"'") == "&lt;b&gt;&amp;&quot;&apos;")
check("plain text unchanged", item.escape("Hina") == "Hina")
local span = item.colored("A<B", Color3.fromRGB(255, 0, 0))
check("colored span escapes and uses hex", span == '<font color="#FF0000">A&lt;B</font>')
local line = item.killLine("Ana", Color3.fromRGB(0, 0, 255), "Bo>", Color3.fromRGB(0, 255, 0), "Sword")
check("kill line composed", string.find(line, "[Sword]", 1, true) ~= nil and string.find(line, "Bo&gt;", 1, true) ~= nil)
```
