local Kit = require("../../testkit")
local Remotes = require("./Remotes")
local t = Remotes.t

local function setup()
	local clock = Kit.clock(0)
	local rejects = {}
	local layer = Remotes.new({
		now = clock.now,
		onReject = function(_, name, reason) table.insert(rejects, name .. ": " .. reason) end,
	})
	return layer, clock, rejects
end

local player = Kit.player(1)

Kit.test("valid event reaches the handler with cleaned values", function()
	local layer = setup()
	local event = { OnServerEvent = Kit.signal() }
	local got
	layer:Bind("Buy", event, {
		kind = "event", args = { t.string(20), t.number(1, 10, true) }, rate = { perSecond = 2, burst = 4 },
		handler = function(p, item, qty) got = { p, item, qty } end,
	})
	event.OnServerEvent:Fire(player, "Sword", 3)
	Kit.eq(got[1], player)
	Kit.eq(got[2], "Sword")
	Kit.eq(got[3], 3)
end)

Kit.test("bad types, NaN, infinity, out of range and extra arguments are rejected", function()
	local layer, _, rejects = setup()
	local calls = 0
	layer:Bind("Buy", { OnServerEvent = Kit.signal() }, {
		kind = "event", args = { t.number(1, 10, true) }, rate = { perSecond = 100, burst = 100 },
		handler = function() calls += 1 end,
	})
	for _, bad in { "5", 0 / 0, math.huge, 11, 2.5, {} } do
		local ok = layer:Dispatch("Buy", player, bad)
		Kit.eq(ok, false)
	end
	Kit.eq((layer:Dispatch("Buy", player, 1, 2)), false, "extra argument")
	Kit.eq((layer:Dispatch("Buy", player)), false, "missing argument")
	Kit.eq(calls, 0)
	Kit.eq(#rejects, 8)
end)

Kit.test("rate limit: burst, then refill over time, per player", function()
	local layer, clock = setup()
	local calls = 0
	layer:Bind("Ping", { OnServerEvent = Kit.signal() }, {
		kind = "event", args = {}, rate = { perSecond = 1, burst = 3 }, handler = function() calls += 1 end,
	})
	for _ = 1, 5 do layer:Dispatch("Ping", player) end
	Kit.eq(calls, 3)
	clock.advance(2)
	for _ = 1, 5 do layer:Dispatch("Ping", player) end
	Kit.eq(calls, 5)
	Kit.eq((layer:Dispatch("Ping", Kit.player(2))), true, "another player has their own bucket")
end)

Kit.test("remote function returns the handler result, nil when rejected", function()
	local layer = setup()
	local remote = {}
	layer:Bind("Price", remote, {
		kind = "function", args = { t.oneOf({ "Sword", "Shield" }) }, rate = { perSecond = 5, burst = 5 },
		handler = function(_, item) return item == "Sword" and 100 or 50 end,
	})
	Kit.eq(remote.OnServerInvoke(player, "Sword"), 100)
	Kit.eq(remote.OnServerInvoke(player, "Bomb"), nil)
end)

Kit.test("shape rejects unknown fields; optional accepts nil", function()
	local v = t.shape({ id = t.string(8), note = t.optional(t.string(5)) })
	Kit.truthy((v({ id = "abc" })))
	Kit.eq((v({ id = "abc", admin = true })), false)
	Kit.eq((v({ id = "abc", note = "toolong" })), false)
end)

Kit.test("a throwing handler does not break the layer", function()
	local layer, _, rejects = setup()
	layer:Bind("Boom", { OnServerEvent = Kit.signal() }, {
		kind = "event", args = {}, rate = { perSecond = 5, burst = 5 }, handler = function() error("bug") end,
	})
	Kit.eq((layer:Dispatch("Boom", player)), false)
	Kit.eq(rejects[1], "Boom: handler error")
end)

Kit.finish("remotes")
