local Kit = require("../../testkit")
local Admins = require("./Admin")
local L = Admins.Level

local function setup()
	local names = { owner = L.Owner, admin = L.Admin, mod = L.Mod, guest = L.User, other = L.Mod }
	local replies, audit, kicked = {}, {}, {}
	local admin = Admins.new({
		prefix = "!",
		getLevel = function(p) return names[p] or 0 end,
		findPlayer = function(q) return if names[q] then q else nil end,
		reply = function(p, text) table.insert(replies, p .. ":" .. text) end,
		audit = function(p, line, ok) table.insert(audit, p .. ":" .. line .. ":" .. tostring(ok)) end,
	})
	admin:Register({ name = "kick", aliases = { "k" }, level = L.Mod, args = { "player", "rest" }, outranks = true,
		run = function(_, target, reason) table.insert(kicked, target .. "|" .. reason) end })
	admin:Register({ name = "speed", level = L.Admin, args = { "player", "number" },
		run = function(ctx, target, n) ctx.reply(target .. "=" .. n) end })
	admin:Register({ name = "crash", level = L.Mod, args = {}, run = function() error("bug") end })
	return admin, replies, audit, kicked
end

Kit.test("a mod can kick a lower-level player with a quoted or free-form reason", function()
	local admin, _, _, kicked = setup()
	Kit.truthy(admin:Run("mod", "!kick guest being rude to everyone"))
	Kit.truthy(admin:Run("mod", '!k guest "x y"'))
	Kit.eq(kicked[1], "guest|being rude to everyone")
	Kit.eq(kicked[2], "guest|x y")
end)

Kit.test("below the required level the command looks unknown", function()
	local admin, replies = setup()
	local ok, why = admin:Run("mod", "!speed guest 50")
	Kit.eq(ok, false)
	Kit.eq(why, "unknown command")
	Kit.eq(select(2, admin:Run("guest", "!kick mod")), "unknown command")
	Kit.eq(replies[1], "mod:unknown command")
end)

Kit.test("cannot target equal or higher level when outranks is set", function()
	local admin, _, _, kicked = setup()
	Kit.eq(select(2, admin:Run("mod", "!kick other bye")), "target has equal or higher permission")
	Kit.eq(select(2, admin:Run("mod", "!kick admin bye")), "target has equal or higher permission")
	Kit.truthy(admin:Run("owner", "!kick admin bye"))
	Kit.eq(#kicked, 1)
end)

Kit.test("argument parsing: numbers, missing arguments, unknown players", function()
	local admin, replies = setup()
	Kit.truthy(admin:Run("admin", "!speed guest 32.5"))
	Kit.eq(replies[1], "admin:guest=32.5")
	Kit.eq(select(2, admin:Run("admin", "!speed guest fast")), "argument 2 must be a number")
	Kit.eq(select(2, admin:Run("admin", "!speed guest nan")), "argument 2 must be a number")
	Kit.eq(select(2, admin:Run("admin", "!speed guest inf")), "argument 2 must be a number")
	Kit.eq(select(2, admin:Run("admin", "!speed guest")), "missing argument 2")
	Kit.eq(select(2, admin:Run("admin", "!speed nobody 5")), "no player nobody")
end)

Kit.test("non-commands are ignored; errors are contained; everything is audited", function()
	local admin, replies, audit = setup()
	Kit.eq(select(2, admin:Run("mod", "hello")), "not a command")
	local ok = admin:Run("mod", "!crash")
	Kit.eq(ok, false)
	Kit.eq(replies[#replies], "mod:command failed")
	Kit.eq(audit[1], "mod:!crash:false")
end)

Kit.test("duplicate command names are rejected", function()
	local admin = setup()
	Kit.eq(pcall(admin.Register, admin, { name = "K", level = 0, args = {}, run = function() end }), false)
end)

Kit.finish("admin")
