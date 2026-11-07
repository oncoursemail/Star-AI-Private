---
id: gb-data-fix-donation-total-race
category: datastore-safety
topics: DataStore, race condition, UpdateAsync, GetAsync SetAsync, global total
source: original
---
# Request
My donation board shows a global total from all servers, but the total is often lower than the sum of donations. What is wrong with this?

```lua
local function addDonation(player, amount)
	local record = donations:GetAsync("Totals") or { total = 0, count = 0 }
	record.total += amount
	record.count += 1
	record.last = player.Name
	donations:SetAsync("Totals", record)
end
```

# Answer
Two servers can both read the same old total, each add their donation, and the second `SetAsync` overwrites the first, so one donation vanishes. `UpdateAsync` fixes it: Roblox hands your function the latest stored value and retries the function if someone else wrote in between. Wrap it in `pcall` with retries, and take the amount from the product's server-side price, never from a client.

```lua
--!strict
-- ModuleScript: ServerScriptService.Donations
local DataStoreService = game:GetService("DataStoreService")

local donations = DataStoreService:GetDataStore("Donations")

export type Totals = { total: number, count: number, lastDonor: number }

local Donations = {}

-- amount comes from your ProcessReceipt handler's product table, not from a RemoteEvent.
function Donations.record(userId: number, amount: number): boolean
	if amount ~= amount or amount <= 0 or amount % 1 ~= 0 then
		return false
	end
	for attempt = 1, 3 do
		local ok, err = pcall(function()
			donations:UpdateAsync("Totals", function(old: Totals?): Totals
				local totals = old or { total = 0, count = 0, lastDonor = 0 }
				totals.total += amount
				totals.count += 1
				totals.lastDonor = userId
				return totals
			end)
		end)
		if ok then
			return true
		end
		warn("donation write failed:", err)
		task.wait(attempt)
	end
	return false
end

function Donations.read(): Totals?
	local ok, totals = pcall(function()
		return donations:GetAsync("Totals")
	end)
	return if ok then totals else nil
end

return Donations
```

- Store the donor's UserId rather than `player.Name`; names change and the board can resolve the current name when it renders.
- The transform must stay free of side effects (no prints that matter, no granting), because Roblox may run it more than once.
- One hot key shared by every server is limited by per-key write throughput; if donations are very frequent, sum them per server and flush every 30 seconds.

# Test
```lua
warn = function(...) end
```
```lua
check("first donation is recorded", item.record(1, 50))
item.record(2, 25)
item.record(3, 25)
local totals = item.read()
check("every donation is counted", totals ~= nil and totals.total == 100 and totals.count == 3 and totals.lastDonor == 3)

check("zero, negative, fractional and NaN amounts are refused",
	not item.record(1, 0) and not item.record(1, -5) and not item.record(1, 2.5) and not item.record(1, 0 / 0))

local ds = game:GetService("DataStoreService")
ds.__failNext = 1
local ok = nil
task.spawn(function()
	ok = item.record(4, 10)
end)
__advance(5)
check("a transient failure is retried", ok == true and item.read().total == 110)
```
