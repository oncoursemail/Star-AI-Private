---
id: gb-data-schema-migration
category: datastore-safety
topics: DataStore, schema version, migration, data format change
source: original
---
# Request
I renamed "Gold" to "coins" and changed pets from a list of names to a count per pet. Old players still have the old format saved. How should I structure migrations so every save format upgrades cleanly, including ones I change later?

# Answer
Save a `version` number in every record and keep an ordered list of one-step migrations (v1 to v2, v2 to v3, ...). On load, run the steps from the record's version up to the current one. A record from a newer version than this server knows is refused, not loaded.

```lua
--!strict
-- ModuleScript: ServerScriptService.Migrations
export type Data = { [string]: any }

local CURRENT_VERSION = 3

-- migrations[n] upgrades a version n record to version n + 1. Never edit a step after it has shipped; add a new one.
local migrations: { [number]: (Data) -> Data } = {
	[1] = function(data: Data): Data
		data.coins = if type(data.Gold) == "number" then data.Gold else 0
		data.Gold = nil
		data.gems = 0
		return data
	end,
	[2] = function(data: Data): Data
		local counts: { [string]: number } = {}
		if type(data.pets) == "table" then
			for _, name in data.pets do
				if type(name) == "string" then
					counts[name] = (counts[name] or 0) + 1
				end
			end
		end
		data.pets = counts
		return data
	end,
}

local Migrations = {}
Migrations.CURRENT_VERSION = CURRENT_VERSION

-- Records saved before versioning existed have no version field; treat them as v1.
function Migrations.upgrade(data: Data): (Data?, string?)
	local version = data.version or 1
	if type(version) ~= "number" or version < 1 or version % 1 ~= 0 then
		return nil, "invalid version field"
	end
	if version > CURRENT_VERSION then
		return nil, "saved by a newer server (v" .. version .. ")"
	end
	while version < CURRENT_VERSION do
		local step = migrations[version]
		if step == nil then
			return nil, "missing migration from v" .. version
		end
		data = step(data)
		version += 1
		data.version = version
	end
	return data, nil
end

return Migrations
```

- Refusing newer data matters during a rolling update: an old server that loaded v4 data as v3 would save it back and silently drop the new fields.
- Migrations run only in memory; the upgraded record is written on the next normal save, so a crash mid-load loses nothing.
- When a player's data fails to upgrade, kick with a short message instead of starting them on defaults.

# Test
```lua
local v1 = item.upgrade({ Gold = 50, pets = { "Cat", "Dog", "Cat" } })
check("v1 gold becomes coins", v1 ~= nil and v1.coins == 50 and v1.Gold == nil and v1.gems == 0)
check("v1 pet list becomes counts", v1 ~= nil and v1.pets.Cat == 2 and v1.pets.Dog == 1)
check("upgraded record is stamped current", v1 ~= nil and v1.version == item.CURRENT_VERSION)

local v2 = item.upgrade({ version = 2, coins = 7, gems = 3, pets = { "Fox" } })
check("v2 only runs the later step", v2 ~= nil and v2.coins == 7 and v2.gems == 3 and v2.pets.Fox == 1)

local current = item.upgrade({ version = 3, coins = 1, gems = 0, pets = { Cat = 4 } })
check("current data is untouched", current ~= nil and current.pets.Cat == 4)

local newer, why = item.upgrade({ version = 4 })
check("newer data is refused", newer == nil and string.find(why or "", "newer") ~= nil)

local bad = item.upgrade({ version = "3" })
check("non-number version is refused", bad == nil)
```
