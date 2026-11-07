---
id: gb-data-econ-promo-codes
category: economy-simulation
topics: promo codes, redeem, limited uses, UpdateAsync, expiry
source: original
---
# Request
I want Twitter-style codes players can type in for rewards: each code works once per player, some expire on a date, and some are limited to the first 1000 redemptions across all servers. How do I build this?

# Answer
Codes live in a server table (never in the client), normalised to upper case. Redeeming checks the code exists and has not expired, checks the player's own redeemed list and records the code on the player before anything yields. For limited codes it then claims a global use with `UpdateAsync` on a counter key, which is atomic across servers, and un-records the code if that claim fails. Only then is the reward granted.

```lua
--!strict
-- ModuleScript: ServerScriptService.PromoCodes
local DataStoreService = game:GetService("DataStoreService")

export type Code = { coins: number, expires: number?, maxUses: number? }
export type Result = "ok" | "invalid" | "expired" | "used" | "sold out" | "error"

local CODES: { [string]: Code } = {
	LAUNCH = { coins = 500 },
	SUMMER24 = { coins = 250, expires = 1_725_000_000 },
	FIRST1000 = { coins = 1000, maxUses = 1000 },
}

local counters = DataStoreService:GetDataStore("PromoCodeUses")

local PromoCodes = {}

local function claimGlobalUse(code: string, maxUses: number): Result
	local result: Result = "error"
	local ok = pcall(function()
		counters:UpdateAsync(code, function(used: number?): number?
			local count = used or 0
			if count >= maxUses then
				result = "sold out"
				return nil
			end
			result = "ok"
			return count + 1
		end)
	end)
	-- the transform can run and the write still fail, so only a successful call counts
	return if ok then result else "error"
end

-- redeemed is the player's saved set of codes; addCoins is your currency module's add.
function PromoCodes.redeem(redeemed: { [string]: boolean }, input: unknown, now: number, addCoins: (number) -> ()): Result
	if type(input) ~= "string" or #input > 32 then
		return "invalid"
	end
	local stripped = string.gsub(input, "%s", "")
	local key = string.upper(stripped)
	local code = CODES[key]
	if code == nil then
		return "invalid"
	elseif code.expires and now > code.expires then
		return "expired"
	elseif redeemed[key] then
		return "used"
	end
	redeemed[key] = true -- before the yield below, so a parallel request sees "used"
	if code.maxUses then
		local claim = claimGlobalUse(key, code.maxUses)
		if claim ~= "ok" then
			redeemed[key] = nil
			return claim
		end
	end
	addCoins(code.coins)
	return "ok"
end

return PromoCodes
```

The redeem remote passes the player's saved `redeemed` table, `os.time()` and a closure over the currency module; rate-limit it to a few attempts per minute so codes cannot be brute-forced.

- Recording the code on the player before anything can yield again keeps one player from redeeming the same code twice with parallel requests.
- A failed counter write returns "error" without granting; the player can simply try again.
- Keep the reward data on the server even for public codes; the client only ever sends the text the player typed.

# Test
```lua
local now = 1_720_000_000
local coins = 0
local function add(n)
	coins += n
end
local redeemed = {}
check("a valid code grants its reward", item.redeem(redeemed, " launch ", now, add) == "ok" and coins == 500)
check("each code works once per player", item.redeem(redeemed, "LAUNCH", now, add) == "used" and coins == 500)
check("unknown and malformed codes are invalid", item.redeem(redeemed, "FREEROBUX", now, add) == "invalid"
	and item.redeem(redeemed, 1234, now, add) == "invalid" and item.redeem(redeemed, string.rep("A", 40), now, add) == "invalid")
check("expired codes are refused", item.redeem(redeemed, "summer24", 1_730_000_000, add) == "expired")

local store = game:GetService("DataStoreService"):GetDataStore("PromoCodeUses")
store:SetAsync("FIRST1000", 999)
check("the last global use can be claimed", item.redeem(redeemed, "FIRST1000", now, add) == "ok" and coins == 1500)
local late = {}
check("after the limit the code is sold out and not recorded", item.redeem(late, "FIRST1000", now, add) == "sold out"
	and coins == 1500 and late.FIRST1000 == nil)

store:SetAsync("FIRST1000", 0)
game:GetService("DataStoreService").__failNext = 1
local fresh = {}
check("a counter failure grants nothing and can be retried", item.redeem(fresh, "FIRST1000", now, add) == "error"
	and fresh.FIRST1000 == nil and item.redeem(fresh, "FIRST1000", now, add) == "ok")

store:SetAsync("FIRST1000", 0)
local realUpdate = store.UpdateAsync
store.UpdateAsync = function(self, key, fn)
	task.wait(1) -- a real DataStore call yields
	return realUpdate(self, key, fn)
end
local twin = {}
local before = coins
task.spawn(item.redeem, twin, "FIRST1000", now, add)
task.spawn(item.redeem, twin, "FIRST1000", now, add)
__advance(2)
check("two parallel requests from one player grant once", coins == before + 1000 and store:GetAsync("FIRST1000") == 1)
```
