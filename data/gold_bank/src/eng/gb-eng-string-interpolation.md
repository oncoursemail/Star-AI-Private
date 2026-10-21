---
id: gb-eng-string-interpolation
category: luau-syntax
topics: string interpolation, backticks, string.format, kill feed, escaping
source: original
---
# Request
My kill-feed messages are built with long `..` chains and `string.format("%s killed %s with %s (%d m)", ...)` and they are hard to read. I heard Luau has backtick strings. How do they work, and what are the gotchas (numbers, nil, literal braces)?

# Answer
Backtick strings evaluate each `{expression}` and call `tostring` on the result, so numbers, booleans and nil all work. Use `string.format` inside the braces when you need a fixed number of decimals, and `\{` for a literal brace.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.KillFeed
local KillFeed = {}

export type Kill = {
	killer: string,
	victim: string,
	weapon: string?,
	distance: number,
	streak: number,
}

function KillFeed.format(kill: Kill): string
	local weapon = kill.weapon or "bare hands"
	local line = `{kill.killer} eliminated {kill.victim} with {weapon} ({string.format("%.1f", kill.distance)} m)`
	if kill.streak >= 3 then
		line ..= ` - {kill.streak} in a row!`
	end
	return line
end

function KillFeed.richText(kill: Kill, killerColor: string): string
	-- RichText markup: the quotes around the color are part of the tag
	return `<font color="{killerColor}">{kill.killer}</font> > {kill.victim}`
end

function KillFeed.template(name: string): string
	return `\{{name}\}`
end

return KillFeed
```

- Any expression fits inside the braces, including calls and if-expressions: `{if n == 1 then "kill" else "kills"}`.
- `{nil}` prints `nil`, which is why the weapon falls back to `"bare hands"` first instead of being interpolated directly.
- Unlike `print "hi"`, an interpolated string cannot be passed to a call without parentheses; always write the parentheses.
- For player-typed text shown to others, filter it with TextService before it reaches the kill feed.

# Test
```lua
local msg = item.format({ killer = "Ana", victim = "Bo", weapon = "Bow", distance = 42.345, streak = 1 })
check("basic message", msg == "Ana eliminated Bo with Bow (42.3 m)")
local noWeapon = item.format({ killer = "Ana", victim = "Cy", distance = 3, streak = 4 })
check("nil weapon falls back and streak appended", noWeapon == "Ana eliminated Cy with bare hands (3.0 m) - 4 in a row!")
check("rich text tag", item.richText({ killer = "Ana", victim = "Bo", distance = 1, streak = 0 }, "#ff0000") == '<font color="#ff0000">Ana</font> > Bo')
check("escaped braces", item.template("score") == "{score}")
```
