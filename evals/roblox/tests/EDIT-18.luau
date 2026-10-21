local ret, env = load_answer()
local EventBus = ret
local bus = EventBus.new()
local log = {}
local c1
c1 = bus:on("Splat", function() table.insert(log, "a"); c1.disconnect() end)
bus:on("Splat", function() table.insert(log, "b") end)
bus:emit("Splat")
check("a self-disconnecting handler does not skip the next one", log[1] == "a" and log[2] == "b" and #log == 2)
bus:emit("Splat")
check("the disconnected handler is gone", #log == 3 and log[3] == "b")
check("once exists", type(bus.once) == "function")
local n = 0
if bus.once then bus:once("Flag", function(team) n += 1; check("once passes arguments", team == "Red") end) end
bus:emit("Flag", "Red")
bus:emit("Flag", "Red")
check("once runs only for the next emit", n == 1)
check("once leaves no listener behind", bus:listeners("Flag") == 0)
check("count still counts emits", bus:count("Flag") == 2 and bus:count("Splat") == 2)
