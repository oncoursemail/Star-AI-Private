---
id: gb-data-memorystore-matchmaking-queue
category: datastore-safety
topics: MemoryStoreService, queue, matchmaking, ReserveServerAsync, MessagingService
source: original
---
# Request
I want cross-server matchmaking for a 4-player arena: players in any lobby server click "Play", and once 4 are waiting they all get teleported into the same reserved server. How would I build that with MemoryStore queues?

# Answer
Each lobby adds a ticket to a MemoryStore queue. A matching loop reads exactly 4 tickets with `allOrNothing`, reserves the arena with `ReserveServerAsync` (which returns the access code immediately), removes the tickets and publishes the match. Every lobby then teleports its own matched players into that reserved server.

```lua
--!strict
-- ModuleScript: ServerScriptService.Matchmaker
local MemoryStoreService = game:GetService("MemoryStoreService")
local MessagingService = game:GetService("MessagingService")
local TeleportService = game:GetService("TeleportService")
local Players = game:GetService("Players")

local INVISIBLE_SECONDS = 30 -- read tickets stay hidden from other matchers this long
local TICKET_TTL = 120
local MATCH_TOPIC = "ArenaMatch"

local queue = MemoryStoreService:GetQueue("Arena4", INVISIBLE_SECONDS)
-- userId -> time its ticket expires, so a ticket lost to TTL or a failed publish does not block requeueing
local queuedUntil: { [number]: number } = {}

local Matchmaker = {}

function Matchmaker.enqueue(player: Player): boolean
	local userId: number = player.UserId
	local now = os.clock()
	if (queuedUntil[userId] or 0) > now then
		return false
	end
	local ok = pcall(function()
		queue:AddAsync({ userId = userId }, TICKET_TTL)
	end)
	if ok then
		queuedUntil[userId] = now + TICKET_TTL
	end
	return ok
end

function Matchmaker.tryMatch(size: number, arenaPlaceId: number): { number }?
	local ok, tickets, readId = pcall(function()
		return queue:ReadAsync(size, true, 0)
	end)
	if not ok or type(tickets) ~= "table" or #tickets < size then
		return nil
	end
	-- Reserve before removing: if reserving fails, the tickets reappear after INVISIBLE_SECONDS.
	local reserved, code = pcall(function()
		return TeleportService:ReserveServerAsync(arenaPlaceId)
	end)
	if not reserved then
		return nil
	end
	local removed = pcall(function()
		queue:RemoveAsync(readId)
	end)
	if not removed then
		return nil
	end
	local userIds: { number } = {}
	for _, ticket in tickets do
		table.insert(userIds, ticket.userId)
	end
	local published = pcall(function()
		MessagingService:PublishAsync(MATCH_TOPIC, { placeId = arenaPlaceId, code = code, users = userIds })
	end)
	if not published then
		warn("match publish failed; these players can requeue when their tickets expire")
	end
	return userIds
end

-- Every lobby (the matcher's included) teleports the matched players it hosts.
local function onMatch(message: { Data: any })
	local data = message.Data
	local mine: { Player } = {}
	for _, userId in data.users do
		local player = Players:GetPlayerByUserId(userId)
		if player then
			queuedUntil[userId] = nil
			table.insert(mine, player)
		end
	end
	if #mine == 0 then
		return
	end
	local options = Instance.new("TeleportOptions")
	options.ReservedServerAccessCode = data.code
	local ok, err = pcall(function()
		TeleportService:TeleportAsync(data.placeId, mine, options)
	end)
	if not ok then
		warn("arena teleport failed:", err)
	end
end

Players.PlayerRemoving:Connect(function(player: Player)
	queuedUntil[player.UserId] = nil
end)

task.spawn(function()
	for attempt = 1, 5 do
		local ok = pcall(function()
			MessagingService:SubscribeAsync(MATCH_TOPIC, onMatch)
		end)
		if ok then
			return
		end
		task.wait(2 ^ attempt)
	end
	warn("matchmaker could not subscribe; this lobby cannot receive matches")
end)

return Matchmaker
```

Run `tryMatch` from a loop every 2-3 seconds in each lobby server; `allOrNothing` reads mean two matchers never split one group.

- A ticket from a player who left stays until its TTL and can end up in a match; have the arena start with whoever arrives within 20 seconds, and requeue the rest from their lobbies.
- Reserving before `RemoveAsync` means a failed reservation loses nobody: the hidden tickets become readable again.
- Keep messages tiny (user ids and a code); a MessagingService message is limited to 1 KB.

# Test
```lua
warn = function(...) end
game:GetService("TeleportService").ReserveServerAsync = function(self, placeId: number)
	if self.__reserveFails then
		error("reserve failed")
	end
	return "code-" .. placeId, "private-id"
end
```
```lua
local players = {}
for i = 1, 4 do
	players[i] = __makePlayer(100 + i, "P" .. i)
end
check("first enqueue works", item.enqueue(players[1]))
check("double enqueue is refused", not item.enqueue(players[1]))
item.enqueue(players[2])
item.enqueue(players[3])
check("no match with only three waiting", item.tryMatch(4, 999) == nil)

item.enqueue(players[4])
game:GetService("TeleportService").__reserveFails = true
check("a failed reservation makes no match", item.tryMatch(4, 999) == nil)
game:GetService("TeleportService").__reserveFails = false
local matched = item.tryMatch(4, 999)
check("the tickets survive a failed reservation and match next time", matched ~= nil and #matched == 4)

local teleports = game:GetService("TeleportService").__teleports
check("all four go to the reserved server with its access code", #teleports == 1 and teleports[1][1] == 999
	and #teleports[1][2] == 4 and teleports[1][3].ReservedServerAccessCode == "code-999")
check("queue is empty after the match", item.tryMatch(4, 999) == nil)
check("players can queue again after being matched", item.enqueue(players[1]))
```
