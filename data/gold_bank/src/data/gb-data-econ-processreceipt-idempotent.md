---
id: gb-data-econ-processreceipt-idempotent
category: economy-simulation
topics: MarketplaceService, ProcessReceipt, developer products, idempotent, purchase history
source: original
---
# Request
I sell gem packs as developer products. I read that ProcessReceipt can be called more than once for the same purchase and that I must not return PurchaseGranted unless the gems are really saved. How do I write it correctly?

# Answer
Keep gems and the list of processed receipt ids in one DataStore record per player, and grant inside a single `UpdateAsync`: if the `PurchaseId` is already recorded, the purchase was granted before; otherwise add the gems and record the id in the same write. Return `PurchaseGranted` only after that write succeeded, and `NotProcessedYet` otherwise so Roblox retries later.

```lua
--!strict
-- Script: ServerScriptService.GemProducts
local MarketplaceService = game:GetService("MarketplaceService")
local DataStoreService = game:GetService("DataStoreService")
local Players = game:GetService("Players")

local store = DataStoreService:GetDataStore("Gems")
local MAX_RECEIPTS = 100

-- Product ids come from attributes set on this script in Studio (GemPack100, GemPack500).
local PACKS: { [string]: number } = { GemPack100 = 100, GemPack500 = 550 }
local PRODUCTS: { [number]: number } = {}
for attribute, gems in PACKS do
	local productId = script:GetAttribute(attribute)
	if type(productId) == "number" then
		PRODUCTS[productId] = gems
	end
end

type Record = { gems: number, receipts: { string } }

local function grant(userId: number, purchaseId: string, gems: number): boolean
	local ok = pcall(function()
		store:UpdateAsync("user_" .. userId, function(old: Record?): Record?
			local record: Record = old or { gems = 0, receipts = {} }
			if table.find(record.receipts, purchaseId) then
				return nil -- already granted; nothing to write
			end
			record.gems += gems
			table.insert(record.receipts, purchaseId)
			if #record.receipts > MAX_RECEIPTS then
				table.remove(record.receipts, 1)
			end
			return record
		end)
	end)
	return ok
end

local function processReceipt(receipt: { PlayerId: number, ProductId: number, PurchaseId: string }): Enum.ProductPurchaseDecision
	local gems = PRODUCTS[receipt.ProductId]
	if gems == nil then
		return Enum.ProductPurchaseDecision.NotProcessedYet -- unknown product: let support look at it
	end
	if not grant(receipt.PlayerId, receipt.PurchaseId, gems) then
		return Enum.ProductPurchaseDecision.NotProcessedYet
	end
	local player = Players:GetPlayerByUserId(receipt.PlayerId)
	if player then
		player:SetAttribute("GemsDirty", true) -- tell your gem display to re-read the balance
	end
	return Enum.ProductPurchaseDecision.PurchaseGranted
end

MarketplaceService.ProcessReceipt = processReceipt
```

- Granting and recording in the same `UpdateAsync` is what makes it idempotent: there is no moment where gems were added but the receipt id was not saved, or the reverse.
- An already-recorded receipt cancels the write and still returns `PurchaseGranted`, which is correct: the player already has their gems.
- Gems live only in this record (read it through `GetAsync` for display); if you also copied gems into a session profile, its next save would overwrite this purchase.

# Test
```lua
script:SetAttribute("GemPack100", 1001)
script:SetAttribute("GemPack500", 1005)
```
```lua
local mps = game:GetService("MarketplaceService")
local store = game:GetService("DataStoreService"):GetDataStore("Gems")
local granted = Enum.ProductPurchaseDecision.PurchaseGranted
local retry = Enum.ProductPurchaseDecision.NotProcessedYet

local receipt = { PlayerId = 7, ProductId = 1001, PurchaseId = "p-1" }
check("a new purchase is granted", mps.ProcessReceipt(receipt) == granted and store:GetAsync("user_7").gems == 100)
check("the same receipt again is acknowledged without granting twice", mps.ProcessReceipt(receipt) == granted
	and store:GetAsync("user_7").gems == 100)

check("a second pack adds its own amount", mps.ProcessReceipt({ PlayerId = 7, ProductId = 1005, PurchaseId = "p-2" }) == granted
	and store:GetAsync("user_7").gems == 650)

game:GetService("DataStoreService").__failNext = 1
check("a failed save asks Roblox to retry", mps.ProcessReceipt({ PlayerId = 7, ProductId = 1001, PurchaseId = "p-3" }) == retry
	and store:GetAsync("user_7").gems == 650)
check("the retry then succeeds once", mps.ProcessReceipt({ PlayerId = 7, ProductId = 1001, PurchaseId = "p-3" }) == granted
	and store:GetAsync("user_7").gems == 750)
check("unknown products are not granted", mps.ProcessReceipt({ PlayerId = 7, ProductId = 42, PurchaseId = "p-4" }) == retry)
```
