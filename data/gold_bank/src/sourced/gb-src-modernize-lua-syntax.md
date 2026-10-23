---
id: gb-src-modernize-lua-syntax
category: luau-syntax
topics: string interpolation, if-then-else expression, compound assignment, generalized iteration, floor division, continue
source: adapted
source_id: luau-site
source_path: src/content/docs/getting-started/syntax.md
source_commit: 41db794d9ee6e56a17b399f8a4520b92301fee59
---
# Request
I copied this leaderboard formatter from an old Lua 5.1 tutorial. It works, but it looks clunky. Can you rewrite it with modern Luau syntax?

```lua
function formatBoard(entries)
	local lines = {}
	for i, e in ipairs(entries) do
		if e.score ~= nil then
			local minutes = math.floor(e.seconds / 60)
			local secs = e.seconds % 60
			local medal
			if i == 1 then medal = "[1st] " else medal = "" end
			e.score = e.score + 0
			table.insert(lines, medal .. e.name .. ": " .. tostring(e.score) .. " (" .. minutes .. "m " .. secs .. "s)")
		end
	end
	return table.concat(lines, "\n")
end
```

# Answer
Use Luau's additions: string interpolation with backticks, `if ... then ... else` expressions, `//` floor division, `continue` to skip entries, generalized iteration without `ipairs`, a local function instead of a global, and type annotations.

```lua
--!strict
export type Entry = { name: string, score: number?, seconds: number }

local function formatBoard(entries: { Entry }): string
	local lines = {}
	local rank = 0
	for _, entry in entries do
		local score = entry.score
		if score == nil then
			continue
		end
		rank += 1
		local minutes = entry.seconds // 60
		local secs = entry.seconds % 60
		local medal = if rank == 1 then "[1st] " else ""
		table.insert(lines, `{medal}{entry.name}: {score} ({minutes}m {secs}s)`)
	end
	return table.concat(lines, "\n")
end

return formatBoard
```

- Backtick strings call `tostring` on each `{expression}`, replacing the chain of `..` and explicit conversions.
- `continue` skips entries without a score instead of nesting the loop body in an `if`.
- The medal now follows the shown rank, so a missing first entry no longer means nobody gets "[1st]".
- `local function` avoids writing a global, which strict mode reports.

# Test
```lua
local board = item({
	{ name = "Ghost", score = nil, seconds = 5 },
	{ name = "Ana", score = 120, seconds = 125 },
	{ name = "Bo", score = 90, seconds = 59 },
})
local lines = string.split(board, "\n")
check("entries without a score skipped", #lines == 2)
check("first shown entry gets the medal", lines[1] == "[1st] Ana: 120 (2m 5s)")
check("others have no medal", lines[2] == "Bo: 90 (0m 59s)")
check("empty input gives empty string", item({}) == "")
```
