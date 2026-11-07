local Kit = require("../../testkit")
local Combats = require("./Combat")

local function setup(overrides)
	local clock, damage = Kit.clock(0), {}
	local bodies = {
		a = { position = { X = 0, Y = 0, Z = 0 }, health = 100, team = "Red" },
		b = { position = { X = 10, Y = 0, Z = 0 }, health = 100, team = "Blue" },
	}
	local clear = true
	local cfg = {
		now = clock.now,
		weapons = { Sword = { damage = 20, range = 8, cooldown = 1 }, Bow = { damage = 10, range = 100, cooldown = 0.5 } },
		getCombatant = function(e) return bodies[e] end,
		hasLineOfSight = function() return clear end,
		applyDamage = function(target, amount, attacker, weapon) table.insert(damage, { target, amount, attacker, weapon }) end,
	}
	for k, v in overrides or {} do cfg[k] = v end
	local combat = Combats.new(cfg)
	return combat, clock, damage, bodies, function(v) clear = v end
end

Kit.test("a valid hit applies the server's damage for the equipped weapon", function()
	local combat, _, damage = setup()
	Kit.truthy(combat:Equip("a", "Sword"))
	Kit.truthy(combat:TryHit("a", "b")) -- distance 10 <= range 8 + leeway 6
	Kit.eq(damage[1][2], 20)
	Kit.eq(damage[1][4], "Sword")
end)

Kit.test("no weapon, unknown weapon, not owned", function()
	local combat = setup({ owns = function() return false end })
	Kit.eq(select(2, combat:TryHit("a", "b")), "no weapon equipped")
	Kit.eq(combat:Equip("a", "Laser"), false)
	Kit.eq(combat:Equip("a", "Sword"), false, "not owned")
end)

Kit.test("cooldown blocks rapid fire and expires", function()
	local combat, clock, damage = setup()
	combat:Equip("a", "Sword")
	Kit.truthy(combat:TryHit("a", "b"))
	Kit.eq(select(2, combat:TryHit("a", "b")), "cooldown")
	clock.advance(0.95) -- inside the 10 % jitter allowance
	Kit.truthy(combat:TryHit("a", "b"))
	Kit.eq(#damage, 2)
end)

Kit.test("range uses server positions", function()
	local combat, _, _, bodies = setup()
	combat:Equip("a", "Sword")
	bodies.b.position.X = 40
	Kit.eq(select(2, combat:TryHit("a", "b")), "out of range")
	combat:Equip("a", "Bow")
	Kit.truthy(combat:TryHit("a", "b"))
end)

Kit.test("walls, dead bodies, friendly fire and self hits are refused", function()
	local combat, _, _, bodies, setClear = setup()
	combat:Equip("a", "Bow")
	setClear(false)
	Kit.eq(select(2, combat:TryHit("a", "b")), "no line of sight")
	setClear(true)
	bodies.b.team = "Red"
	Kit.eq(select(2, combat:TryHit("a", "b")), "same team")
	bodies.b.team = "Blue"
	bodies.b.health = 0
	Kit.eq(select(2, combat:TryHit("a", "b")), "not alive")
	Kit.eq(select(2, combat:TryHit("a", "a")), "self hit")
	Kit.eq(select(2, combat:TryHit("a", "ghost")), "not alive")
end)

Kit.test("a refused hit does not start the cooldown", function()
	local combat, _, damage, bodies = setup()
	combat:Equip("a", "Sword")
	bodies.b.position.X = 50
	combat:TryHit("a", "b")
	bodies.b.position.X = 5
	Kit.truthy(combat:TryHit("a", "b"))
	Kit.eq(#damage, 1)
end)

Kit.finish("combat")
