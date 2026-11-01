local Kit = require("../../testkit")
local Inventories = require("./Inventory")

local items = { Potion = { maxStack = 5 }, Sword = { maxStack = 1 } }
local function make(saved, onChanged)
	return Inventories.new({ capacity = 3, items = items, onChanged = onChanged }, saved)
end

Kit.test("stacks fill existing partial stacks before opening slots", function()
	local inv = make()
	Kit.truthy(inv:Add("Potion", 3))
	Kit.truthy(inv:Add("Potion", 4))
	local s = inv:Serialize()
	Kit.eq(#s, 2)
	Kit.eq(s[1].count, 5)
	Kit.eq(s[2].count, 2)
	Kit.eq(inv:Count("Potion"), 7)
end)

Kit.test("capacity is enforced and a failed add changes nothing", function()
	local inv = make()
	Kit.truthy(inv:Add("Sword", 2))
	local ok, why = inv:Add("Potion", 6) -- needs 2 slots, only 1 free
	Kit.eq(ok, false)
	Kit.eq(why, "inventory full")
	Kit.eq(inv:Count("Potion"), 0)
	Kit.eq(#inv:Serialize(), 2)
end)

Kit.test("bad ids and counts are refused", function()
	local inv = make()
	Kit.eq((inv:Add("Nope", 1)), false)
	for _, bad in { 0, -1, 1.5, 0 / 0, math.huge } do
		Kit.eq((inv:Add("Potion", bad)), false)
		Kit.eq((inv:Remove("Potion", bad)), false)
	end
end)

Kit.test("remove is atomic and frees empty slots", function()
	local inv = make()
	inv:Add("Potion", 7)
	Kit.eq((inv:Remove("Potion", 8)), false)
	Kit.eq(inv:Count("Potion"), 7)
	Kit.truthy(inv:Remove("Potion", 6))
	Kit.eq(#inv:Serialize(), 1)
	Kit.truthy(inv:Has("Potion", 1))
	Kit.eq(inv:Has("Potion", 2), false)
end)

Kit.test("loading a saved inventory drops unknown items and clamps stacks", function()
	local inv = make({ { id = "Potion", count = 99 }, { id = "Ghost", count = 1 }, { id = "Sword", count = 1 } })
	Kit.eq(inv:Count("Potion"), 5)
	Kit.eq(inv:Count("Ghost"), 0)
	Kit.eq(inv:Count("Sword"), 1)
end)

Kit.test("onChanged fires only on real changes", function()
	local n = 0
	local inv = make(nil, function() n += 1 end)
	inv:Add("Potion", 1)
	inv:Add("Nope", 1)
	inv:Remove("Potion", 9)
	inv:Remove("Potion", 1)
	Kit.eq(n, 2)
end)

Kit.finish("inventory")
