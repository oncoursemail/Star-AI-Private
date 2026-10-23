local Kit = require("../../testkit")
local Profiles = require("./Profile")

local function setup(overrides)
	local clock, store = Kit.clock(), Kit.datastore()
	local waits = {}
	local cfg = {
		store = store, jobId = "A", now = clock.now, schemaVersion = 2,
		wait = function(s) table.insert(waits, s) end,
		spawn = function(fn) fn() end,
		defaults = { Coins = 0, Settings = { Music = true } },
		migrations = { [1] = function(d) d.Coins = d.Gold or 0; d.Gold = nil; return d end },
	}
	for k, v in overrides or {} do cfg[k] = v end
	return Profiles.new(cfg), store, clock, waits, cfg
end

Kit.test("new key gets defaults and a lock", function()
	local m, store = setup()
	local p = m:Load("u1")
	Kit.eq(p.Data.Coins, 0)
	Kit.eq(store.data.u1.Lock.JobId, "A")
	Kit.eq(store.data.u1.SchemaVersion, 2)
end)

Kit.test("save and release round trip", function()
	local m, store = setup()
	local p = m:Load("u1")
	p.Data.Coins = 50
	Kit.truthy(p:Save())
	Kit.truthy(p:Release())
	Kit.eq(store.data.u1.Data.Coins, 50)
	Kit.eq(store.data.u1.Lock, nil)
	Kit.eq(p:Save(), false, "a released profile cannot save")
end)

Kit.test("a second server cannot load a locked key, after retries", function()
	local m1, store, clock = setup()
	Kit.truthy(m1:Load("u1"))
	local m2, _, _, waits = setup({ store = store, jobId = "B", now = clock.now })
	local p, why = m2:Load("u1")
	Kit.eq(p, nil)
	Kit.eq(why, "locked")
	Kit.eq(#waits, 5, "six attempts, five backoff waits")
	Kit.eq(waits[3], 4, "exponential backoff")
end)

Kit.test("a stale lock from a crashed server is taken over and the old owner loses", function()
	local m1, store, clock = setup()
	local old = m1:Load("u1")
	clock.advance(301)
	local m2 = setup({ store = store, jobId = "B", now = clock.now })
	Kit.truthy(m2:Load("u1"))
	old.Data.Coins = 999
	Kit.eq(old:Save(), false)
	Kit.eq(old.Active, false)
	Kit.eq(store.data.u1.Data.Coins, 0, "the lost server must not overwrite")
end)

Kit.test("DataStore errors are retried", function()
	local m, store, _, waits = setup()
	store.failures = 2
	Kit.truthy(m:Load("u1"))
	Kit.eq(#waits, 2)
end)

Kit.test("gives up after the attempts and reports a datastore failure", function()
	local m, store = setup()
	store.failures = 99
	local p, why = m:Load("u1")
	Kit.eq(p, nil)
	Kit.eq(why, "datastore")
end)

Kit.test("migrations run in order and defaults fill new keys", function()
	local m, store = setup()
	store.data.u1 = { SchemaVersion = 1, Data = { Gold = 7 } }
	local p = m:Load("u1")
	Kit.eq(p.Data.Coins, 7)
	Kit.eq(p.Data.Gold, nil)
	Kit.eq(p.Data.Settings.Music, true)
	Kit.eq(store.data.u1.SchemaVersion, 2)
end)

Kit.test("data from a newer game version is never loaded or downgraded", function()
	local m, store = setup()
	store.data.u1 = { SchemaVersion = 3, Data = { Coins = 1 } }
	local p, why = m:Load("u1")
	Kit.eq(p, nil)
	Kit.eq(why, "newer")
	Kit.eq(store.data.u1.SchemaVersion, 3)
end)

Kit.test("a missing migration is rejected at construction", function()
	Kit.eq(pcall(Profiles.new, { schemaVersion = 3, migrations = { [1] = function(d) return d end } }), false)
end)

Kit.test("ReleaseAll saves and unlocks every profile (BindToClose)", function()
	local m, store = setup()
	local a, b = m:Load("a"), m:Load("b")
	a.Data.Coins, b.Data.Coins = 1, 2
	local registered
	m:BindToClose({ BindToClose = function(_, fn) registered = fn end })
	registered()
	Kit.eq(store.data.a.Data.Coins, 1)
	Kit.eq(store.data.b.Lock, nil)
	Kit.eq(b.Active, false)
end)

Kit.finish("profile")
