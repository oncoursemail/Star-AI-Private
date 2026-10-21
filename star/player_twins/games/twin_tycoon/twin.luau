-- Player Twins adapter for Twin Tycoon: what a player can see and do, through the same remotes the
-- real client uses. It never touches server state directly.
return function(client)
	local A = {}
	A.currency = "Cash"
	-- Main progression line, in order; the report uses it for quit points and walls. The conveyor
	-- upgrade is optional, so it is not on the line.
	A.mainline = { "dropper1", "dropper2", "dropper3", "dropper4", "dropper5", "rebirth" }

	function A.observe()
		local okShop, shop = client:Invoke("Remotes.GetShop")
		local okStages, stages = client:Invoke("Remotes.GetStages")
		return {
			cash = client:Stat("Cash") or 0,
			stage = client:Stat("Stage") or 0,
			rebirths = client:Stat("Rebirths") or 0,
			shop = (okShop and type(shop) == "table") and shop or { items = {}, income = 0 },
			stages = (okStages and type(stages) == "table") and stages or {},
		}
	end

	function A.milestones(obs)
		local reached = {}
		for _, item in obs.shop.items or {} do
			if item.owned then
				table.insert(reached, item.id)
			end
		end
		if obs.rebirths > 0 then
			table.insert(reached, "rebirth")
		end
		if obs.stage >= 5 then
			table.insert(reached, "stage5")
		end
		if obs.stage >= 10 then
			table.insert(reached, "stage10")
		end
		return reached
	end

	-- kinds: earn (repeatable click), purchase (cost, value = income gained per second),
	-- challenge (difficulty, duration; run() is called only when the attempt succeeds), prestige (cost).
	function A.actions(obs)
		local list = {
			{ id = "work", kind = "earn", ui = { w = 160, d = 260 }, run = function()
				client:Fire("Remotes.Work")
			end },
		}
		local income = obs.shop.income or 0
		for _, item in obs.shop.items or {} do
			if item.available and not item.owned then
				local value = item.income or (income * ((item.multiplier or 1) - 1))
				table.insert(list, { id = "buy:" .. item.id, kind = "purchase", cost = item.price, value = value,
					ui = { w = 110, d = 420 }, run = function()
						client:Fire("Remotes.Buy", item.id)
					end })
			end
		end
		local nextStage = obs.stages[obs.stage + 1]
		if nextStage then
			table.insert(list, { id = "stage:" .. nextStage.stage, kind = "challenge", difficulty = nextStage.difficulty,
				duration = 8 + 2 * nextStage.stage, ui = { w = 200, d = 300 }, run = function()
					client:Fire("Remotes.ClearStage", nextStage.stage)
				end })
		end
		if obs.shop.rebirth and obs.shop.rebirth.unlocked then
			table.insert(list, { id = "rebirth", kind = "prestige", cost = obs.shop.rebirth.cost, ui = { w = 140, d = 380 }, run = function()
				client:Fire("Remotes.Rebirth")
			end })
		end
		return list
	end

	return A
end
