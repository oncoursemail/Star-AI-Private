---
id: gb-eng-state-machine-enemy
category: engineering-algorithm
topics: finite state machine, enemy AI, enter exit hooks, transitions, update loop
source: original
---
# Request
My enemy AI is a big `if state == "patrol" ... elseif state == "chase"` block inside Heartbeat, and timers for each state are tangled together. How do I structure it as a proper state machine with enter/exit hooks and per-state update?

# Answer
A small FSM module: each state is a table with optional `enter`, `exit` and `update` functions; `update` may return the name of the next state. The machine tracks time spent in the current state, so states stop managing their own timers.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.StateMachine
export type State<C> = {
	enter: ((context: C) -> ())?,
	exit: ((context: C) -> ())?,
	update: ((context: C, dt: number, timeInState: number) -> string?)?,
}

export type Machine<C> = {
	current: string,
	timeInState: number,
	states: { [string]: State<C> },
	context: C,
}

local StateMachine = {}

function StateMachine.new<C>(states: { [string]: State<C> }, initial: string, context: C): Machine<C>
	assert(states[initial], `unknown initial state {initial}`)
	local machine = { current = initial, timeInState = 0, states = states, context = context }
	local enter = states[initial].enter
	if enter then
		enter(context)
	end
	return machine
end

function StateMachine.transition<C>(machine: Machine<C>, nextState: string): ()
	local target = machine.states[nextState]
	assert(target, `unknown state {nextState}`)
	if nextState == machine.current then
		return
	end
	local exit = machine.states[machine.current].exit
	if exit then
		exit(machine.context)
	end
	machine.current = nextState
	machine.timeInState = 0
	if target.enter then
		target.enter(machine.context)
	end
end

function StateMachine.update<C>(machine: Machine<C>, dt: number): ()
	machine.timeInState += dt
	local update = machine.states[machine.current].update
	if update then
		local nextState = update(machine.context, dt, machine.timeInState)
		if nextState then
			StateMachine.transition(machine, nextState)
		end
	end
end

return StateMachine
```

```lua
--!strict
-- Enemy states (server); `targetDistance` would come from your targeting code each frame
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local StateMachine = require(ReplicatedStorage.StateMachine)

type Enemy = { targetDistance: number, speed: number }

local enemy: Enemy = { targetDistance = math.huge, speed = 8 }
local brain = StateMachine.new({
	Patrol = {
		enter = function(e: Enemy) e.speed = 8 end,
		update = function(e: Enemy): string?
			return if e.targetDistance < 40 then "Chase" else nil
		end,
	},
	Chase = {
		enter = function(e: Enemy) e.speed = 18 end,
		update = function(e: Enemy, _dt: number, t: number): string?
			if e.targetDistance < 5 then
				return "Attack"
			end
			return if e.targetDistance > 60 or t > 15 then "Patrol" else nil
		end,
	},
	Attack = {
		enter = function(e: Enemy) e.speed = 0 end,
		update = function(_e: Enemy, _dt: number, t: number): string?
			return if t >= 0.8 then "Chase" else nil
		end,
	},
}, "Patrol", enemy)

game:GetService("RunService").Heartbeat:Connect(function(dt: number)
	StateMachine.update(brain, dt)
end)
```

- Each state owns its rules and the machine owns the bookkeeping, so adding a "Flee" state is one more table, not another branch in a giant `if`.
- `timeInState` resets on every transition, which replaces the separate `chaseStartedAt`, `attackStartedAt` variables that tend to go stale.
- Transitions to the current state are ignored, so `enter` effects (sounds, animations) do not replay every frame.

# Test
```lua
local log = {}
local ctx = { distance = 100 }
local m = item.new({
	Idle = {
		enter = function() table.insert(log, "enter Idle") end,
		exit = function() table.insert(log, "exit Idle") end,
		update = function(c) return if c.distance < 10 then "Alert" else nil end,
	},
	Alert = {
		enter = function() table.insert(log, "enter Alert") end,
		update = function(_, _, t) return if t >= 2 then "Idle" else nil end,
	},
}, "Idle", ctx)
check("initial enter ran", log[1] == "enter Idle" and m.current == "Idle")
item.update(m, 0.1)
check("stays idle while far", m.current == "Idle" and math.abs(m.timeInState - 0.1) < 1e-9)
ctx.distance = 5
item.update(m, 0.1)
check("exit then enter on transition", m.current == "Alert" and log[2] == "exit Idle" and log[3] == "enter Alert")
check("time resets on transition", m.timeInState == 0)
item.update(m, 1)
item.update(m, 1)
check("timed transition back", m.current == "Idle")
local before = #log
item.transition(m, "Idle")
check("self transition ignored", #log == before)
check("unknown state errors", not pcall(item.transition, m, "Nope"))
```
