local ret, env = load_answer()
local C = ret
local now = 100
C.clock = function() return now end
local a, b = {}, {}
check("a uses dash", C.use(a, "dash") == true)
check("b's dash is still ready", C.ready(b, "dash") == true and C.use(b, "dash") == true)
check("a's dash is on cooldown", C.use(a, "dash") == false and C.remaining(a, "dash") == 3)
now = 103
check("a's dash is ready after 3 seconds", C.ready(a, "dash") == true)
check("unknown abilities do not error", not throws(function() C.ready(a, "laser"); C.use(a, "laser") end))
check("unknown abilities return false", C.ready(a, "laser") == false and C.use(a, "laser") == false)
C.use(a, "shield"); C.use(b, "shield")
C.clear(a)
check("clear forgets that player's cooldowns", C.ready(a, "shield") == true)
check("clear keeps other players' cooldowns", C.ready(b, "shield") == false)
