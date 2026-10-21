---
id: gb-eng-unknown-json-decode
category: luau-typing
topics: unknown type, avoid any, JSONDecode, validation, typed records
source: original
---
# Request
I load level layouts from a JSON string (stored in a StringValue made by our level editor) with `HttpService:JSONDecode`. The result is `any`, so I index it freely and it blew up on a malformed level. How do I get from that `any` to a properly typed table without just casting?

# Answer
Assign the decoded value to `unknown` immediately, then validate it field by field into a typed record. Collect errors instead of stopping at the first one so the level editor can show every problem in a broken file.

```lua
--!strict
-- ModuleScript: ServerScriptService.LevelLoader
local HttpService = game:GetService("HttpService")

export type Spawner = { enemy: string, x: number, z: number, count: number }
export type Level = { name: string, timeLimit: number, spawners: { Spawner } }

local LevelLoader = {}

local function num(t: { [unknown]: unknown }, key: string, errors: { string }, where: string): number
	local v = t[key]
	if type(v) ~= "number" or v ~= v then
		table.insert(errors, `{where}.{key} must be a number`)
		return 0
	end
	return v
end

function LevelLoader.decode(json: string): (Level?, { string })
	local errors: { string } = {}
	local ok, decoded = pcall(HttpService.JSONDecode, HttpService, json)
	if not ok then
		return nil, { "not valid JSON" }
	end
	local raw: unknown = decoded
	if type(raw) ~= "table" then
		return nil, { "top level must be an object" }
	end
	local root = raw :: { [unknown]: unknown }

	local name = root.name
	if type(name) ~= "string" or name == "" then
		table.insert(errors, "name must be a non-empty string")
	end
	local timeLimit = num(root, "timeLimit", errors, "level")

	local spawners: { Spawner } = {}
	local list = root.spawners
	if type(list) ~= "table" then
		table.insert(errors, "spawners must be a list")
	else
		for i, entry in list :: { unknown } do
			local where = `spawners[{i}]`
			if type(entry) ~= "table" then
				table.insert(errors, `{where} must be an object`)
				continue
			end
			local e = entry :: { [unknown]: unknown }
			local enemy = e.enemy
			if type(enemy) ~= "string" then
				table.insert(errors, `{where}.enemy must be a string`)
				continue
			end
			local count = num(e, "count", errors, where)
			table.insert(spawners, { enemy = enemy, x = num(e, "x", errors, where), z = num(e, "z", errors, where), count = math.clamp(math.floor(count), 1, 50) })
		end
	end

	if #errors > 0 or type(name) ~= "string" then
		return nil, errors
	end
	return { name = name, timeLimit = timeLimit, spawners = spawners }, errors
end

return LevelLoader
```

- `unknown` is the honest type for decoded data: the analyzer refuses `root.spawners[1].enemy` until each step has been checked, while `any` would accept it and crash at runtime.
- `pcall(HttpService.JSONDecode, HttpService, json)` turns malformed text into an error message instead of a thrown error.
- Counts are floored and clamped so a typo like `"count": 5000` cannot flood the map.

# Test
```lua
local good = '{"name":"Caves","timeLimit":120,"spawners":[{"enemy":"Bat","x":4,"z":-2,"count":3}]}'
local level, errs = item.decode(good)
check("valid level decodes", level ~= nil and #errs == 0 and level.spawners[1].enemy == "Bat" and level.timeLimit == 120)
local bad = '{"name":"","timeLimit":"soon","spawners":[{"enemy":5},{"enemy":"Rat","x":1,"z":2,"count":9000}]}'
local none, problems = item.decode(bad)
check("invalid level rejected", none == nil)
check("all problems reported", #problems == 3)
check("malformed json handled", select(2, item.decode("{oops")) [1] == "not valid JSON")
check("non-object rejected", item.decode("[1,2]") == nil)
local clamped = item.decode('{"name":"A","timeLimit":1,"spawners":[{"enemy":"Rat","x":1,"z":2,"count":9000}]}')
check("count clamped", clamped ~= nil and clamped.spawners[1].count == 50)
```
