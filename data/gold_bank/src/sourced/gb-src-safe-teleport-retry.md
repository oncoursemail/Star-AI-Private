---
id: gb-src-safe-teleport-retry
category: round-systems
topics: TeleportService, TeleportAsync, TeleportOptions, TeleportInitFailed, retry, reserved server
source: adapted
source_id: creator-docs
source_path: content/en-us/projects/teleport.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
My lobby sends a full party to a reserved match server with `TeleportService:TeleportAsync`. Sometimes it errors or the teleport silently fails for one player and they're stuck in the lobby. How do I make teleports reliable?

# Answer
Teleports fail in two places: the `TeleportAsync` call itself can throw (wrap it in `pcall` and retry a few times), and a teleport that started can still fail per player later, which fires `TeleportInitFailed`. Retry transient results (`Flooded`, `Failure`) for that player, and give up on permanent ones. A player retried out of a reserved-server teleport must join the server the party went to, so keep its access code for the retry instead of reserving a new server.

```lua
--!strict
local Players = game:GetService("Players")
local TeleportService = game:GetService("TeleportService")

local ATTEMPT_LIMIT = 5
local RETRY_DELAY = 1
local FLOOD_DELAY = 15

local SafeTeleport = {}

local retryOptions: { [Player]: TeleportOptions } = {}

function SafeTeleport.teleport(placeId: number, players: { Player }, options: TeleportOptions?): (boolean, any)
	if #players == 0 then
		return false, "no players"
	end
	local ok: boolean, result: any = false, nil
	for attempt = 1, ATTEMPT_LIMIT do
		ok, result = pcall(function()
			return TeleportService:TeleportAsync(placeId, players, options)
		end)
		if ok then
			break
		end
		if attempt < ATTEMPT_LIMIT then
			task.wait(RETRY_DELAY)
		end
	end
	if not ok then
		warn("Teleport failed:", result)
	end
	return ok, result
end

function SafeTeleport.reservedMatch(placeId: number, players: { Player }, matchId: string): (boolean, any)
	local options = Instance.new("TeleportOptions")
	options.ShouldReserveServer = true
	options:SetTeleportData({ matchId = matchId })
	local ok, result = SafeTeleport.teleport(placeId, players, options)
	if ok then
		local joinOptions = Instance.new("TeleportOptions")
		joinOptions.ReservedServerAccessCode = result.ReservedServerAccessCode
		joinOptions:SetTeleportData({ matchId = matchId })
		for _, player in players do
			retryOptions[player] = joinOptions
		end
	end
	return ok, result
end

TeleportService.TeleportInitFailed:Connect(function(player: Player, result: Enum.TeleportResult, message: string, placeId: number, options: TeleportOptions)
	if result == Enum.TeleportResult.Flooded then
		task.wait(FLOOD_DELAY)
	elseif result == Enum.TeleportResult.Failure then
		task.wait(RETRY_DELAY)
	else
		warn("Teleport not retried for", player.Name, result, message)
		return
	end
	SafeTeleport.teleport(placeId, { player }, retryOptions[player] or options)
end)

Players.PlayerRemoving:Connect(function(player: Player)
	retryOptions[player] = nil
end)

return SafeTeleport
```

- `ShouldReserveServer = true` puts the whole party in one new private server; retrying a single player with those same options would reserve a second server, so retries use `ReservedServerAccessCode` from the `TeleportAsync` result instead.
- Teleport data is readable on arrival with `player:GetJoinData().TeleportData`, but the client can tamper with it; use it for hints like `matchId` and look up anything important on the server side.
- Retrying `Unauthorized` or `GameNotFound` never succeeds, so those are reported instead.

# Test
```lua
local TeleportService = game:GetService("TeleportService")
local a = __makePlayer(1, "A")
local b = __makePlayer(2, "B")
local ok = item.reservedMatch(1234, { a, b }, "match-7")
local sent = TeleportService.__teleports
check("teleport issued", ok == true and #sent == 1)
check("whole party in one call", sent[1][1] == 1234 and #sent[1][2] == 2)
check("reserves a server with match data", sent[1][3].ShouldReserveServer == true and sent[1][3]:GetTeleportData().matchId == "match-7")
local okEmpty, reason = item.teleport(1234, {})
check("empty party rejected", okEmpty == false and reason == "no players")
TeleportService.TeleportInitFailed:Fire(b, Enum.TeleportResult.Failure, "lost connection", 1234, sent[1][3])
__advance(1.1)
check("failed player retried alone", #sent == 2 and #sent[2][2] == 1 and sent[2][2][1] == b)
check("retry joins the reserved server instead of reserving another", sent[2][3].ShouldReserveServer ~= true and sent[2][3].ReservedServerAccessCode ~= nil and sent[2][3]:GetTeleportData().matchId == "match-7")
TeleportService.TeleportInitFailed:Fire(a, Enum.TeleportResult.Unauthorized, "no access", 1234, sent[1][3])
__advance(1.1)
check("permanent failure not retried", #sent == 2)
```
