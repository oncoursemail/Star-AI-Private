---
id: gb-data-studio-store-separation
category: datastore-safety
topics: DataStore, Studio testing, store names, environment, live data
source: original
---
# Request
When I playtest in Studio my test runs save into the same data stores as the live game, and I already wiped my own live save once while testing a migration. How do I keep Studio data separate from production?

# Answer
Pick store names in one module: production names in live servers, a prefixed copy in Studio. Every script asks this module for a store instead of calling `GetDataStore` directly, so no code path can reach live data from a playtest.

```lua
--!strict
-- ModuleScript: ServerScriptService.Stores
local DataStoreService = game:GetService("DataStoreService")
local RunService = game:GetService("RunService")

local Stores = {}

local function prefix(): string
	if RunService:IsStudio() then
		return "STUDIO_"
	end
	return ""
end

function Stores.nameFor(base: string): string
	return prefix() .. base
end

function Stores.get(base: string): DataStore
	return DataStoreService:GetDataStore(Stores.nameFor(base))
end

function Stores.ordered(base: string): OrderedDataStore
	return DataStoreService:GetOrderedDataStore(Stores.nameFor(base))
end

return Stores
```

Usage:

```lua
--!strict
local ServerScriptService = game:GetService("ServerScriptService")
local Stores = require(ServerScriptService.Stores)

local playerData = Stores.get("PlayerData")
local wins = Stores.ordered("Wins")

return { playerData = playerData, wins = wins }
```

- Studio still talks to the real DataStore service (when "Enable Studio Access to API Services" is on); only the names keep the data apart.
- To test against a real save, copy that one key into the `STUDIO_` store from a live server's console instead of turning the prefix off.
- Publish a separate test place under the same experience if testers need shared data; its servers can use their own prefix with the same module.

# Test
```lua
local RunService = game:GetService("RunService")
check("live servers use production names", item.nameFor("PlayerData") == "PlayerData")
local live = item.get("PlayerData")
check("live store object is the production store", live.Name == "PlayerData")

RunService.IsStudio = function()
	return true
end
check("Studio gets prefixed names", item.nameFor("PlayerData") == "STUDIO_PlayerData")
local studio = item.get("PlayerData")
pcall(function()
	studio:SetAsync("player_1", { coins = 1 })
end)
check("Studio writes do not touch live data", live:GetAsync("player_1") == nil)
check("ordered stores are prefixed too", item.ordered("Wins").Name == "STUDIO_Wins")
```
