---
id: gb-ui-search-filter-debounce
category: ui-interaction
topics: TextBox, search filter, debounce, empty state, string.find plain
source: original
---
# Request
My catalogue search filters 800 items on every keystroke and rebuilds the list each time, so typing feels laggy. Also, typing characters like "(" or "%" throws a "malformed pattern" error. How do I fix both?

# Answer
Debounce: on each text change, schedule the filter a short moment later and let a newer keystroke cancel the older schedule, so the list rebuilds once when the player pauses. Match with `string.find(name, query, 1, true)`: the `plain` flag turns off pattern syntax, so any character is safe. Show an explicit empty state when nothing matches.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.SearchFilter
local SearchFilter = {}

function SearchFilter.filter(names: { string }, query: string): { string }
	local q = string.lower((string.gsub(query, "^%s+", "")))
	if q == "" then
		return names
	end
	local out = {}
	for _, name in names do
		if string.find(string.lower(name), q, 1, true) then
			table.insert(out, name)
		end
	end
	return out
end

function SearchFilter.bind(box: TextBox, names: { string }, render: (results: { string }) -> (), emptyLabel: TextLabel, delaySeconds: number?): RBXScriptConnection
	local pause = delaySeconds or 0.15
	local version = 0

	local function run()
		local results = SearchFilter.filter(names, box.Text)
		emptyLabel.Visible = #results == 0
		emptyLabel.Text = "No items match \"" .. box.Text .. "\""
		render(results)
	end

	run()
	return box:GetPropertyChangedSignal("Text"):Connect(function()
		version += 1
		local mine = version
		task.delay(pause, function()
			if mine == version then
				run()
			end
		end)
	end)
end

return SearchFilter
```

- The version counter is the debounce: only the last scheduled run still matches it when its delay ends.
- Lower-casing both sides gives case-insensitive search without patterns.
- An empty query returns the full list unchanged, so clearing the box restores everything at once.

# Test
```lua
local names = { "Fire Sword", "Ice Sword", "Fire Staff", "Shield (Gold)" }
check("case-insensitive match", #item.filter(names, "fire") == 2)
check("pattern characters are literal", #item.filter(names, "(gold") == 1 and #item.filter(names, "%") == 0)
check("empty query returns everything", #item.filter(names, "  ") == 4)
local box = Instance.new("TextBox")
box.Text = ""
local empty = Instance.new("TextLabel")
local renders = 0
local lastCount = 0
local conn = item.bind(box, names, function(results)
	renders += 1
	lastCount = #results
end, empty, 0.15)
check("initial render shows all", renders == 1 and lastCount == 4)
box.Text = "s"
box.Text = "sw"
box.Text = "swo"
__advance(0.2)
check("one render after typing pauses", renders == 2 and lastCount == 2)
box.Text = "zzz"
__advance(0.2)
check("empty state shown", lastCount == 0 and empty.Visible)
conn:Disconnect()
```
