---
id: gb-data-versioned-key-fallback
category: datastore-safety
topics: DataStore, key naming, legacy data, versioned keys, UpdateAsync
source: original
---
# Request
My old saves are in a store called "Stats" with the player's name as the key (bad idea, names change). I want to move to a "PlayerData_v2" store keyed by UserId without anyone losing progress. What is a safe way to switch over?

# Answer
Read the new key first. If it is empty, read the legacy key once, convert it, and write it into the new key with `UpdateAsync` that only writes when the new key is still empty, so two servers cannot both import. Leave the legacy data untouched so you can roll back.

```lua
--!strict
-- ModuleScript: ServerScriptService.KeyMove
local DataStoreService = game:GetService("DataStoreService")

local current = DataStoreService:GetDataStore("PlayerData_v2")
local legacy = DataStoreService:GetDataStore("Stats")

export type Data = { coins: number, wins: number, importedFrom: string? }

local KeyMove = {}

local function readLegacy(name: string): (boolean, any)
	return pcall(function()
		return legacy:GetAsync(name)
	end)
end

local function convert(old: any, name: string): Data
	local data: Data = { coins = 0, wins = 0, importedFrom = name }
	if type(old) == "table" then
		data.coins = tonumber(old.Cash) or 0
		data.wins = tonumber(old.Wins) or 0
	end
	return data
end

-- Returns the player's data, importing legacy data on first load. nil means "do not let them play yet".
function KeyMove.load(userId: number, legacyName: string): Data?
	local key = "user_" .. userId
	local okNew, data = pcall(function()
		return current:GetAsync(key)
	end)
	if not okNew then
		return nil
	end
	if data ~= nil then
		return data
	end

	local okOld, old = readLegacy(legacyName)
	if not okOld then
		return nil -- legacy read failed: importing "nothing" now would hide their old progress forever
	end
	local imported = convert(old, legacyName)
	local result: Data? = nil
	local okWrite = pcall(function()
		result = current:UpdateAsync(key, function(existing: Data?): Data?
			if existing ~= nil then
				return nil -- another server imported first; keep theirs
			end
			return imported
		end)
	end)
	if not okWrite then
		return nil
	end
	return result or imported
end

return KeyMove
```

- The legacy lookup uses the name the player had when you switched; if renames already happened, keep a name to UserId table from your logs, or fall back to defaults with a support path.
- `importedFrom` records where the data came from, which answers "I lost my stuff" reports months later.
- Once almost nobody is importing, stop reading the legacy store; the code path then costs one `GetAsync` per join.

# Test
```lua
local ds = game:GetService("DataStoreService")
ds:GetDataStore("Stats"):SetAsync("OldName", { Cash = 400, Wins = 3 })

local data = item.load(9, "OldName")
check("legacy data is converted on first load", data ~= nil and data.coins == 400 and data.wins == 3)
check("new key now holds the import", ds:GetDataStore("PlayerData_v2"):GetAsync("user_9").coins == 400)
check("legacy data is left in place", ds:GetDataStore("Stats"):GetAsync("OldName").Cash == 400)

ds:GetDataStore("PlayerData_v2"):SetAsync("user_9", { coins = 999, wins = 3 })
check("existing new data wins over legacy", item.load(9, "OldName").coins == 999)

local fresh = item.load(10, "NeverPlayed")
check("players with no legacy data start at zero", fresh ~= nil and fresh.coins == 0)

ds.__failNext = 1
check("a failed read returns nil instead of defaults", item.load(11, "Someone") == nil)
check("the next attempt loads normally", item.load(11, "Someone") ~= nil)
```
