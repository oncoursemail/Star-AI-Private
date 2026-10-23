--!strict
-- Shop purchases and Developer Product receipts. The client only names an item and a quantity; price, currency,
-- capacity and the grant are decided here. ProcessReceipt is idempotent: Roblox may call it again for the same
-- PurchaseId (rejoin, crash, retry) and the player must get the product exactly once.

export type Wallet = { Spend: (self: Wallet, player: any, currency: string, amount: number) -> (boolean, string?), Add: (self: Wallet, player: any, currency: string, amount: number) -> (boolean, string?) }
export type InventoryLike = {
	CanAdd: (self: InventoryLike, id: string, count: number) -> (boolean, string?),
	Add: (self: InventoryLike, id: string, count: number) -> (boolean, string?),
}
export type CatalogEntry = { currency: string, price: number }
export type Config = {
	catalog: { [string]: CatalogEntry }, -- item id -> price, the only source of prices
	wallet: Wallet,
	getInventory: (player: any) -> InventoryLike?,
	maxQuantity: number?, -- per purchase (default 99)
}
export type Shop = { Purchase: (self: Shop, player: any, itemId: string, quantity: number) -> (boolean, string?) }

export type ReceiptInfo = { PurchaseId: string, PlayerId: number, ProductId: number }
export type ProfileLike = { Data: { [string]: any }, Save: (self: ProfileLike) -> boolean }
export type ReceiptConfig = {
	getPlayer: (userId: number) -> any?,
	getProfile: (player: any) -> ProfileLike?,
	products: { [number]: (player: any, data: { [string]: any }) -> boolean }, -- product id -> grant
	granted: any, -- Enum.ProductPurchaseDecision.PurchaseGranted
	notProcessed: any, -- Enum.ProductPurchaseDecision.NotProcessedYet
	remember: number?, -- how many receipt ids to keep per player (default 200)
}

local Shops = {}

function Shops.new(cfg: Config): Shop
	local maxQuantity = cfg.maxQuantity or 99
	local shop = {} :: Shop

	function shop.Purchase(_self, player, itemId, quantity)
		local entry = cfg.catalog[itemId]
		if entry == nil then
			return false, "unknown item"
		end
		if type(quantity) ~= "number" or quantity < 1 or quantity % 1 ~= 0 or quantity > maxQuantity then
			return false, "bad quantity"
		end
		local inventory = cfg.getInventory(player)
		if inventory == nil then
			return false, "inventory not loaded"
		end
		local fits, why = inventory:CanAdd(itemId, quantity)
		if not fits then
			return false, why
		end
		local total = entry.price * quantity
		local paid, reason = cfg.wallet:Spend(player, entry.currency, total)
		if not paid then
			return false, reason
		end
		-- Nothing above yields, so no other request can interleave. If you add a yield, re-check afterwards.
		local added = inventory:Add(itemId, quantity)
		if not added then
			cfg.wallet:Add(player, entry.currency, total) -- refund; unreachable after CanAdd, kept as a safety net
			return false, "could not add item"
		end
		return true, nil
	end

	return shop
end

-- Assign the returned function to MarketplaceService.ProcessReceipt (once, from a server Script).
function Shops.receiptProcessor(cfg: ReceiptConfig): (ReceiptInfo) -> any
	local remember = cfg.remember or 200
	return function(info)
		local player = cfg.getPlayer(info.PlayerId)
		local grant = cfg.products[info.ProductId]
		if player == nil or grant == nil then
			return cfg.notProcessed -- left the game: Roblox asks again when they rejoin
		end
		local profile = cfg.getProfile(player)
		if profile == nil then
			return cfg.notProcessed -- data not loaded yet
		end
		local log = profile.Data.Receipts
		if log == nil then
			log = { ids = {}, order = {} }
			profile.Data.Receipts = log
		end
		if log.ids[info.PurchaseId] ~= true then
			local ok, granted = pcall(grant, player, profile.Data)
			if not ok or granted ~= true then
				return cfg.notProcessed
			end
			log.ids[info.PurchaseId] = true
			table.insert(log.order, info.PurchaseId)
			if #log.order > remember then
				log.ids[table.remove(log.order, 1)] = nil
			end
		end
		-- Granted only once the record of the grant is safely stored; otherwise Roblox retries and we land here again.
		if profile:Save() then
			return cfg.granted
		end
		return cfg.notProcessed
	end
end

return Shops
