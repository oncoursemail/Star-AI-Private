---
id: gb-data-econ-rebirth-multiplier
category: economy-simulation
topics: rebirth, prestige, multiplier, reset, simulator
source: original
---
# Request
I want a rebirth system for my simulator: when you have enough cash you can rebirth, which resets cash and upgrades but gives a permanent income multiplier. Each rebirth should cost more than the last. How should the server side work?

# Answer
Keep the rule in one server module: the cost grows with the rebirth count, the multiplier is derived from the count (never stored separately, so it cannot drift), and `rebirth` checks the price and resets exactly the fields you list. Income code always multiplies through `multiplier(data)`.

```lua
--!strict
-- ModuleScript: ServerScriptService.Rebirth
export type Data = { cash: number, rebirths: number, upgrades: { [string]: number }, gems: number }

local BASE_COST = 1_000_000
local COST_GROWTH = 2.5
local BONUS_PER_REBIRTH = 0.5
local MAX_REBIRTHS = 100

local Rebirth = {}

function Rebirth.cost(rebirths: number): number
	return math.floor(BASE_COST * COST_GROWTH ^ rebirths)
end

function Rebirth.multiplier(data: Data): number
	return 1 + BONUS_PER_REBIRTH * data.rebirths
end

-- Returns true when the rebirth happened. Gems survive; cash and upgrades reset.
function Rebirth.rebirth(data: Data): boolean
	if data.rebirths >= MAX_REBIRTHS or data.cash < Rebirth.cost(data.rebirths) then
		return false
	end
	data.rebirths += 1
	data.cash = 0
	data.upgrades = {}
	return true
end

function Rebirth.income(data: Data, baseIncome: number): number
	return math.floor(baseIncome * Rebirth.multiplier(data))
end

return Rebirth
```

The client's "Rebirth" button just fires a remote with no arguments; the handler calls `Rebirth.rebirth(profile)` with the server-side profile and saves soon after.

- Cost growth (2.5x) outpaces the multiplier gain (+0.5x each), so each rebirth takes longer than the last; tune the two together with a spreadsheet of time-to-rebirth.
- Deriving the multiplier from `rebirths` means there is only one number to save and validate.
- Save right after a rebirth: a crash that restores the old cash but keeps the new rebirth count would be a free multiplier.

# Test
```lua
local data = { cash = 999_999, rebirths = 0, upgrades = { speed = 5 }, gems = 40 }
check("rebirth needs the full cost", not item.rebirth(data) and data.rebirths == 0 and data.cash == 999_999)
data.cash = 1_200_000
check("rebirth resets cash and upgrades", item.rebirth(data) and data.cash == 0 and next(data.upgrades) == nil)
check("gems and the count survive", data.gems == 40 and data.rebirths == 1)
check("multiplier comes from the count", item.multiplier(data) == 1.5 and item.income(data, 100) == 150)
check("each rebirth costs more", item.cost(1) == 2_500_000 and item.cost(2) > item.cost(1))
data.cash = 2_499_999
check("second rebirth needs the higher cost", not item.rebirth(data))
data.cash = item.cost(1)
check("and works once paid", item.rebirth(data) and data.rebirths == 2 and item.income(data, 10) == 20)
local capped = { cash = 1e300, rebirths = 100, upgrades = {}, gems = 0 }
check("rebirths are capped", not item.rebirth(capped))
```
