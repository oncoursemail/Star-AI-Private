local ret, env = load_answer()
local L = ret
local entries = {
	{ name = "Cara", kills = 5, deaths = 3 },
	{ name = "Alex", kills = 9, deaths = 4 },
	{ name = "Bea", kills = 5, deaths = 1 },
	{ name = "Dan", kills = 5, deaths = 1 },
}
local r = L.rank(entries)
check("most kills first", r[1].name == "Alex" and r[1].rank == 1)
check("ties: fewer deaths first, then name", r[2].name == "Bea" and r[3].name == "Dan" and r[4].name == "Cara")
check("rank is not written into the caller's entries", entries[1].rank == nil and entries[2].rank == nil)
check("the caller's list order is unchanged", entries[1].name == "Cara")
check("kdr with 0 deaths is the kill count", L.kdr({ name = "Z", kills = 4, deaths = 0 }) == 4)
check("kdr otherwise divides", L.kdr({ name = "Z", kills = 6, deaths = 3 }) == 2)
check("top(2)", #L.top(entries, 2) == 2 and L.top(entries, 2)[2].name == "Bea")
check("mvp", L.mvp(entries) == "Alex")
check("format works with 0 deaths", not throws(function() L.lines({ { name = "Z", kills = 1, deaths = 0 } }) end))
