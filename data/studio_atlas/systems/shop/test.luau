local Kit = require("../../testkit")
local Shops = require("./Shop")
local Wallets = require("../wallet/Wallet")
local Inventories = require("../inventory/Inventory")

local function setup()
	local wallet = Wallets.new({ currencies = { Coins = { max = 1e6 } } })
	local player = Kit.player(1)
	wallet:Attach(player, { Coins = 100 })
	local inv = Inventories.new({ capacity = 2, items = { Potion = { maxStack = 5 }, Sword = { maxStack = 1 } } })
	local shop = Shops.new({
		catalog = { Potion = { currency = "Coins", price = 10 }, Sword = { currency = "Coins", price = 80 } },
		wallet = wallet,
		getInventory = function(p) return if p == player then inv else nil end,
	})
	return shop, wallet, player, inv
end

Kit.test("purchase deducts the server price and grants the item", function()
	local shop, wallet, player, inv = setup()
	Kit.truthy(shop:Purchase(player, "Potion", 3))
	Kit.eq(wallet:Get(player, "Coins"), 70)
	Kit.eq(inv:Count("Potion"), 3)
end)

Kit.test("insufficient funds, unknown item and bad quantity change nothing", function()
	local shop, wallet, player, inv = setup()
	Kit.eq(select(2, shop:Purchase(player, "Sword", 2)), "insufficient funds") -- 160 > 100
	Kit.eq((shop:Purchase(player, "Gem", 1)), false)
	for _, q in { 0, -1, 1.5, 100, 0 / 0 } do Kit.eq((shop:Purchase(player, "Potion", q)), false) end
	Kit.truthy(shop:Purchase(player, "Sword", 1))
	local ok, why = shop:Purchase(player, "Sword", 1)
	Kit.eq(ok, false)
	Kit.eq(why, "insufficient funds")
	Kit.eq(wallet:Get(player, "Coins"), 20)
	Kit.eq(inv:Count("Sword"), 1)
end)

Kit.test("a full inventory refuses before any money is taken", function()
	local shop, wallet, player = setup()
	Kit.truthy(shop:Purchase(player, "Potion", 10)) -- 2 slots x 5
	local ok, why = shop:Purchase(player, "Potion", 1)
	Kit.eq(ok, false)
	Kit.eq(why, "inventory full")
	Kit.eq(wallet:Get(player, "Coins"), 0)
end)

local GRANTED, NOT_YET = "granted", "notyet"
local function receipts(saveOk)
	local player, grants = Kit.player(7), 0
	local profile = { Data = {}, saves = 0 }
	function profile:Save() self.saves += 1; return saveOk() end
	local process = Shops.receiptProcessor({
		getPlayer = function(id) return if id == 7 then player else nil end,
		getProfile = function(p) return if p == player then profile else nil end,
		products = { [100] = function(_, data) grants += 1; data.Gems = (data.Gems or 0) + 10; return true end,
			[200] = function() error("boom") end },
		granted = GRANTED, notProcessed = NOT_YET, remember = 3,
	})
	return process, profile, function() return grants end
end

Kit.test("receipt is granted once even when Roblox sends it again", function()
	local process, profile, grants = receipts(function() return true end)
	local info = { PurchaseId = "p1", PlayerId = 7, ProductId = 100 }
	Kit.eq(process(info), GRANTED)
	Kit.eq(process(info), GRANTED)
	Kit.eq(grants(), 1)
	Kit.eq(profile.Data.Gems, 10)
end)

Kit.test("player gone, data not loaded, unknown product, grant error: not processed", function()
	local process = receipts(function() return true end)
	Kit.eq(process({ PurchaseId = "a", PlayerId = 99, ProductId = 100 }), NOT_YET)
	Kit.eq(process({ PurchaseId = "b", PlayerId = 7, ProductId = 999 }), NOT_YET)
	Kit.eq(process({ PurchaseId = "c", PlayerId = 7, ProductId = 200 }), NOT_YET)
end)

Kit.test("a failed save means not processed, and the retry does not grant twice", function()
	local saveOk = false
	local process, _, grants = receipts(function() return saveOk end)
	local info = { PurchaseId = "p2", PlayerId = 7, ProductId = 100 }
	Kit.eq(process(info), NOT_YET)
	saveOk = true
	Kit.eq(process(info), GRANTED)
	Kit.eq(grants(), 1)
end)

Kit.test("only the most recent receipt ids are remembered", function()
	local process, profile = receipts(function() return true end)
	for i = 1, 5 do process({ PurchaseId = "r" .. i, PlayerId = 7, ProductId = 100 }) end
	Kit.eq(#profile.Data.Receipts.order, 3)
	Kit.eq(profile.Data.Receipts.ids.r1, nil)
	Kit.eq(profile.Data.Receipts.ids.r5, true)
end)

Kit.finish("shop")
