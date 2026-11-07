local Kit = require("../../testkit")
local Quests = require("./Quests")

local function setup()
	local rewards, progress = {}, {}
	local tracker = Quests.new({
		quests = {
			hunt = { title = "Hunt", objectives = { { kind = "kill", target = "Zombie", count = 3 }, { kind = "collect", target = "Bone", count = 2 } } },
			boss = { title = "Boss", requires = { "hunt" }, objectives = { { kind = "kill", target = "Boss", count = 1 } } },
			daily = { title = "Daily", repeatable = true, objectives = { { kind = "login", target = "day", count = 1 } } },
		},
		maxActive = 2,
		onComplete = function(_, id) table.insert(rewards, id) end,
		onProgress = function(_, id, p) progress[id] = table.clone(p) end,
	})
	local player, state = Kit.player(1), { Active = {}, Completed = {} }
	tracker:Attach(player, state)
	return tracker, player, state, rewards, progress
end

Kit.test("objectives advance, clamp, and the quest completes once", function()
	local t, p, _, rewards = setup()
	Kit.truthy(t:Accept(p, "hunt"))
	t:Report(p, "kill", "Zombie", 2)
	t:Report(p, "kill", "Zombie", 5) -- overshoot clamps at 3
	Kit.eq(t:Progress(p, "hunt")[1], 3)
	Kit.eq(#rewards, 0)
	t:Report(p, "collect", "Bone")
	t:Report(p, "collect", "Bone")
	Kit.eq(rewards[1], "hunt")
	Kit.eq(t:IsCompleted(p, "hunt"), true)
	t:Report(p, "kill", "Zombie")
	Kit.eq(#rewards, 1, "no second reward")
end)

Kit.test("events that do not match change nothing", function()
	local t, p, _, _, progress = setup()
	t:Accept(p, "hunt")
	t:Report(p, "kill", "Skeleton")
	t:Report(p, "collect", "Zombie")
	t:Report(p, "kill", "Zombie", -4)
	t:Report(p, "kill", "Zombie", 0.5)
	Kit.eq(progress.hunt, nil)
	Kit.eq(t:Progress(p, "hunt")[1], 0)
end)

Kit.test("requirements, duplicates, completed and the active limit are enforced", function()
	local t, p = setup()
	Kit.eq(select(2, t:Accept(p, "boss")), "requirement missing")
	Kit.truthy(t:Accept(p, "hunt"))
	Kit.eq(select(2, t:Accept(p, "hunt")), "already active")
	Kit.truthy(t:Accept(p, "daily"))
	t:Report(p, "login", "day")
	Kit.truthy(t:Accept(p, "daily"), "repeatable can be taken again")
	Kit.eq(select(2, t:Accept(p, "nope")), "unknown quest")
	t:Report(p, "kill", "Zombie", 3)
	t:Report(p, "collect", "Bone", 2)
	Kit.truthy(t:Accept(p, "boss"))
	Kit.eq(select(2, t:Accept(p, "hunt")), "already completed")
end)

Kit.test("abandon drops progress", function()
	local t, p = setup()
	t:Accept(p, "hunt")
	t:Report(p, "kill", "Zombie")
	t:Abandon(p, "hunt")
	Kit.eq(t:Progress(p, "hunt"), nil)
	t:Accept(p, "hunt")
	Kit.eq(t:Progress(p, "hunt")[1], 0)
end)

Kit.test("saved state is repaired on attach", function()
	local t = setup()
	local fresh = { Active = { gone = { 1 }, hunt = { 99, "x" } }, Completed = {} }
	t:Attach(Kit.player(5), fresh)
	Kit.eq(fresh.Active.gone, nil)
	Kit.eq(fresh.Active.hunt[1], 3)
	Kit.eq(fresh.Active.hunt[2], 0)
end)

Kit.finish("quests")
