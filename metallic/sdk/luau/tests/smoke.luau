-- lune run tests/smoke.luau <baseUrl> <serverKey>   (run by metallic/tests/test_api_v1.py when LUNE_BIN is set)
local process = require("@lune/process")
local fs = require("@lune/fs")
local luau = require("@lune/luau")
local shim = require("./roblox_shim")

local base, key = process.args[1], process.args[2]
_G.SHIM_SECRETS.metallic_api_key = key

local source = fs.readFile("MetallicApi.luau")
local MetallicApi = luau.load(source, { debugName = "MetallicApi", environment = { game = shim.game } })()

-- refuses to run on a client
shim.RunService.server = false
assert(not pcall(MetallicApi.new, { baseUrl = base, secretName = "metallic_api_key" }), "must refuse on a client")
shim.RunService.server = true

local api = MetallicApi.new({ baseUrl = base, secretName = "metallic_api_key" })
local ok, games = api:listGames()
assert(ok and #games.games == 4, "listGames")
local ok2, hb = api:serverHeartbeat({ game = "RB", server_id = "lune-1", players = 9 })
assert(ok2 and hb.ok == true, "heartbeat")
local ok3, err = api:serverHeartbeat({ game = "MC", server_id = "lune-1", players = 1 })
assert(not ok3 and err.status == 403 and err.error == "wrong_game", "wrong game refused")
local ok4, who = api:verifyPlayer({ player_token = "eyJhbGciOiJFUzI1NiJ9.teen.sig" })  -- star:allow (test fixture)
assert(ok4 and who.minor == true and who.username == nil, "minor without a name")
local ok5, rel = api:getRelease("beta")
assert(ok5 and rel.verified == true, "release")
local anon = MetallicApi.new({ baseUrl = base })
local ok6, e6 = anon:serverHeartbeat({ game = "RB", server_id = "x", players = 1 })
assert(not ok6 and e6.status == 401, "no key refused")
print("SMOKE OK")
