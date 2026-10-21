---
id: gb-data-reconcile-defaults
category: datastore-safety
topics: DataStore, defaults, reconcile, template, nil fields
source: original
---
# Request
Every time I add a new stat (like "settings.musicVolume") old players error because the field is nil in their saved data. How do I fill in missing fields from a default template without wiping what they already have?

# Answer
Reconcile the loaded data against a template recursively: copy in any key that is missing, recurse into nested tables, and replace values whose type no longer matches the template. Arrays are treated as single values so a player's list is never merged with the default list.

```lua
--!strict
-- ModuleScript: ServerScriptService.Reconcile
local Reconcile = {}

local function copy(value: any): any
	if type(value) ~= "table" then
		return value
	end
	local out = {}
	for k, v in value do
		out[k] = copy(v)
	end
	return out
end

local function isArray(t: { [any]: any }): boolean
	return next(t) == nil or t[1] ~= nil
end

-- Mutates data in place. Returns the paths it fixed, which is useful for logging.
function Reconcile.apply(data: { [string]: any }, template: { [string]: any }, path: string?): { string }
	local fixed: { string } = {}
	local prefix = if path then path .. "." else ""
	for key, default in template do
		local current = data[key]
		local here = prefix .. key
		if current == nil or type(current) ~= type(default) then
			data[key] = copy(default)
			table.insert(fixed, here)
		elseif type(default) == "table" and not isArray(default) then
			for _, nested in Reconcile.apply(current, default, here) do
				table.insert(fixed, nested)
			end
		end
	end
	return fixed
end

return Reconcile
```

Usage after a successful load:

```lua
--!strict
local ServerScriptService = game:GetService("ServerScriptService")
local Reconcile = require(ServerScriptService.Reconcile)

local TEMPLATE = {
	coins = 0,
	inventory = {},
	settings = { musicVolume = 0.5, showHints = true },
}

local function prepare(saved: { [string]: any }?): { [string]: any }
	local data = saved or {}
	Reconcile.apply(data, TEMPLATE)
	return data
end

return prepare
```

- Defaults are deep-copied, so two players never share the same `inventory` table by accident.
- Keys you removed from the template stay in old saves; delete them in a schema migration rather than here, so reconcile never destroys data.
- A type mismatch (a string where a number belongs) is reset to the default; log the returned paths once so you notice corrupt saves.

# Test
```lua
local template = { coins = 0, inventory = {}, settings = { musicVolume = 0.5, showHints = true }, tags = { "new" } }
local saved = { coins = 120, settings = { musicVolume = 0.1 }, tags = { "vip", "early" } }
local fixed = item.apply(saved, template)
check("existing values are kept", saved.coins == 120 and saved.settings.musicVolume == 0.1)
check("missing nested field is filled", saved.settings.showHints == true)
check("missing top-level table is added", type(saved.inventory) == "table")
check("arrays are not merged", #saved.tags == 2 and saved.tags[1] == "vip")
check("fixed paths are reported", #fixed == 2)

local other = item.apply({}, template)
saved.inventory.sword = 1
local fresh = {}
item.apply(fresh, template)
check("defaults are copied, not shared", fresh.inventory.sword == nil and #other == 4)

local wrongType = { coins = "lots" }
item.apply(wrongType, template)
check("wrong types are reset to the default", wrongType.coins == 0)
```
