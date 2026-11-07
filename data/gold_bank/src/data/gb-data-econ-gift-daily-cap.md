---
id: gb-data-econ-gift-daily-cap
category: economy-simulation
topics: gifting, daily cap, alt accounts, account age, currency transfer
source: original
---
# Request
I want players to send coins to friends in the same server, but I'm worried about alt accounts farming coins and funneling them to a main. What limits would you put on gifting, and how do I implement them?

# Answer
Make the transfer a server-only operation with limits that make alt farming slow and visible: senders need a minimum account age, each player can send at most a daily amount (reset on the UTC day from server time), recipients have a daily receive cap too, and the transfer is all-or-nothing with no fee rounding surprises.

```lua
--!strict
-- ModuleScript: ServerScriptService.Gifting
export type Wallet = { coins: number, sentToday: number, receivedToday: number, day: number }
export type Result = "ok" | "bad amount" | "self" | "new account" | "funds" | "send cap" | "receive cap"

local MIN_ACCOUNT_AGE = 7 -- days
local DAILY_SEND = 5_000
local DAILY_RECEIVE = 10_000

local Gifting = {}

local function rollDay(wallet: Wallet, today: number)
	if wallet.day ~= today then
		wallet.day = today
		wallet.sentToday = 0
		wallet.receivedToday = 0
	end
end

-- now is the server's os.time(); accountAge is the sender's Player.AccountAge (days).
function Gifting.send(from: Wallet, to: Wallet, amountArg: unknown, accountAge: number, now: number): Result
	if from == to then
		return "self"
	end
	if type(amountArg) ~= "number" or amountArg % 1 ~= 0 or amountArg < 1 then
		return "bad amount"
	end
	if accountAge < MIN_ACCOUNT_AGE then
		return "new account"
	end
	local today = now // 86400
	rollDay(from, today)
	rollDay(to, today)
	if from.coins < amountArg then
		return "funds"
	elseif from.sentToday + amountArg > DAILY_SEND then
		return "send cap"
	elseif to.receivedToday + amountArg > DAILY_RECEIVE then
		return "receive cap"
	end
	from.coins -= amountArg
	from.sentToday += amountArg
	to.coins += amountArg
	to.receivedToday += amountArg
	return "ok"
end

return Gifting
```

The gift remote looks up both wallets on the server (the target by UserId, and only if they are in this server and on the sender's friends list via `Player:IsFriendsWith` in `pcall`), passes `player.AccountAge` and `os.time()`, and logs every "ok" with both UserIds.

- The receive cap is what defeats ten alts feeding one main: the main can only take in so much per day no matter how many senders exist.
- Daily counters live in each player's saved data, so leaving and rejoining does not reset them.
- Logging transfers lets you spot patterns (many new accounts sending maximum gifts to one player) and act on them.

# Test
```lua
local now = 1_700_000_000
local alice = { coins = 20_000, sentToday = 0, receivedToday = 0, day = 0 }
local bob = { coins = 0, sentToday = 0, receivedToday = 0, day = 0 }
check("a normal gift moves coins", item.send(alice, bob, 1000, 30, now) == "ok" and alice.coins == 19_000 and bob.coins == 1000)
check("new accounts cannot send", item.send(alice, bob, 10, 2, now) == "new account")
check("bad amounts are refused", item.send(alice, bob, -5, 30, now) == "bad amount" and item.send(alice, bob, 0 / 0, 30, now) == "bad amount"
	and item.send(alice, bob, 2.5, 30, now) == "bad amount")
check("sending to yourself is refused", item.send(alice, alice, 10, 30, now) == "self")
check("the daily send cap applies", item.send(alice, bob, 4001, 30, now) == "send cap" and alice.coins == 19_000)

local carol = { coins = 50_000, sentToday = 0, receivedToday = 0, day = 0 }
local dave = { coins = 50_000, sentToday = 0, receivedToday = 0, day = 0 }
item.send(carol, bob, 5000, 30, now)
check("the daily receive cap applies across senders", item.send(dave, bob, 4500, 30, now) == "receive cap" and bob.coins == 6000)

check("caps reset on the next UTC day", item.send(dave, bob, 4500, 30, now + 86400) == "ok" and bob.coins == 10_500)
check("insufficient funds are refused", item.send(bob, alice, 20_000, 30, now + 86400) == "funds")
```
