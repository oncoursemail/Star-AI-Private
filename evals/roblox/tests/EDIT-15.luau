local ret, env = load_answer()
local Streaks = ret
local s = Streaks.new()
local p = {}
local rewards = {}
for i = 1, 6 do rewards[i] = s:kill(p) or false end
check("reward at exactly 3", rewards[3] == "RadarPing")
check("no reward at 4 or 6", rewards[4] == false and rewards[6] == false)
check("reward at exactly 5", rewards[5] == "PaintGrenade")
s:death(p)
check("death resets the streak", s:streakOf(p) == 0)
check("bestOf exists and survives death", type(s.bestOf) == "function" and s:bestOf(p) == 6)
s:kill(p); s:kill(p)
check("the best stays after a shorter streak", s:bestOf(p) == 6 and s:streakOf(p) == 2)
check("rewards counted", s:rewardsGiven(p) == 2)
for _ = 1, 8 do s:kill(p) end
check("airstrike at 10 and a new best", s:streakOf(p) == 10 and s:bestOf(p) == 10 and s:rewardsGiven(p) == 5)
