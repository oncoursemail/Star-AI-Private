--!strict
-- What a request is allowed to change. TycoonServer calls these after its type checks.
local Rules = {}

function Rules.validStageClear(data, stage: number, stageCount: number): boolean
	return stage == data.stage + 1 and stage <= stageCount
end

function Rules.applyUpgrade(data, item)
	data.owned[item.id] = true
	data.multiplier *= item.multiplier
end

function Rules.applyRebirth(data)
	data.rebirths += 1
	data.cash = 0
	data.owned = {}
	data.multiplier = 1
end

return Rules
