local ret, env = load_answer()
local RoundTimer = ret
local t = RoundTimer.new(3)
local finished, seconds = 0, {}
t:onFinished(function() finished += 1 end)
t:onSecond(function(s) table.insert(seconds, s) end)
t:start()
for _ = 1, 50 do t:step(0.25) end
check("finished handlers ran exactly once", finished == 1)
check("remaining stops at 0", t.remaining == 0)
check("the timer stops running at the end", t:isRunning() == false)
local negative = false
for _, s in seconds do if s < 0 then negative = true end end
check("onSecond never reports a negative number", not negative and #seconds > 0)
local f = RoundTimer.new(65)
check("format pads seconds", f:format() == "1:05")
local g = RoundTimer.new(600)
check("format of 10 minutes", g:format() == "10:00")
local h = RoundTimer.new(9)
check("format under a minute", h:format() == "0:09")
check("format at the end", t:format() == "0:00")
