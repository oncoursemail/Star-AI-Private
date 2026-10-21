local ret, env = load_answer()
local B = ret
local teams = { { name = "Red", players = { "a" }, score = 5 }, { name = "Blue", players = { "b" }, score = 2 } }
check("a tie goes to the lower score", B.assign(teams, "c").name == "Blue")
check("otherwise the smaller team", B.assign(teams, "d").name == "Red")
local t2 = { { name = "Red", players = {}, score = 1 }, { name = "Blue", players = {}, score = 3 } }
check("empty teams: lower score", B.assign(t2, "x").name == "Red")
check("rebalance exists", type(B.rebalance) == "function")
local uneven = { { name = "Red", players = { "p1", "p2", "p3", "p4", "p5" }, score = 0 }, { name = "Blue", players = { "p6" }, score = 0 } }
local moved = B.rebalance and B.rebalance(uneven) or {}
check("rebalance evens the sizes", #uneven[1].players == 3 and #uneven[2].players == 3)
check("the most recent joiners move first", moved[1] == "p5" and moved[2] == "p4" and #moved == 2)
local fine = { { name = "Red", players = { "a", "b" }, score = 0 }, { name = "Blue", players = { "c" }, score = 0 } }
check("sizes within 1 are left alone", B.rebalance ~= nil and #B.rebalance(fine) == 0)
check("remove and teamOf still work", B.remove(teams, "a").name == "Red" and B.teamOf(teams, "c").name == "Blue")
