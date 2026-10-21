---
id: gb-data-econ-market-fee-tax
category: economy-simulation
topics: player market, sales tax, listing fee, currency sink, rounding
source: original
---
# Request
I'm adding a player marketplace and want it to remove coins from the economy: a small listing fee and a 10% tax on sales. How should I compute fees so rounding never creates or destroys coins by accident?

# Answer
Work in whole coins only and compute each fee once with explicit rounding: the tax is `floor(price * rate)` but at least 1 coin on any sale, the seller gets `price - tax`, and the buyer pays exactly `price`. Then `paid == received + tax` always holds, and the tax and listing fee are the only coins leaving the economy, which you can total for balancing.

```lua
--!strict
-- ModuleScript: ServerScriptService.MarketFees
export type Sale = { price: number, tax: number, sellerGets: number }

local TAX_RATE = 0.10
local LISTING_FEE_RATE = 0.02
local MIN_PRICE = 2
local MAX_PRICE = 10_000_000

local MarketFees = {}
MarketFees.sunk = 0 -- coins removed by the market since server start, for balancing dashboards

function MarketFees.validPrice(price: unknown): number?
	if type(price) == "number" and price % 1 == 0 and price >= MIN_PRICE and price <= MAX_PRICE then
		return price
	end
	return nil
end

-- Charged when listing; not refunded if the listing expires, which discourages spam listings.
function MarketFees.listingFee(price: number): number
	return math.max(1, math.floor(price * LISTING_FEE_RATE))
end

function MarketFees.sale(price: number): Sale
	local tax = math.max(1, math.floor(price * TAX_RATE))
	return { price = price, tax = tax, sellerGets = price - tax }
end

-- Applies a sale to two server-side wallets. Returns false (and changes nothing) if the buyer cannot pay.
function MarketFees.settle(buyer: { coins: number }, seller: { coins: number }, price: number): boolean
	if buyer.coins < price then
		return false
	end
	local s = MarketFees.sale(price)
	buyer.coins -= s.price
	seller.coins += s.sellerGets
	MarketFees.sunk += s.tax
	return true
end

return MarketFees
```

- `MIN_PRICE = 2` guarantees the seller always receives at least 1 coin after the minimum tax.
- Tracking `sunk` against coins created by quests and drops per hour tells you whether the economy is inflating; adjust `TAX_RATE` with data, not guesses.
- The price is the seller's listed price read from the server's listing record at purchase time, never a price the buyer's client sends.

# Test
```lua
check("price validation accepts whole prices in range", item.validPrice(100) == 100 and item.validPrice(1) == nil
	and item.validPrice(2.5) == nil and item.validPrice(0 / 0) == nil and item.validPrice("100") == nil)
local s = item.sale(100)
check("10% tax on a round price", s.tax == 10 and s.sellerGets == 90)
check("small sales still pay at least 1 coin tax", item.sale(5).tax == 1 and item.sale(5).sellerGets == 4)
check("listing fee is 2% with a 1 coin minimum", item.listingFee(1000) == 20 and item.listingFee(10) == 1)

local conserved = true
for price = 2, 2000 do
	local sale = item.sale(price)
	if sale.sellerGets + sale.tax ~= price or sale.sellerGets < 1 or sale.tax % 1 ~= 0 then
		conserved = false
	end
end
check("buyer payment always equals seller share plus tax", conserved)

local buyer, seller = { coins = 150 }, { coins = 0 }
check("settle moves coins and records the sink", item.settle(buyer, seller, 120) and buyer.coins == 30 and seller.coins == 108
	and item.sunk == 12)
check("buyers who cannot pay change nothing", not item.settle(buyer, seller, 120) and buyer.coins == 30 and seller.coins == 108)
```
