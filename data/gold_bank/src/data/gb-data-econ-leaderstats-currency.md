---
id: gb-data-econ-leaderstats-currency
category: economy-simulation
topics: currency, leaderstats, server authority, spend, IntValue
source: original
---
# Request
Half a dozen of my scripts (quests, shop, trading, daily bonus) each poke the Coins IntValue directly, and I keep finding players with negative balances and no idea which script caused it. How would you centralise the currency so it stays correct and traceable?

# Answer
One server module owns the balances; the leaderstats IntValue is only a display mirror that the module updates. Every change goes through `add` or `spend`, which validate the amount, refuse to go below zero and keep a reason for logging, so no script edits the value directly.

```lua
--!strict
-- ModuleScript: ServerScriptService.Coins
local balances: { [Player]: number } = {}
local displays: { [Player]: IntValue } = {}

local Coins = {}

local function validAmount(amount: number): boolean
	return amount == amount and amount > 0 and amount % 1 == 0 and amount < 1e12
end

local function refresh(player: Player)
	local display = displays[player]
	if display then
		display.Value = balances[player] or 0
	end
end

function Coins.setup(player: Player, saved: number)
	local stats = Instance.new("Folder")
	stats.Name = "leaderstats"
	local display = Instance.new("IntValue")
	display.Name = "Coins"
	display.Parent = stats
	stats.Parent = player
	displays[player] = display
	balances[player] = math.max(0, math.floor(saved))
	refresh(player)
end

-- nil means "not loaded": a saver must skip the write instead of saving 0 over real data.
function Coins.get(player: Player): number?
	return balances[player]
end

function Coins.add(player: Player, amount: number, reason: string): boolean
	local balance = balances[player]
	if balance == nil or not validAmount(amount) then
		return false
	end
	balances[player] = balance + amount
	refresh(player)
	print(string.format("[coins] %s +%d (%s)", player.Name, amount, reason))
	return true
end

-- Spends only when the full amount is available.
function Coins.spend(player: Player, amount: number, reason: string): boolean
	local balance = balances[player]
	if balance == nil or not validAmount(amount) or balance < amount then
		return false
	end
	balances[player] = balance - amount
	refresh(player)
	print(string.format("[coins] %s -%d (%s)", player.Name, amount, reason))
	return true
end

-- Called by your saver after the final save. Clearing in a separate PlayerRemoving handler would race
-- the saver: handler order is not guaranteed, so the save could run after the balance is gone.
function Coins.release(player: Player)
	balances[player] = nil
	displays[player] = nil
end

return Coins
```

Your data loader calls `Coins.setup(player, savedCoins)` after loading. Your PlayerRemoving saver reads `Coins.get(player)`, skips the write when it is `nil`, and calls `Coins.release(player)` once the save has finished.

- Because the IntValue is written only by `refresh`, a stray script setting it changes the display until the next update, never the real balance.
- `spend` returning `false` is how shops refuse: check the result before granting anything.
- The `reason` strings make "where did my coins go" support questions answerable from logs or `AnalyticsService:LogEconomyEvent`.

# Test
```lua
local p = __makePlayer(1, "Earner")
item.setup(p, 100)
check("setup shows the saved balance", __leaderstat(p, "Coins") == 100 and item.get(p) == 100)
check("add increases balance and display", item.add(p, 50, "quest") and __leaderstat(p, "Coins") == 150)
check("spend within balance works", item.spend(p, 120, "sword") and item.get(p) == 30)
check("overspending is refused", not item.spend(p, 31, "shield") and item.get(p) == 30)
check("negative, fractional and NaN amounts are refused", not item.add(p, -10, "x") and not item.add(p, 1.5, "x")
	and not item.spend(p, -5, "x") and not item.add(p, 0 / 0, "x"))
p.leaderstats.Coins.Value = 999999
item.add(p, 1, "tick")
check("display edits do not change the real balance", item.get(p) == 31 and __leaderstat(p, "Coins") == 31)
local stranger = __makePlayer(2, "NotLoaded")
check("players without loaded data cannot earn", not item.add(stranger, 10, "x"))
check("unloaded players read nil, not 0", item.get(stranger) == nil)
__removePlayer(p)
check("leaving alone does not clear the balance before the save", item.get(p) == 31)
item.release(p)
check("release clears the player's state", item.get(p) == nil and not item.add(p, 1, "late"))
```
