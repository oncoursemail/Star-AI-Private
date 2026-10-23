--!strict
-- Quest / objective tracker. Game systems report events (Report(player, "kill", "Zombie")); the tracker advances
-- every matching objective, completes the quest exactly once and hands the reward to your callback.
-- Per-player state is a plain table that belongs in the profile.

export type Objective = { kind: string, target: string, count: number }
export type QuestDef = { title: string, objectives: { Objective }, requires: { string }?, repeatable: boolean? }
export type State = { Active: { [string]: { number } }, Completed: { [string]: boolean } }
export type Config = {
	quests: { [string]: QuestDef },
	maxActive: number?, -- default 10
	onComplete: (player: any, questId: string, def: QuestDef) -> (), -- grant the reward here, server side
	onProgress: ((player: any, questId: string, progress: { number }) -> ())?, -- replicate to the client
}
export type Tracker = {
	Attach: (self: Tracker, player: any, state: State) -> (),
	Detach: (self: Tracker, player: any) -> (),
	Accept: (self: Tracker, player: any, questId: string) -> (boolean, string?),
	Abandon: (self: Tracker, player: any, questId: string) -> (),
	Report: (self: Tracker, player: any, kind: string, target: string, amount: number?) -> (),
	Progress: (self: Tracker, player: any, questId: string) -> { number }?,
	IsCompleted: (self: Tracker, player: any, questId: string) -> boolean,
}

local Quests = {}

function Quests.new(cfg: Config): Tracker
	local maxActive = cfg.maxActive or 10
	local states: { [any]: State } = {}
	local tracker = {} :: Tracker

	-- A saved state may be old (quest removed or objectives changed): keep only what still fits the definitions.
	function tracker.Attach(_self, player, state)
		state.Active = state.Active or {}
		state.Completed = state.Completed or {}
		for id, progress in state.Active do
			local def = cfg.quests[id]
			if def == nil then
				state.Active[id] = nil
			else
				for i, objective in def.objectives do
					local v = progress[i]
					progress[i] = if type(v) == "number" and v >= 0 then math.min(math.floor(v), objective.count) else 0
				end
			end
		end
		states[player] = state
	end

	function tracker.Detach(_self, player)
		states[player] = nil
	end

	function tracker.Accept(_self, player, questId)
		local state, def = states[player], cfg.quests[questId]
		if state == nil or def == nil then
			return false, "unknown quest"
		end
		if state.Active[questId] ~= nil then
			return false, "already active"
		end
		if state.Completed[questId] and def.repeatable ~= true then
			return false, "already completed"
		end
		for _, required in def.requires or {} do
			if not state.Completed[required] then
				return false, "requirement missing"
			end
		end
		local active = 0
		for _ in state.Active do
			active += 1
		end
		if active >= maxActive then
			return false, "too many active quests"
		end
		state.Active[questId] = table.create(#def.objectives, 0)
		return true, nil
	end

	function tracker.Abandon(_self, player, questId)
		local state = states[player]
		if state then
			state.Active[questId] = nil
		end
	end

	function tracker.Report(_self, player, kind, target, amount)
		local state = states[player]
		local step = amount or 1
		if state == nil or step < 1 or step % 1 ~= 0 then
			return
		end
		for id, progress in table.clone(state.Active) do
			local def = cfg.quests[id]
			local changed, done = false, true
			for i, objective in def.objectives do
				if objective.kind == kind and objective.target == target and progress[i] < objective.count then
					progress[i] = math.min(objective.count, progress[i] + step)
					changed = true
				end
				done = done and progress[i] >= objective.count
			end
			local onProgress = cfg.onProgress
			if changed and onProgress then
				onProgress(player, id, progress)
			end
			if done then
				state.Active[id] = nil -- removed first, so a re-entrant Report cannot complete it twice
				state.Completed[id] = true
				cfg.onComplete(player, id, def)
			end
		end
	end

	function tracker.Progress(_self, player, questId)
		local state = states[player]
		return if state then state.Active[questId] else nil
	end

	function tracker.IsCompleted(_self, player, questId)
		local state = states[player]
		return state ~= nil and state.Completed[questId] == true
	end

	return tracker
end

return Quests
