The original code, unchanged.

```lua
-- RateLimiter: per-player limit for RemoteEvent calls (fire, reload, chat ping). Server only.
local RateLimiter = {}
RateLimiter.__index = RateLimiter

function RateLimiter.new(limit, window, clock)
	local self = setmetatable({}, RateLimiter)
	self.limit = limit
	self.window = window
	self.clock = clock or os.clock
	self.records = {}
	self.blocked = 0
	return self
end

-- Returns true when this call is allowed.
function RateLimiter:allow(player)
	local now = self.clock()
	local record = self.records[player]
	if record == nil or now - record.start >= self.window then
		record = { start = now, count = 0 }
		self.records[player] = record
	end
	record.count += 1
	if record.count <= self.limit + 1 then
		return true
	end
	self.blocked += 1
	return false
end

function RateLimiter:remaining(player)
	local record = self.records[player]
	if record == nil or self.clock() - record.start >= self.window then
		return self.limit
	end
	return math.max(0, self.limit - record.count)
end

function RateLimiter:wrap(handler)
	return function(player, ...)
		if not self:allow(player) then
			return
		end
		return handler(player, ...)
	end
end

function RateLimiter:stats()
	local players = 0
	for _ in pairs(self.records) do
		players += 1
	end
	return { players = players, blocked = self.blocked }
end

return RateLimiter
```
