Reference fix.

```lua
--!strict
-- AmmoService: magazine + reserve paintballs per player for the paintball markers.
local AmmoService = {}

export type AmmoState = {
	magazine: number,
	reserve: number,
	reloading: boolean,
}

local MAGAZINE_SIZE = 20
local START_RESERVE = 60
local MAX_RESERVE = 120
local states: { [any]: AmmoState } = {}

local function newState(): AmmoState
	return { magazine = MAGAZINE_SIZE, reserve = START_RESERVE, reloading = false }
end

function AmmoService.get(player: any): AmmoState
	local state = states[player]
	if state == nil then
		state = newState()
		states[player] = state
	end
	return state
end

-- Fires one paintball. Returns true when a shot was fired.
function AmmoService.fire(player: any): boolean
	local state = AmmoService.get(player)
	if state.reloading or state.magazine <= 0 then
		return false
	end
	state.magazine -= 1
	return true
end

-- Refills the magazine from the reserve. Returns how many paintballs were moved.
function AmmoService.reload(player: any): number
	local state = AmmoService.get(player)
	if state.reloading then
		return 0
	end
	state.reloading = true
	local missing = math.min(MAGAZINE_SIZE - state.magazine, state.reserve)
	state.magazine += missing
	state.reserve -= missing
	state.reloading = false
	return missing
end

function AmmoService.addReserve(player: any, amount: number)
	local state = AmmoService.get(player)
	state.reserve = math.min(MAX_RESERVE, state.reserve + amount)
end

function AmmoService.reset(player: any)
	states[player] = newState()
end

function AmmoService.remove(player: any)
	states[player] = nil
end

return AmmoService
```
