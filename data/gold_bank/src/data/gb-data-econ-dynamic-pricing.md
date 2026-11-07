---
id: gb-data-econ-dynamic-pricing
category: economy-simulation
topics: dynamic pricing, supply and demand, exponential decay, shop, quote
source: original
---
# Request
I want a shop item whose price goes up when lots of players in the server buy it and slowly drifts back to normal when nobody does, like a stock price. How would I model that on the server?

# Answer
Track a "demand" value per item that each purchase raises and that decays exponentially over time. The price is `base * (1 + demand * sensitivity)`, capped. Decay is applied lazily from the time since the last update, so nothing has to run every frame, and the server always recomputes the price at purchase time.

```lua
--!strict
-- ModuleScript: ServerScriptService.DynamicPrice
export type Market = {
	price: (now: number) -> number,
	buy: (now: number, maxPrice: number) -> (boolean, number),
}

local DynamicPrice = {}

-- halfLife: seconds for demand to halve. sensitivity: price increase per unit of demand. cap: max multiple of base.
function DynamicPrice.new(base: number, halfLife: number, sensitivity: number, cap: number): Market
	local demand = 0
	local updated = 0
	local decayRate = math.log(2) / halfLife

	local function decay(now: number)
		local dt = math.max(0, now - updated)
		demand *= math.exp(-decayRate * dt)
		updated = now
	end

	local function price(now: number): number
		decay(now)
		return math.floor(base * math.min(cap, 1 + demand * sensitivity))
	end

	-- maxPrice is the price the player saw; refuse if it rose since, so nobody pays more than they agreed to.
	local function buy(now: number, maxPrice: number): (boolean, number)
		local current = price(now)
		if current > maxPrice then
			return false, current
		end
		demand += 1
		return true, current
	end

	return { price = price, buy = buy }
end

return DynamicPrice
```

Use one market per item: `local potionMarket = DynamicPrice.new(100, 120, 0.05, 3)`; the buy remote passes the price the UI displayed as `maxPrice` (validated as a number) and charges the returned price from the server wallet.

- The client's `maxPrice` can only make a purchase fail, never cheaper: the charge is always the server's current price.
- Exponential decay with a half-life is easy to reason about: with 120 s, demand halves every two minutes of quiet.
- For a price shared by all servers, keep demand in a MemoryStore sorted map and update it with `UpdateAsync` instead of a local variable.

# Test
```lua
local market = item.new(100, 60, 0.1, 3)
check("starts at the base price", market.price(0) == 100)
for i = 1, 5 do
	market.buy(i * 0.01, 1000)
end
check("purchases raise the price", market.price(0.1) >= 149 and market.price(0.1) <= 150)
check("demand halves after one half-life", math.abs(market.price(60.1) - 125) <= 1)
check("price drifts back toward base", market.price(1000) == 100)

local ok, charged = market.buy(1000, 100)
check("buying at the displayed price works", ok and charged == 100)
local okAfter, current = market.buy(1000, 100)
check("a price that rose above what the player saw is refused", not okAfter and current > 100)

local hot = item.new(100, 1e9, 1, 3)
for _ = 1, 50 do
	hot.buy(0, math.huge)
end
check("price is capped", hot.price(0) == 300)
```
