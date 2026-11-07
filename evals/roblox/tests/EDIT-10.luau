local ret, env = load_answer()
local KillFeed = ret
local f = KillFeed.new(3, 5)
for i = 1, 6 do f:push("k" .. i, "v" .. i, "paintball", i) end
check("at most maxEntries are kept", f:count() == 3)
check("the newest stay, newest first", f.entries[1].killer == "k6" and f.entries[3].killer == "k4")
local v = f:visible(9.5)
check("visible returns the live entries", #v == 2 and v[1].killer == "k6" and v[2].killer == "k5")
check("visible removed the expired entry from the list", f:count() == 2)
check("format still works", f:format(f.entries[1]) == "k6 splatted v6")
check("lines", #f:lines(9.5) == 2)
f:visible(100)
check("everything expires", f:count() == 0)
