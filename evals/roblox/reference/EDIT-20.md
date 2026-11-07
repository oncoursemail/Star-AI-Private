Reference fix.

```lua
-- Flag: one team's flag in capture the flag. States: "home", "carried", "dropped".
local Flag = {}
Flag.__index = Flag

function Flag.new(team, returnTime)
	local self = setmetatable({}, Flag)
	self.team = team
	self.returnTime = returnTime or 30
	self.state = "home"
	self.carrier = nil
	self.droppedAt = nil
	self.dropPosition = nil
	return self
end

-- A player of `playerTeam` touches the flag at time `now`. Returns what happened, or nil.
function Flag:touch(player, playerTeam, now)
	if self.state == "carried" then
		return nil
	end
	if playerTeam == self.team then
		if self.state == "dropped" then
			self:returnHome()
			return "returned"
		end
		return nil
	end
	self.state = "carried"
	self.carrier = player
	return "taken"
end

-- The carrier was splatted at `position`.
function Flag:drop(position, now)
	if self.state ~= "carried" then
		return
	end
	self.state = "dropped"
	self.carrier = nil
	self.dropPosition = position
	self.droppedAt = now
end

-- Called every second by the round script.
function Flag:update(now)
	if self.state == "dropped" and self.droppedAt and now - self.droppedAt >= self.returnTime then
		self:returnHome()
	end
end

function Flag:returnHome()
	self.state = "home"
	self.carrier = nil
	self.droppedAt = nil
	self.dropPosition = nil
end

-- The carrier reached their own base.
function Flag:capture()
	if self.state ~= "carried" then
		return false
	end
	self:returnHome()
	return true
end

function Flag:isHome()
	return self.state == "home"
end

return Flag
```
