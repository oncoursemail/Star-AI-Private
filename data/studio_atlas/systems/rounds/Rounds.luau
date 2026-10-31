--!strict
-- Round state machine: Intermission -> Round -> Cleanup -> Intermission. Driven by Step(dt) from one server
-- loop, so it is deterministic and testable. Players who join mid-round spectate until the next round starts.

export type State = "Intermission" | "Round" | "Cleanup"
export type Config = { minPlayers: number, intermission: number, roundLength: number, cleanup: number }
export type Hooks = {
	getPlayers: () -> { any },
	onState: (state: State, timeLeft: number) -> (), -- replicate to clients (attribute or RemoteEvent)
	startRound: (participants: { any }) -> (), -- spawn, teleport, give loadouts
	endRound: (winners: { any }, reason: string) -> (), -- reason: "timeout" | "lastStanding" | "empty"
	cleanup: () -> (), -- remove round-only objects
}
export type Rounds = {
	Step: (self: Rounds, dt: number) -> (),
	Eliminate: (self: Rounds, player: any) -> (),
	PlayerRemoving: (self: Rounds, player: any) -> (),
	GetState: (self: Rounds) -> (State, number),
	IsParticipant: (self: Rounds, player: any) -> boolean,
}

local Machine = {}

function Machine.new(cfg: Config, hooks: Hooks): Rounds
	local state: State = "Intermission"
	local timeLeft = cfg.intermission
	local alive: { [any]: boolean } = {}
	local startedWith = 0
	local rounds = {} :: Rounds

	local function enter(next: State, duration: number)
		state, timeLeft = next, duration
		hooks.onState(state, timeLeft)
	end

	local function aliveList(): { any }
		local list = {}
		for player in alive do
			table.insert(list, player)
		end
		return list
	end

	local function finish(reason: string)
		hooks.endRound(aliveList(), reason)
		enter("Cleanup", cfg.cleanup)
	end

	function rounds.Step(_self, dt)
		timeLeft -= dt
		if state == "Intermission" then
			local players = hooks.getPlayers()
			if #players < cfg.minPlayers then
				timeLeft = cfg.intermission -- wait for enough players, restart the countdown
			elseif timeLeft <= 0 then
				alive = {}
				for _, player in players do
					alive[player] = true
				end
				startedWith = #players
				hooks.startRound(players)
				enter("Round", cfg.roundLength)
			end
		elseif state == "Round" then
			local count = #aliveList()
			if count == 0 then
				finish("empty")
			elseif startedWith > 1 and count <= 1 then
				finish("lastStanding")
			elseif timeLeft <= 0 then
				finish("timeout")
			end
		elseif timeLeft <= 0 then
			hooks.cleanup()
			alive = {}
			enter("Intermission", cfg.intermission)
		end
	end

	function rounds.Eliminate(_self, player)
		alive[player] = nil
	end

	function rounds.PlayerRemoving(_self, player)
		alive[player] = nil -- the next Step ends the round if nobody is left
	end

	function rounds.GetState(_self)
		return state, math.max(0, timeLeft)
	end

	function rounds.IsParticipant(_self, player)
		return alive[player] == true
	end

	return rounds
end

return Machine
