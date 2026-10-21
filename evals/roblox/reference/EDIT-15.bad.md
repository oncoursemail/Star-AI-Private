The original code, unchanged.

```lua
-- Streaks: kill streak rewards for paintball (3 = radar ping, 5 = paint grenade, 10 = airstrike).
local Streaks = {}
Streaks.__index = Streaks

local REWARDS = {
	[3] = "RadarPing",
	[5] = "PaintGrenade",
	[10] = "Airstrike",
}

function Streaks.new()
	local self = setmetatable({}, Streaks)
	self.current = {}
	self.given = {}
	return self
end

function Streaks:streakOf(player)
	return self.current[player] or 0
end

-- The reward the streak earns at this kill count, or nil.
function Streaks:rewardFor(streak)
	local best = nil
	for count, reward in pairs(REWARDS) do
		if streak >= count and (best == nil or count > best.count) then
			best = { count = count, reward = reward }
		end
	end
	return best and best.reward
end

-- Call when `player` gets a kill. Returns the reward to give now, or nil.
function Streaks:kill(player)
	local streak = self:streakOf(player) + 1
	self.current[player] = streak
	local reward = self:rewardFor(streak)
	if reward then
		self.given[player] = (self.given[player] or 0) + 1
	end
	return reward
end

function Streaks:death(player)
	self.given[player] = 0
end

function Streaks:rewardsGiven(player)
	return self.given[player] or 0
end

function Streaks:remove(player)
	self.current[player] = nil
	self.given[player] = nil
end

return Streaks
```
