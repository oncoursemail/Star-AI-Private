---
id: gb-eng-tdd-cart-discounts
category: engineering-test-first
topics: test-first, shop cart, discounts, integer currency, rounding
source: original
test_block: 2
---
# Request
I'm adding a cart to our in-game coin shop and want tests first because money bugs are painful. Rules: line total = unit price x quantity; "buy 3 get 1 free" applies per item that has the flag; then one coupon percentage off the whole cart (0-50%); totals are whole coins, rounded down in the player's favour only at the very end; quantities must be whole numbers 1-99 or the cart is rejected.

# Answer
Write the money rules as exact-integer cases first: bundle math, coupon after bundles, a single rounding step at the end, and rejected quantities. Then a pure `total` function that returns either a number or an error string, which the server calls with its own price table.

```lua
--!strict
-- Script: ServerScriptService.Tests.CartSpec
local Cart = require(game:GetService("ServerScriptService").Cart)

local failures = 0
local function test(name: string, fn: () -> ())
	local ok, err = pcall(fn)
	if not ok then
		failures += 1
		warn(`FAIL {name}: {err}`)
	end
end

local CATALOG = {
	Potion = { price = 30, bundle = true },
	Sword = { price = 250, bundle = false },
}

test("plain line totals", function()
	assert(Cart.total(CATALOG, { Sword = 2 }, 0) == 500)
end)
test("buy 3 get 1 free per flagged item", function()
	assert(Cart.total(CATALOG, { Potion = 4 }, 0) == 90)
	assert(Cart.total(CATALOG, { Potion = 9 }, 0) == 210)
end)
test("coupon applies after bundles and rounds down once", function()
	-- (210 + 250) x 0.85 = 391
	assert(Cart.total(CATALOG, { Potion = 9, Sword = 1 }, 15) == 391)
end)
test("bad quantities and coupons reject the cart", function()
	assert(select(2, Cart.total(CATALOG, { Potion = 0 }, 0)) ~= nil)
	assert(select(2, Cart.total(CATALOG, { Potion = 2.5 }, 0)) ~= nil)
	assert(select(2, Cart.total(CATALOG, { Potion = 1 }, 80)) ~= nil)
	assert(select(2, Cart.total(CATALOG, { Shield = 1 }, 0)) ~= nil)
end)

print(`Cart spec: {failures} failure(s)`)
```

```lua
--!strict
-- ModuleScript: ServerScriptService.Cart
export type CatalogItem = { price: number, bundle: boolean }

local MAX_QUANTITY = 99
local MAX_COUPON = 50

local Cart = {}

function Cart.total(catalog: { [string]: CatalogItem }, lines: { [string]: unknown }, couponPercent: number): (number?, string?)
	if type(couponPercent) ~= "number" or couponPercent ~= couponPercent or couponPercent < 0 or couponPercent > MAX_COUPON then
		return nil, "invalid coupon"
	end
	local subtotal = 0
	for itemId, quantity in lines do
		local entry = catalog[itemId]
		if entry == nil then
			return nil, `unknown item {itemId}`
		end
		if type(quantity) ~= "number" or quantity % 1 ~= 0 or quantity < 1 or quantity > MAX_QUANTITY then
			return nil, `invalid quantity for {itemId}`
		end
		local paid = if entry.bundle then quantity - quantity // 4 else quantity
		subtotal += entry.price * paid
	end
	-- integer arithmetic until the single rounding step: subtotal * (100 - pct) / 100
	return (subtotal * (100 - couponPercent)) // 100, nil
end

return Cart
```

- Multiplying by `100 - percent` and dividing once with `//` avoids float drift such as `90 * 0.7 = 62.99999...`, which would floor to 62 instead of 63; the only rounding happens at the end, in the player's favour.
- The catalog argument is the server's price table; the client sends only item ids and quantities, so it cannot set prices.
- Any invalid line rejects the whole cart instead of silently dropping it, so the player never pays for a different cart than the one they saw.

# Test
```lua
local CATALOG = { Potion = { price = 30, bundle = true }, Sword = { price = 250, bundle = false } }
check("plain", item.total(CATALOG, { Sword = 2 }, 0) == 500)
check("bundle of 4", item.total(CATALOG, { Potion = 4 }, 0) == 90)
check("bundle of 9", item.total(CATALOG, { Potion = 9 }, 0) == 210)
check("coupon once at end", item.total(CATALOG, { Potion = 9, Sword = 1 }, 15) == 391)
check("zero quantity rejected", item.total(CATALOG, { Potion = 0 }, 0) == nil)
check("fractional rejected", item.total(CATALOG, { Potion = 2.5 }, 0) == nil)
check("too many rejected", item.total(CATALOG, { Potion = 100 }, 0) == nil)
check("coupon over cap rejected", item.total(CATALOG, { Potion = 1 }, 80) == nil and item.total(CATALOG, { Potion = 1 }, 0 / 0) == nil)
check("unknown item rejected", select(2, item.total(CATALOG, { Shield = 1 }, 0)) == "unknown item Shield")
check("string quantity rejected", item.total(CATALOG, { Potion = "3" }, 0) == nil)
check("no float drift at the rounding step", item.total({ Gem = { price = 90, bundle = false } }, { Gem = 1 }, 30) == 63)
```
