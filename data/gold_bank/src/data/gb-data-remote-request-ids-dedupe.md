---
id: gb-data-remote-request-ids-dedupe
category: remote-security
topics: RemoteEvent, sequence number, replay, idempotency, double purchase
source: original
---
# Request
Sometimes a laggy player clicks "Buy" and the purchase goes through twice, and I have read that exploiters can replay remote calls too. Would adding a sequence number to my remotes help, and how would I do it?

# Answer
Partly. Roblox delivers each remote call once and in order, so a laggy double purchase is two real clicks with two different ids, and the fix for that is a client button lock plus a server-side purchase cooldown. A per-player sequence number adds something else: the server remembers the highest id it accepted and drops anything not greater, so a request your client resends (say, after a timeout) or a call an exploit tool replays verbatim is processed at most once. It does not stop cheating on its own (an exploiter can send a fresh id), so the server still validates price, funds and cooldown on every request.

```lua
--!strict
-- ModuleScript: ServerScriptService.RequestIds
local Players = game:GetService("Players")

export type Tracker = {
	accept: (player: Player, id: unknown) -> boolean,
}

local RequestIds = {}

-- maxJump stops a client from jumping to a huge id and locking itself out of later requests.
function RequestIds.new(maxJump: number): Tracker
	local lastSeen: { [Player]: number } = {}

	Players.PlayerRemoving:Connect(function(player: Player)
		lastSeen[player] = nil
	end)

	local function accept(player: Player, id: unknown): boolean
		if type(id) ~= "number" or id % 1 ~= 0 then
			return false -- also rejects NaN, since NaN % 1 is NaN
		end
		local last = lastSeen[player] or 0
		if id <= last or id > last + maxJump then
			return false
		end
		lastSeen[player] = id
		return true
	end

	return { accept = accept }
end

return RequestIds
```

Client side, the id simply counts up:

```lua
--!strict
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local buy = ReplicatedStorage:WaitForChild("BuyItem") :: RemoteEvent

local nextId = 0

local function requestBuy(itemId: string)
	nextId += 1
	buy:FireServer(nextId, itemId)
end

return requestBuy
```

- Remotes are ordered and reliable per client, so honest requests always arrive with increasing ids; anything else is a resend, a replay or tampering.
- The double click is two honest requests with two ids, so the id check does not catch it: lock the button until the server replies and keep a short purchase cooldown on the server.
- Use one tracker per remote (or include the remote name in the key) so ids from different remotes do not interfere.

# Test
```lua
local tracker = item.new(100)
local p = __makePlayer(1, "Buyer")
check("first request is accepted", tracker.accept(p, 1))
check("the same id is rejected as a replay", not tracker.accept(p, 1))
check("next id is accepted", tracker.accept(p, 2))
check("older ids are rejected", not tracker.accept(p, 1))
check("gaps are allowed within the limit", tracker.accept(p, 10))
check("huge jumps are rejected", not tracker.accept(p, 1e9))
check("non-integers and NaN are rejected", not tracker.accept(p, 11.5) and not tracker.accept(p, 0 / 0) and not tracker.accept(p, "12"))
local other = __makePlayer(2, "Other")
check("ids are tracked per player", tracker.accept(other, 1))
__removePlayer(p)
check("state is cleared when the player leaves", tracker.accept(__makePlayer(1, "Buyer"), 1))
```
