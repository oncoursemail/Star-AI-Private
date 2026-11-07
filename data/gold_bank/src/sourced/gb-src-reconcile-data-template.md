---
id: gb-src-reconcile-data-template
category: datastore-safety
topics: player data, template, reconcile, deep copy, schema migration, DataStore
source: adapted
source_id: rbxutil
source_path: modules/table-util/init.luau
source_commit: 31f9120fca021e3dec275b42bc7047d626962082
---
# Request
I added new fields (`settings.musicVolume`, `quests`) to my default player data, but players who already have saves load without them and my code errors on nil. How do I fill in missing fields from the template when loading, without wiping what they already have?

# Answer
Reconcile the loaded table against the template after loading: copy in every key the save is missing (deep-copying table defaults so players never share one table), recurse into nested tables, and keep the player's existing values.

```lua
--!strict
local Reconcile = {}

local function deepCopy(value: any): any
	if type(value) ~= "table" then
		return value
	end
	local copy = {}
	for k, v in value do
		copy[k] = deepCopy(v)
	end
	return copy
end

function Reconcile.reconcile(saved: { [any]: any }, template: { [any]: any }): { [any]: any }
	local result = table.clone(saved)
	for key, default in template do
		local current = saved[key]
		if current == nil then
			result[key] = deepCopy(default)
		elseif type(current) == "table" and type(default) == "table" then
			result[key] = Reconcile.reconcile(current, default)
		end
	end
	return result
end

Reconcile.deepCopy = deepCopy

return Reconcile
```

Usage after a successful `GetAsync`: `local data = Reconcile.reconcile(saved or {}, DEFAULT_DATA)`.

- Defaults that are tables are deep-copied, so two new players never end up editing the same `quests` table.
- Existing values win, even if their type differs from the template; validate types separately if old saves could hold bad data.
- Keys that are no longer in the template are kept, so removing a field from the template never deletes player data by accident.

# Test
```lua
local template = { coins = 0, settings = { musicVolume = 0.5, sfx = true }, quests = {} }
local saved = { coins = 120, settings = { sfx = false }, legacyFlag = true }
local data = item.reconcile(saved, template)
check("existing values kept", data.coins == 120 and data.settings.sfx == false)
check("missing nested field added", data.settings.musicVolume == 0.5)
check("missing table added as a copy", type(data.quests) == "table" and data.quests ~= template.quests)
check("unknown keys kept", data.legacyFlag == true)
local a = item.reconcile({}, template)
local b = item.reconcile({}, template)
table.insert(a.quests, "q1")
check("players do not share default tables", #b.quests == 0 and #template.quests == 0)
check("input save not mutated", saved.settings.musicVolume == nil)
```
