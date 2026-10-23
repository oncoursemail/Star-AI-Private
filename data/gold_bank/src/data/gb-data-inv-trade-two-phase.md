---
id: gb-data-inv-trade-two-phase
category: server-authoritative-inventory
topics: trading, two-phase confirm, item duplication, scam prevention, atomic swap
source: original
---
# Request
I want a player-to-player trade window: both players put items in, both press Accept, then the swap happens. How do I build the server side so nobody can swap their offer at the last second or dupe items?

# Answer
Model the trade as a server object. Each side's offer is a list of item counts; any change to either offer clears both acceptances (the classic last-second swap scam). When both have accepted, the server checks again that each player still owns every offered item, and only then moves everything in one step.

```lua
--!strict
-- ModuleScript: ServerScriptService.TradeSession
export type Bag = { [string]: number }
export type Side = { bag: Bag, offer: Bag, accepted: boolean }
export type Trade = { a: Side, b: Side, done: boolean }

local MAX_KINDS_PER_OFFER = 8

local TradeSession = {}

function TradeSession.new(bagA: Bag, bagB: Bag): Trade
	return {
		a = { bag = bagA, offer = {}, accepted = false },
		b = { bag = bagB, offer = {}, accepted = false },
		done = false,
	}
end

local function owns(bag: Bag, offer: Bag): boolean
	for id, n in offer do
		if (bag[id] or 0) < n then
			return false
		end
	end
	return true
end

-- Set one item count in a side's offer (0 removes it). Any change resets both accepts.
function TradeSession.setOffer(trade: Trade, side: Side, id: unknown, countArg: unknown): boolean
	if trade.done or type(id) ~= "string" or type(countArg) ~= "number" then
		return false
	end
	if countArg % 1 ~= 0 or countArg < 0 or countArg > (side.bag[id] or 0) then
		return false
	end
	local kinds = 0
	for _ in side.offer do
		kinds += 1
	end
	if side.offer[id] == nil and countArg > 0 and kinds >= MAX_KINDS_PER_OFFER then
		return false
	end
	side.offer[id] = if countArg > 0 then countArg else nil
	trade.a.accepted, trade.b.accepted = false, false
	return true
end

local function move(from: Bag, to: Bag, offer: Bag)
	for id, n in offer do
		local left = (from[id] or 0) - n
		from[id] = if left > 0 then left else nil
		to[id] = (to[id] or 0) + n
	end
end

-- Returns "waiting", "completed" or "failed" (ownership changed; offers cleared).
function TradeSession.accept(trade: Trade, side: Side): string
	if trade.done then
		return "failed"
	end
	side.accepted = true
	if not (trade.a.accepted and trade.b.accepted) then
		return "waiting"
	end
	if not owns(trade.a.bag, trade.a.offer) or not owns(trade.b.bag, trade.b.offer) then
		trade.a.offer, trade.b.offer = {}, {}
		trade.a.accepted, trade.b.accepted = false, false
		return "failed"
	end
	move(trade.a.bag, trade.b.bag, trade.a.offer)
	move(trade.b.bag, trade.a.bag, trade.b.offer)
	trade.done = true
	return "completed"
end

return TradeSession
```

- The final ownership check matters because items can leave a bag during the trade (sold, dropped, used in another trade); without it, one sword can be traded to two people.
- These bags have no capacity limit; if yours do, also check that each side has room for what it receives before the two `move` calls, and fail the trade otherwise.
- Show both offers to both clients after every change and add a short delay (2-3 s) before Accept is clickable again, so a changed offer is actually seen.
- Save both players' data right after `completed` (and log the trade); a crash before saving would otherwise roll back only one side.

# Test
```lua
local alice = { sword = 1, gold = 100 }
local bob = { shield = 1, gem = 5 }
local trade = item.new(alice, bob)
item.setOffer(trade, trade.a, "sword", 1)
item.setOffer(trade, trade.b, "gem", 5)
check("first accept waits for the other side", item.accept(trade, trade.a) == "waiting")

item.setOffer(trade, trade.b, "gem", 1)
check("changing an offer resets both accepts", trade.a.accepted == false and trade.b.accepted == false)
check("offering more than you own is refused", not item.setOffer(trade, trade.b, "gem", 6)
	and not item.setOffer(trade, trade.b, "gem", -1) and not item.setOffer(trade, trade.b, "gem", 0 / 0))

item.accept(trade, trade.a)
check("both accepting completes the swap", item.accept(trade, trade.b) == "completed")
check("items moved both ways", alice.sword == nil and bob.sword == 1 and alice.gem == 1 and bob.gem == 4)
check("a finished trade cannot be reused", not item.setOffer(trade, trade.a, "gold", 10) and item.accept(trade, trade.a) == "failed")

local carol = { bow = 1 }
local dave = { coin = 3 }
local t2 = item.new(carol, dave)
item.setOffer(t2, t2.a, "bow", 1)
item.accept(t2, t2.a)
carol.bow = nil -- sold elsewhere mid-trade
check("ownership is checked again at completion", item.accept(t2, t2.b) == "failed" and dave.bow == nil)
```
