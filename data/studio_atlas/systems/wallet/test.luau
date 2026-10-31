local Kit = require("../../testkit")
local Wallets = require("./Wallet")

local function setup()
	local shown = {}
	local w = Wallets.new({
		currencies = { Coins = { max = 1000 }, Gems = { max = 50 } },
		publisher = { Show = function(_, c, v) shown[c] = v end, Hide = function() end },
	})
	local p, data = Kit.player(1), { Coins = 10 }
	w:Attach(p, data)
	return w, p, data, shown
end

Kit.test("attach fills missing currencies and mirrors them to leaderstats", function()
	local w, p, data, shown = setup()
	Kit.eq(data.Gems, 0)
	Kit.eq(shown.Coins, 10)
	Kit.eq(w:Get(p, "Coins"), 10)
end)

Kit.test("corrupt saved balances are repaired", function()
	local w = Wallets.new({ currencies = { Coins = { max = 100 } } })
	local data = { Coins = -5 }
	w:Attach(Kit.player(1), data)
	Kit.eq(data.Coins, 0)
	local big = { Coins = 5000.7 }
	w:Attach(Kit.player(2), big)
	Kit.eq(big.Coins, 100)
end)

Kit.test("add caps at max and reports it", function()
	local w, p = setup()
	local ok, note = w:Add(p, "Gems", 80)
	Kit.truthy(ok)
	Kit.eq(note, "capped")
	Kit.eq(w:Get(p, "Gems"), 50)
end)

Kit.test("spend checks the balance and never goes negative", function()
	local w, p, _, shown = setup()
	local ok, why = w:Spend(p, "Coins", 11)
	Kit.eq(ok, false)
	Kit.eq(why, "insufficient funds")
	Kit.truthy(w:Spend(p, "Coins", 10))
	Kit.eq(w:Get(p, "Coins"), 0)
	Kit.eq(shown.Coins, 0)
end)

Kit.test("bad amounts and unknown currencies are refused", function()
	local w, p = setup()
	for _, bad in { 0, -3, 1.5, 0 / 0, math.huge } do
		Kit.eq((w:Add(p, "Coins", bad)), false)
		Kit.eq((w:Spend(p, "Coins", bad)), false)
	end
	Kit.eq((w:Add(p, "Rubies", 1)), false)
	Kit.eq((w:Add(Kit.player(9), "Coins", 1)), false, "player not attached")
end)

Kit.test("leaderstats publisher creates one folder and one value per currency", function()
	local created = {}
	local function node(class)
		local n = { ClassName = class, kids = {} }
		function n:FindFirstChild(name) return self.kids[name] end
		return n
	end
	local pub = Wallets.leaderstats(function(class) local n = node(class); table.insert(created, n); return n end)
	local player = node("Player")
	-- minimal Parent emulation: assigning Parent registers the child by Name
	local function show(c, v)
		pub.Show(player, c, v)
		for _, n in created do
			if n.Parent and n.Parent.kids then n.Parent.kids[n.Name] = n end
		end
	end
	show("Coins", 5)
	show("Coins", 6)
	Kit.eq(#created, 2, "folder + IntValue created once")
	Kit.eq(created[2].Value, 6)
end)

Kit.finish("wallet")
