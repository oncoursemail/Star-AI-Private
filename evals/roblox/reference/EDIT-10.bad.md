The original code, unchanged.

```lua
-- KillFeed: the top-right "X splatted Y" list. Newest entry first.
local KillFeed = {}
KillFeed.__index = KillFeed

function KillFeed.new(maxEntries, lifetime)
	local self = setmetatable({}, KillFeed)
	self.maxEntries = maxEntries or 5
	self.lifetime = lifetime or 6
	self.entries = {}
	return self
end

function KillFeed:push(killer, victim, weapon, now)
	table.insert(self.entries, 1, {
		killer = killer,
		victim = victim,
		weapon = weapon,
		time = now,
	})
end

-- Entries still on screen at time `now`, newest first.
function KillFeed:visible(now)
	local out = {}
	for _, entry in ipairs(self.entries) do
		if now - entry.time < self.lifetime then
			table.insert(out, entry)
		end
	end
	return out
end

function KillFeed:format(entry)
	if entry.weapon == "paintball" then
		return entry.killer .. " splatted " .. entry.victim
	end
	return entry.killer .. " eliminated " .. entry.victim .. " (" .. entry.weapon .. ")"
end

function KillFeed:lines(now)
	local lines = {}
	for _, entry in ipairs(self:visible(now)) do
		table.insert(lines, self:format(entry))
	end
	return lines
end

function KillFeed:clear()
	table.clear(self.entries)
end

function KillFeed:count()
	return #self.entries
end

return KillFeed
```
