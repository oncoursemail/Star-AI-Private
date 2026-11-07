local Kit = require("../../testkit")
local Machine = require("./Rounds")

local function setup(playerCount)
	local players, log = {}, {}
	for i = 1, playerCount do table.insert(players, Kit.player(i)) end
	local rounds = Machine.new({ minPlayers = 2, intermission = 10, roundLength = 60, cleanup = 5 }, {
		getPlayers = function() return players end,
		onState = function(s) table.insert(log, s) end,
		startRound = function(p) table.insert(log, "start:" .. #p) end,
		endRound = function(w, reason) table.insert(log, "end:" .. reason .. ":" .. #w) end,
		cleanup = function() table.insert(log, "cleanup") end,
	})
	return rounds, players, log
end

local function run(rounds, seconds)
	for _ = 1, seconds do rounds:Step(1) end
end

Kit.test("full cycle: intermission, round, cleanup, intermission", function()
	local rounds, _, log = setup(3)
	run(rounds, 10)
	Kit.eq(rounds:GetState(), "Round")
	run(rounds, 60)
	Kit.eq(rounds:GetState(), "Cleanup")
	run(rounds, 5)
	Kit.eq(rounds:GetState(), "Intermission")
	Kit.eq(table.concat(log, ","), "start:3,Round,end:timeout:3,Cleanup,cleanup,Intermission")
end)

Kit.test("countdown restarts while there are too few players", function()
	local rounds, players = setup(1)
	run(rounds, 30)
	Kit.eq(rounds:GetState(), "Intermission")
	table.insert(players, Kit.player(2))
	run(rounds, 9)
	Kit.eq(rounds:GetState(), "Intermission")
	run(rounds, 1)
	Kit.eq(rounds:GetState(), "Round")
end)

Kit.test("round ends when one player is left standing", function()
	local rounds, players, log = setup(3)
	run(rounds, 10)
	rounds:Eliminate(players[1])
	rounds:PlayerRemoving(players[2]) -- leaving counts as elimination
	rounds:Step(1)
	Kit.eq(rounds:GetState(), "Cleanup")
	Kit.truthy(table.find(log, "end:lastStanding:1"))
end)

Kit.test("a player who joins mid-round spectates until the next round", function()
	local rounds, players = setup(2)
	run(rounds, 10)
	local late = Kit.player(9)
	table.insert(players, late)
	Kit.eq(rounds:IsParticipant(late), false)
	Kit.eq(rounds:IsParticipant(players[1]), true)
	run(rounds, 60 + 5 + 10)
	Kit.eq(rounds:GetState(), "Round")
	Kit.eq(rounds:IsParticipant(late), true, "in the next round")
end)

Kit.test("everyone leaving ends the round as empty", function()
	local rounds, players, log = setup(2)
	run(rounds, 10)
	rounds:PlayerRemoving(players[1])
	rounds:PlayerRemoving(players[2])
	rounds:Step(1)
	Kit.truthy(table.find(log, "end:empty:0"))
end)

Kit.finish("rounds")
