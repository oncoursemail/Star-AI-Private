---
id: gb-world-anim-attack-phases
category: animation
topics: combat timing, windup, active frames, recovery, input buffer, state machine
source: original
---
# Request
For my fighting game I need each attack to have windup, active and recovery phases with exact timings, plus a small input buffer so pressing attack slightly early during recovery chains the next hit. Animation markers drift with lag, so I want the timing in code. Can you write that as a module?

# Answer
A small time-based state machine: it owns the phase, advances it from `os.clock()` whenever `update` is called, buffers one input during the tail of an attack and starts it the moment recovery ends. Hitboxes and VFX subscribe to phase changes instead of guessing from the animation.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.AttackPhases
export type Phase = "Idle" | "Windup" | "Active" | "Recovery"
export type Attack = { name: string, windup: number, active: number, recovery: number }
export type Machine = {
	tryAttack: (attack: Attack) -> boolean,
	update: () -> Phase,
	interrupt: () -> (),
	phase: () -> Phase,
	current: () -> Attack?,
}

local AttackPhases = {}

function AttackPhases.new(bufferWindow: number, onPhase: (phase: Phase, attack: Attack?) -> ()): Machine
	local phase: Phase = "Idle"
	local attack: Attack? = nil
	local phaseEndsAt = 0
	local queued: Attack? = nil

	local function enter(newPhase: Phase, startTime: number)
		phase = newPhase
		if attack and newPhase == "Windup" then
			phaseEndsAt = startTime + attack.windup
		elseif attack and newPhase == "Active" then
			phaseEndsAt = startTime + attack.active
		elseif attack and newPhase == "Recovery" then
			phaseEndsAt = startTime + attack.recovery
		end
		onPhase(newPhase, attack)
	end

	local function start(nextAttack: Attack, startTime: number)
		attack = nextAttack
		enter("Windup", startTime)
	end

	local function update(): Phase
		local now = os.clock()
		-- Loop so a long gap between updates still passes through every phase in order.
		while phase ~= "Idle" and now >= phaseEndsAt do
			local endedAt = phaseEndsAt
			if phase == "Windup" then
				enter("Active", endedAt)
			elseif phase == "Active" then
				enter("Recovery", endedAt)
			else
				local nextAttack = queued
				queued = nil
				if nextAttack then
					start(nextAttack, endedAt)
				else
					attack = nil
					enter("Idle", endedAt)
				end
			end
		end
		return phase
	end

	local function remainingTotal(): number
		local current = attack
		if current == nil then
			return 0
		end
		local left = phaseEndsAt - os.clock()
		if phase == "Windup" then
			return left + current.active + current.recovery
		elseif phase == "Active" then
			return left + current.recovery
		end
		return left
	end

	return {
		tryAttack = function(nextAttack: Attack): boolean
			update()
			if phase == "Idle" then
				start(nextAttack, os.clock())
				return true
			end
			if queued == nil and phase ~= "Windup" and remainingTotal() <= bufferWindow then
				queued = nextAttack
				return true
			end
			return false
		end,
		update = update,
		interrupt = function()
			queued = nil
			if phase ~= "Idle" then
				attack = nil
				enter("Idle", os.clock())
			end
		end,
		phase = function(): Phase
			return phase
		end,
		current = function(): Attack?
			return attack
		end,
	}
end

return AttackPhases
```

- Phase boundaries are computed from the previous boundary, not from when `update` happened to run, so frame rate and server hitches do not stretch the timings.
- Only one input is buffered and never during windup, which stops mashing from queueing a long chain.
- Call `update` from Heartbeat on whichever side owns the combat (the server for authority, the client for prediction) and open the hitbox only while the phase is "Active".
- `interrupt` is the hook for stuns and parries: it clears the queue so a stunned player does not swing on recovery.

# Test
```lua
local log = {}
local machine = item.new(0.2, function(phase)
	table.insert(log, phase)
end)
local jab = { name = "Jab", windup = 0.1, active = 0.1, recovery = 0.3 }

check("starts from idle", machine.tryAttack(jab) and machine.phase() == "Windup")
check("cannot buffer during windup", machine.tryAttack(jab) == false)
__advance(0.15)
check("windup -> active on time", machine.update() == "Active")
__advance(0.1)
check("active -> recovery", machine.update() == "Recovery")
__advance(0.15)
check("input in the buffer window is accepted", machine.tryAttack(jab))
__advance(0.15)
check("buffered attack starts after recovery", machine.update() == "Windup")
machine.interrupt()
check("interrupt returns to idle", machine.phase() == "Idle" and machine.current() == nil)
machine.tryAttack(jab)
__advance(2)
check("a long gap walks every phase back to idle", machine.update() == "Idle" and log[#log] == "Idle" and log[#log - 1] == "Recovery")
```
