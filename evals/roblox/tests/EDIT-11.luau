local ret, env = load_answer()
local RateLimiter = ret
local now = 0
local r = RateLimiter.new(10, 1, function() return now end)
local p = {}
local allowed = 0
for _ = 1, 15 do if r:allow(p) then allowed += 1 end end
check("exactly 10 calls per window", allowed == 10)
check("blocked calls are counted in stats", r:stats().blocked == 5)
check("blocked calls do not count toward the window", r.records[p].count == 10 and r:remaining(p) == 0)
now = 1
check("a new window allows calls again", r:allow(p) == true and r:remaining(p) == 9)
check("forget exists", type(r.forget) == "function")
r:forget(p)
check("forget removes the player", r:stats().players == 0 and r:remaining(p) == 10)
local calls = 0
local h = RateLimiter.new(2, 1, function() return now end):wrap(function() calls += 1 end)
h(p); h(p); h(p)
check("wrap still limits", calls == 2)
