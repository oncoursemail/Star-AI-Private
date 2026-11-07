# Shop and receipts

## API
- `Shops.new({ catalog = { [item] = { currency, price } }, wallet, getInventory, maxQuantity? }) -> shop`; `shop:Purchase(player, itemId, qty) -> ok, reason`. Order: validate, `CanAdd`, `Spend`, `Add`, refund if the add fails.
- `Shops.receiptProcessor({ getPlayer, getProfile, products = { [productId] = grantFn }, granted, notProcessed, remember? }) -> fn`. `grantFn(player, data)` returns true when done.

## Wire it
`MarketplaceService.ProcessReceipt = Shops.receiptProcessor({ ..., granted = Enum.ProductPurchaseDecision.PurchaseGranted, notProcessed = Enum.ProductPurchaseDecision.NotProcessedYet })`. Assign it once, from one script. Behind a RemoteEvent, call `shop:Purchase` with the validated `itemId` and `qty` only.

## Pitfalls
- The client never sends a price. A missing catalog entry means "unknown item".
- `Purchase` has no yields; if you add one (a DataStore call), re-check balance and capacity after it.
- The receipt id is stored in the profile and the grant is saved before `PurchaseGranted` is returned; a failed save returns `NotProcessedYet`, and Roblox calls again.
- Player gone or data not loaded: `NotProcessedYet`, never `PurchaseGranted`.
