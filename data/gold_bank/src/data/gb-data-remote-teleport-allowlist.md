---
id: gb-data-remote-teleport-allowlist
category: remote-security
topics: TeleportService, allowlist, RemoteEvent, TeleportAsync, level gate
source: original
---
# Request
My world map UI sends `Travel:FireServer(placeId)` and the server teleports the player there. I just realised someone could send any place id. How should I lock this down?

# Answer
Never accept a place id from the client. The client names a destination key ("Hub", "Dungeon"), and the server looks it up in its own table of place ids and requirements, checks the player's level and a cooldown, then teleports inside `pcall` and reports failures back.

```lua
--!strict
-- ModuleScript: ServerScriptService.Travel
local TeleportService = game:GetService("TeleportService")
local Players = game:GetService("Players")

export type Destination = { placeId: number, minLevel: number }
export type Result = "ok" | "unknown" | "level" | "cooldown" | "failed"

local COOLDOWN = 8

local Travel = {}

-- destinations come from server config, e.g. { Hub = { placeId = HUB_ID, minLevel = 0 } }
function Travel.new(destinations: { [string]: Destination }): (player: Player, key: unknown) -> Result
	local lastAttempt: { [Player]: number } = {}

	Players.PlayerRemoving:Connect(function(player: Player)
		lastAttempt[player] = nil
	end)

	return function(player: Player, key: unknown): Result
		if type(key) ~= "string" then
			return "unknown"
		end
		local destination = destinations[key]
		if destination == nil then
			return "unknown"
		end
		local level = player:GetAttribute("Level")
		if type(level) ~= "number" or level < destination.minLevel then
			return "level"
		end
		local now = os.clock()
		local last = lastAttempt[player]
		if last and now - last < COOLDOWN then
			return "cooldown"
		end
		lastAttempt[player] = now
		local ok = pcall(function()
			TeleportService:TeleportAsync(destination.placeId, { player })
		end)
		return if ok then "ok" else "failed"
	end
end

return Travel
```

Wiring it to the remote, with place ids read from attributes on the script so no ids live in client code:

```lua
--!strict
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerScriptService = game:GetService("ServerScriptService")
local Travel = require(ServerScriptService.Travel)

local travelRemote = Instance.new("RemoteEvent")
travelRemote.Name = "Travel"
travelRemote.Parent = ReplicatedStorage

local request = Travel.new({
	Hub = { placeId = script:GetAttribute("HubPlaceId"), minLevel = 0 },
	Dungeon = { placeId = script:GetAttribute("DungeonPlaceId"), minLevel = 10 },
})

local function onTravel(player: Player, key: unknown)
	local result = request(player, key)
	travelRemote:FireClient(player, result)
end

travelRemote.OnServerEvent:Connect(onTravel)
```

- The destination table is also the right place for party-size limits or game-pass gates; the client only ever sees keys.
- `TeleportAsync` can fail (place down, player in a bad state); the cooldown still applies so a failing destination is not hammered, and the client shows "try again".
- Listen to `TeleportService.TeleportInitFailed` if you want to retry automatically for transient failures.

# Test
```lua
local request = item.new({
	Hub = { placeId = 1001, minLevel = 0 },
	Dungeon = { placeId = 2002, minLevel = 10 },
})
local tps = game:GetService("TeleportService")
local p = __makePlayer(1, "Traveler")
p:SetAttribute("Level", 5)

check("unknown keys and raw place ids are refused", request(p, "Secret") == "unknown" and request(p, 2002) == "unknown")
check("level gate applies", request(p, "Dungeon") == "level")
check("allowed destination teleports", request(p, "Hub") == "ok")
local last = tps.__teleports[#tps.__teleports]
check("teleport uses the server's place id", last[1] == 1001 and last[2][1] == p)

p:SetAttribute("Level", 12)
check("cooldown blocks rapid retries", request(p, "Dungeon") == "cooldown")
__advance(9)
check("after the cooldown the gated place works", request(p, "Dungeon") == "ok" and tps.__teleports[#tps.__teleports][1] == 2002)

local noLevel = __makePlayer(2, "Fresh")
check("players without a level attribute are refused", request(noLevel, "Hub") == "level")
```
