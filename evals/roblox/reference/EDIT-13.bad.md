The original code, unchanged.

```lua
-- TeamBalancer: picks a team for players who join mid-match.
-- teams = { { name = "Red", players = { ... }, score = 0 }, ... }; players are in join order.
local TeamBalancer = {}

local function sizeOf(team)
	return #team.players
end

function TeamBalancer.smallest(teams)
	local target = teams[1]
	for _, team in ipairs(teams) do
		if sizeOf(team) <= sizeOf(target) then
			target = team
		end
	end
	return target
end

function TeamBalancer.assign(teams, player)
	local team = TeamBalancer.smallest(teams)
	table.insert(team.players, player)
	return team
end

function TeamBalancer.remove(teams, player)
	for _, team in ipairs(teams) do
		local index = table.find(team.players, player)
		if index then
			table.remove(team.players, index)
			return team
		end
	end
	return nil
end

function TeamBalancer.teamOf(teams, player)
	for _, team in ipairs(teams) do
		if table.find(team.players, player) then
			return team
		end
	end
	return nil
end

function TeamBalancer.sizes(teams)
	local out = {}
	for _, team in ipairs(teams) do
		out[team.name] = sizeOf(team)
	end
	return out
end

return TeamBalancer
```
