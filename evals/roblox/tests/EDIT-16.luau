local ret, env = load_answer()
local S = ret
local spawns = {
	{ name = "A", position = { x = 0, y = 0, z = 0 } },
	{ name = "B", position = { x = 100, y = 0, z = 0 } },
	{ name = "C", position = { x = 50, y = 0, z = 0 } },
}
local enemies = { { x = 5, y = 0, z = 0 } }
check("the spawn farthest from the enemies", S.pick(spawns, enemies).name == "B")
local two = { { x = 0, y = 0, z = 0 }, { x = 100, y = 0, z = 0 } }
check("nearest enemy decides: the middle spawn", S.pick(spawns, two).name == "C")
spawns[2].blocked = true
check("blocked spawns are skipped", S.pick(spawns, enemies).name == "C")
check("no enemies: the first unblocked spawn", S.pick(spawns, {}).name == "A")
spawns[1].blocked = true
check("no enemies, first blocked: the next one", S.pick(spawns, {}).name == "C")
check("all blocked gives nil", S.pick({ { name = "X", position = { x = 0, y = 0, z = 0 }, blocked = true } }, enemies) == nil)
check("ranked still sorts safest first", S.ranked(spawns, enemies)[1].name == "B")
