---
id: gb-data-econ-shop-server-price
category: economy-simulation
topics: shop, server price, purchase, RemoteEvent, catalogue
source: original
---
# Request
My shop GUI sends `Buy:FireServer(itemName, price)` and the server subtracts the price and gives the item. I know the price shouldn't come from the client, but what should the whole purchase handler look like?

# Answer
The client sends only what it wants (item id and quantity). The server looks the price up in its own catalogue, checks the player's level and room in the inventory, and deducts and grants in one step so a failure can never take coins without giving the item. A short per-player cooldown stops request spam.

```lua
--!strict
-- ModuleScript: ServerScriptService.Shop
local Players = game:GetService("Players")

export type Wallet = { coins: number, level: number, items: { [string]: number }, maxPerItem: number }
export type Result = "ok" | "unknown item" | "bad quantity" | "level" | "funds" | "full" | "slow down"

local CATALOG: { [string]: { price: number, level: number } } = {
	potion = { price = 25, level = 1 },
	arrow = { price = 2, level = 1 },
	iron_sword = { price = 400, level = 10 },
}
local MAX_QUANTITY = 50
local COOLDOWN = 0.25

local Shop = {}
local lastBuy: { [Player]: number } = {}

Players.PlayerRemoving:Connect(function(player: Player)
	lastBuy[player] = nil
end)

function Shop.buy(player: Player, wallet: Wallet, itemId: unknown, quantityArg: unknown): Result
	local now = os.clock()
	if lastBuy[player] and now - lastBuy[player] < COOLDOWN then
		return "slow down"
	end
	lastBuy[player] = now
	local entry = if type(itemId) == "string" then CATALOG[itemId] else nil
	if entry == nil then
		return "unknown item"
	end
	if type(quantityArg) ~= "number" or quantityArg % 1 ~= 0 or quantityArg < 1 or quantityArg > MAX_QUANTITY then
		return "bad quantity"
	end
	local id = itemId :: string
	local cost = entry.price * quantityArg
	if wallet.level < entry.level then
		return "level"
	elseif wallet.coins < cost then
		return "funds"
	elseif (wallet.items[id] or 0) + quantityArg > wallet.maxPerItem then
		return "full"
	end
	wallet.coins -= cost
	wallet.items[id] = (wallet.items[id] or 0) + quantityArg
	return "ok"
end

return Shop
```

The remote handler is then two lines: look up the player's server-side wallet and call `Shop.buy(player, wallet, itemId, quantity)`, sending the result string back for the UI.

- All checks happen before any mutation, and the two mutations have no yield between them, so the purchase is effectively atomic.
- `price * quantity` uses the server price; with `quantity` capped and an integer, the cost cannot overflow or go negative.
- Show prices in the UI from a replicated copy of the catalogue, but treat that copy as display only.

# Test
```lua
local p = __makePlayer(1, "Buyer")
local wallet = { coins = 500, level = 5, items = {}, maxPerItem = 99 }
check("buying uses the server price", item.buy(p, wallet, "potion", 4) == "ok" and wallet.coins == 400 and wallet.items.potion == 4)
check("requests faster than the cooldown are refused", item.buy(p, wallet, "potion", 1) == "slow down")
__advance(0.3)
check("level gates are enforced", item.buy(p, wallet, "iron_sword", 1) == "level" and wallet.coins == 400)
__advance(0.3)
check("bulk purchase multiplies the server price", item.buy(p, wallet, "arrow", 50) == "ok" and wallet.coins == 300)
__advance(0.3)
check("insufficient funds are refused", item.buy(p, wallet, "potion", 13) == "funds" and wallet.coins == 300)
__advance(0.3)
wallet.items.arrow = 90
check("capacity is enforced", item.buy(p, wallet, "arrow", 20) == "full" and wallet.coins == 300)
__advance(0.3)
check("negative and huge quantities are refused", item.buy(p, wallet, "potion", -5) == "bad quantity")
__advance(0.3)
check("quantities over the cap are refused", item.buy(p, wallet, "arrow", 51) == "bad quantity")
__advance(0.3)
check("NaN quantity is refused", item.buy(p, wallet, "potion", 0 / 0) == "bad quantity" and wallet.coins == 300)
__advance(0.3)
check("unknown items are refused", item.buy(p, wallet, "admin_wand", 1) == "unknown item")
```
