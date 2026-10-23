---
id: gb-data-docs-remote-types
category: docs-question
topics: RemoteEvent, RemoteFunction, UnreliableRemoteEvent, networking, choosing
source: original
---
# Request
When should I use a RemoteEvent, a RemoteFunction, or an UnreliableRemoteEvent? I've been using RemoteFunctions for everything because I like getting a return value.

# Answer
RemoteEvent is the default: one-way, reliable and ordered, fine in both directions. RemoteFunction is for a client asking the server a question and waiting for the answer (`InvokeServer`); avoid the server waiting on a client (`InvokeClient`), because the client controls if and when that returns. UnreliableRemoteEvent is for frequent, replaceable updates (cursor or look direction, cosmetic effects) where a lost or late message does not matter because the next one supersedes it.

```lua
--!strict
-- Server: one of each, used for what it is good at.
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local function make(className: string, name: string): Instance
	local remote = Instance.new(className)
	remote.Name = name
	remote.Parent = ReplicatedStorage
	return remote
end

-- RemoteEvent: "I want to buy X" (client -> server) and "your inventory changed" (server -> client).
local buy = make("RemoteEvent", "BuyItem") :: RemoteEvent
-- RemoteFunction: the client asks a question and needs the answer to continue (load a shop page).
local getPrices = make("RemoteFunction", "GetPrices") :: RemoteFunction
-- UnreliableRemoteEvent: 10-20 updates a second of cosmetic state; drops are fine.
local aim = make("UnreliableRemoteEvent", "AimDirection") :: UnreliableRemoteEvent

local PRICES = { potion = 25, arrow = 2 }

getPrices.OnServerInvoke = function(_player: Player): { [string]: number }
	return PRICES
end

buy.OnServerEvent:Connect(function(player: Player, itemId: unknown)
	if type(itemId) == "string" and PRICES[itemId] then
		buy:FireClient(player, itemId, "ok")
	end
end)

aim.OnServerEvent:Connect(function(player: Player, yaw: unknown)
	-- yaw == yaw rejects NaN; the bound rejects infinity, where yaw % 360 would be NaN
	if type(yaw) == "number" and yaw == yaw and math.abs(yaw) < 1e9 then
		player:SetAttribute("AimYaw", yaw % 360)
	end
end)

return { buy = buy, getPrices = getPrices, aim = aim }
```

- A RemoteFunction call costs a full round trip and yields the caller; for "do this" requests where the client only needs to hear back later, a RemoteEvent with a reply event is lighter.
- If the server needs information from a client, fire a RemoteEvent and wait for a reply event with a timeout instead of `InvokeClient`.
- Unreliable messages can arrive out of order and have a smaller size limit (about 900 bytes); never send currency, inventory or anything that must add up through them.
- All three are untrusted input on the server: validate every argument whichever type you pick.

# Test
```lua
local rs = game:GetService("ReplicatedStorage")
check("all three remotes exist with the right classes", rs.BuyItem.ClassName == "RemoteEvent"
	and rs.GetPrices.ClassName == "RemoteFunction" and rs.AimDirection.ClassName == "UnreliableRemoteEvent")
local p = __makePlayer(1, "Client")
check("the function returns data", rs.GetPrices.OnServerInvoke(p).potion == 25)
rs.BuyItem.OnServerEvent:Fire(p, "potion")
rs.BuyItem.OnServerEvent:Fire(p, "nuke")
check("the event replies only to valid requests", #rs.BuyItem.__sent == 1 and rs.BuyItem.__sent[1][2] == "potion")
rs.AimDirection.OnServerEvent:Fire(p, 370)
rs.AimDirection.OnServerEvent:Fire(p, 0 / 0)
rs.AimDirection.OnServerEvent:Fire(p, math.huge)
rs.AimDirection.OnServerEvent:Fire(p, -math.huge)
check("unreliable updates are validated too (NaN and infinity refused)", p:GetAttribute("AimYaw") == 10)
```
