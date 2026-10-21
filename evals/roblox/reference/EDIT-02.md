Reference fix.

```lua
-- TeamScore: points per team for one paintball round, with a change callback for the HUD.
local TeamScore = {}
TeamScore.__index = TeamScore

function TeamScore.new(teamNames, winScore)
	local self = setmetatable({}, TeamScore)
	self.scores = {}
	self.winScore = winScore or 50
	self.winner = nil
	self.listeners = {}
	for _, name in ipairs(teamNames) do
		self.scores[name] = 0
	end
	return self
end

function TeamScore:onChanged(fn)
	table.insert(self.listeners, fn)
end

function TeamScore:_emit(team)
	for _, fn in ipairs(self.listeners) do
		fn(team, self.scores[team])
	end
end

function TeamScore:addPoints(team, amount)
	if self.scores[team] == nil or self.winner ~= nil then
		return
	end
	self.scores[team] = self.scores[team] + amount
	if self.scores[team] >= self.winScore then
		self.winner = team
	end
	self:_emit(team)
end

function TeamScore:reset()
	for team in pairs(self.scores) do
		self.scores[team] = 0
		self:_emit(team)
	end
	self.winner = nil
end

function TeamScore:get(team)
	return self.scores[team]
end

function TeamScore:leader()
	local best, bestScore = nil, -1
	for team, score in pairs(self.scores) do
		if score > bestScore then
			best, bestScore = team, score
		end
	end
	return best
end

function TeamScore:standings()
	local list = {}
	for team, score in pairs(self.scores) do
		table.insert(list, { team = team, score = score })
	end
	table.sort(list, function(a, b)
		if a.score == b.score then
			return a.team < b.team
		end
		return a.score > b.score
	end)
	return list
end

return TeamScore
```
