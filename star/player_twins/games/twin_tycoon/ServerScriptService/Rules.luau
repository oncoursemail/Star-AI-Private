--!strict
-- What a request is allowed to change. TycoonServer calls these after its type checks.
local Rules = {}

-- PLANTED FLAW 2 (exploitable remote): any stage above the current one is accepted, so a client
-- can fire ClearStage(50) and skip the obby, collecting 50 * STAGE_REWARD at once.
function Rules.validStageClear(data, stage: number, _stageCount: number): boolean
	return stage > data.stage
end

-- PLANTED FLAW 3 (inflation bug): the upgrade is applied but never marked owned, so the shop keeps
-- offering it and every purchase multiplies income again.
function Rules.applyUpgrade(data, item)
	data.multiplier *= item.multiplier
end

function Rules.applyRebirth(data)
	data.rebirths += 1
	data.cash = 0
	data.owned = {}
	data.multiplier = 1
end

return Rules
