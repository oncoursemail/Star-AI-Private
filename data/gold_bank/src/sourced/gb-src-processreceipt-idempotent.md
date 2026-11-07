---
id: gb-src-processreceipt-idempotent
category: economy-simulation
topics: MarketplaceService, ProcessReceipt, developer products, PurchaseId, idempotency, DataStoreService
source: adapted
source_id: creator-docs
source_path: content/en-us/production/monetization/developer-products.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I sell a "+100 Gold" developer product. How do I write ProcessReceipt so players always get their gold exactly once, even if the server crashes or Roblox retries the receipt?

# Answer
Set `MarketplaceService.ProcessReceipt` once, in one server script. Grant inside a data store `UpdateAsync` that also records the receipt's `PurchaseId`, so a retried receipt sees the id and grants nothing twice. Return `PurchaseGranted` only after the save succeeded; otherwise return `NotProcessedYet` and Roblox retries later.

```lua
--!strict
local MarketplaceService = game:GetService("MarketplaceService")
local DataStoreService = game:GetService("DataStoreService")
local Players = game:GetService("Players")

local GOLD_PRODUCT_ID = 456456

local playerStore = DataStoreService:GetDataStore("PlayerData")

type PlayerData = { gold: number, purchases: { [string]: boolean } }

local grants: { [number]: (data: PlayerData) -> () } = {
	[GOLD_PRODUCT_ID] = function(data: PlayerData)
		data.gold += 100
	end,
}

local function processReceipt(receiptInfo: any): any
	local grant = grants[receiptInfo.ProductId]
	if not grant then
		return Enum.ProductPurchaseDecision.NotProcessedYet
	end

	local purchaseId = tostring(receiptInfo.PurchaseId)
	local newGold = 0
	local ok, err = pcall(function()
		playerStore:UpdateAsync("Player_" .. receiptInfo.PlayerId, function(old: PlayerData?)
			local data: PlayerData = old or { gold = 0, purchases = {} }
			if not data.purchases[purchaseId] then
				grant(data)
				data.purchases[purchaseId] = true
			end
			newGold = data.gold
			return data
		end)
	end)
	if not ok then
		warn("Receipt not saved:", err)
		return Enum.ProductPurchaseDecision.NotProcessedYet
	end

	local player = Players:GetPlayerByUserId(receiptInfo.PlayerId)
	if player then
		player:SetAttribute("Gold", newGold)
	end
	return Enum.ProductPurchaseDecision.PurchaseGranted
end

MarketplaceService.ProcessReceipt = processReceipt
```

- The `PurchaseId` record makes the grant idempotent: a duplicate receipt finds it and changes nothing.
- The grant and the record are written in the same `UpdateAsync`, so they cannot get out of sync.
- This writes the data store directly. If your game also keeps a session copy of the player's data and saves it later, grant through that session instead (or use a session-locking library such as ProfileStore), or the session's next save overwrites this gold.
- The player does not need to be in this server; the purchase is saved and shows up on next join. Trim the purchase log over time so the key stays under the 4 MB value limit.

# Test
```lua
local MarketplaceService = game:GetService("MarketplaceService")
local DataStoreService = game:GetService("DataStoreService")
local p = __makePlayer(42, "Buyer")
local receipt = { PlayerId = 42, ProductId = 456456, PurchaseId = "abc-1" }
local process = MarketplaceService.ProcessReceipt
check("first receipt granted", process(receipt) == Enum.ProductPurchaseDecision.PurchaseGranted and p:GetAttribute("Gold") == 100)
check("retried receipt grants nothing more", process(receipt) == Enum.ProductPurchaseDecision.PurchaseGranted and p:GetAttribute("Gold") == 100)
check("unknown product not processed", process({ PlayerId = 42, ProductId = 1, PurchaseId = "x" }) == Enum.ProductPurchaseDecision.NotProcessedYet)
DataStoreService.__failNext = 1
check("save failure asks for a retry", process({ PlayerId = 42, ProductId = 456456, PurchaseId = "abc-2" }) == Enum.ProductPurchaseDecision.NotProcessedYet and p:GetAttribute("Gold") == 100)
```
