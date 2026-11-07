Reference fix.

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
	self.best = {}
	return self
end

function Streaks:streakOf(player)
	return self.current[player] or 0
end

-- The reward the streak earns at this kill count, or nil.
function Streaks:rewardFor(streak)
	return REWARDS[streak]
end

function Streaks:bestOf(player)
	return self.best[player] or 0
end

-- Call when `player` gets a kill. Returns the reward to give now, or nil.
function Streaks:kill(player)
	local streak = self:streakOf(player) + 1
	self.current[player] = streak
	self.best[player] = math.max(self.best[player] or 0, streak)
	local reward = self:rewardFor(streak)
	if reward then
		self.given[player] = (self.given[player] or 0) + 1
	end
	return reward
end

function Streaks:death(player)
	self.current[player] = 0
end

function Streaks:rewardsGiven(player)
	return self.given[player] or 0
end

function Streaks:remove(player)
	self.current[player] = nil
	self.given[player] = nil
	self.best[player] = nil
end

return Streaks
```
