---
id: gb-world-round-state-machine
category: round-systems
topics: round loop, state machine, intermission, minimum players, attributes
source: original
---
# Request
My round loop is one giant `while true do` with `task.wait(15)` for intermission and `task.wait(120)` for the round. I can't end a round early when someone wins, and if everyone leaves during intermission it starts a round with zero players. How should I structure it?

# Answer
Make the round flow an explicit state machine (Waiting, Intermission, Playing, Results) that is advanced by a cheap `update` call with the current time, player count and whether the round has been decided. Each transition is decided in one place, early endings are just a flag, and the current state and time left are published as attributes for the UI.

```lua
--!strict
-- ModuleScript: ServerScriptService.RoundStateMachine
export type State = "Waiting" | "Intermission" | "Playing" | "Results"
export type Config = { minPlayers: number, intermission: number, roundLength: number, results: number }
export type Machine = {
	update: (now: number, playerCount: number, decided: boolean) -> State,
	state: () -> State,
	timeLeft: (now: number) -> number,
}

local RoundStateMachine = {}

function RoundStateMachine.new(config: Config, onEnter: (state: State) -> ()): Machine
	local state: State = "Waiting"
	local endsAt = 0

	local function enter(newState: State, now: number, duration: number)
		state = newState
		endsAt = now + duration
		onEnter(newState)
	end

	local function update(now: number, playerCount: number, decided: boolean): State
		local enough = playerCount >= config.minPlayers
		if state == "Waiting" then
			if enough then
				enter("Intermission", now, config.intermission)
			end
		elseif state == "Intermission" then
			if not enough then
				enter("Waiting", now, 0)
			elseif now >= endsAt then
				enter("Playing", now, config.roundLength)
			end
		elseif state == "Playing" then
			if decided or playerCount == 0 or now >= endsAt then
				enter("Results", now, config.results)
			end
		elseif now >= endsAt then
			if enough then
				enter("Intermission", now, config.intermission)
			else
				enter("Waiting", now, 0)
			end
		end
		return state
	end

	return {
		update = update,
		state = function(): State
			return state
		end,
		timeLeft = function(now: number): number
			return math.max(0, endsAt - now)
		end,
	}
end

return RoundStateMachine
```

The server Script that drives it:

```lua
--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RoundStateMachine = require(script.Parent:WaitForChild("RoundStateMachine"))

local roundDecided = false

local machine = RoundStateMachine.new(
	{ minPlayers = 2, intermission = 15, roundLength = 120, results = 8 },
	function(state)
		ReplicatedStorage:SetAttribute("RoundState", state)
		if state == "Playing" then
			roundDecided = false
		end
	end
)

while true do
	local now = os.clock()
	machine.update(now, #Players:GetPlayers(), roundDecided)
	ReplicatedStorage:SetAttribute("TimeLeft", math.ceil(machine.timeLeft(now)))
	task.wait(0.25)
end
```

- Ending early is a flag (`roundDecided = true` from your win check); the next update moves to Results without waiting out the timer.
- Losing players during intermission returns to Waiting instead of starting a round nobody can play.
- Attributes on ReplicatedStorage replicate to every client and fire `GetAttributeChangedSignal`, so the HUD needs no remotes.
- The machine never yields, which makes it trivial to test and impossible to leave stuck in a half-finished `task.wait`.

# Test
```lua
local entered = {}
local machine = item.new({ minPlayers = 2, intermission = 10, roundLength = 60, results = 5 }, function(state)
	table.insert(entered, state)
end)
check("waits for players", machine.update(0, 1, false) == "Waiting")
check("enough players start intermission", machine.update(1, 2, false) == "Intermission" and machine.timeLeft(1) == 10)
check("losing players cancels intermission", machine.update(5, 1, false) == "Waiting")
machine.update(6, 3, false)
check("round starts after intermission", machine.update(16, 3, false) == "Playing")
check("early win ends the round", machine.update(20, 3, true) == "Results")
check("results then next intermission", machine.update(25, 3, false) == "Intermission")
machine.update(35, 3, false)
check("round times out", machine.update(95, 3, false) == "Results")
check("everyone leaving during results goes back to waiting", machine.update(100, 0, false) == "Waiting")
check("callbacks fired for each transition", #entered == 9 and entered[#entered] == "Waiting")
```
