Reference fix.

```lua
-- RoundTimer: counts a paintball round down. The server calls step(dt) from RunService.Heartbeat.
local RoundTimer = {}
RoundTimer.__index = RoundTimer

function RoundTimer.new(duration)
	return setmetatable({
		duration = duration,
		remaining = duration,
		running = false,
		finishedHandlers = {},
		secondHandlers = {},
		lastWhole = math.ceil(duration),
	}, RoundTimer)
end

function RoundTimer:start()
	self.running = true
end

function RoundTimer:pause()
	self.running = false
end

function RoundTimer:isRunning()
	return self.running
end

function RoundTimer:onFinished(fn)
	table.insert(self.finishedHandlers, fn)
end

function RoundTimer:onSecond(fn)
	table.insert(self.secondHandlers, fn)
end

function RoundTimer:addTime(seconds)
	self.remaining += seconds
end

function RoundTimer:reset()
	self.remaining = self.duration
	self.lastWhole = math.ceil(self.duration)
	self.running = false
end

function RoundTimer:step(dt)
	if not self.running then
		return
	end
	self.remaining = math.max(0, self.remaining - dt)
	local whole = math.ceil(self.remaining)
	if whole ~= self.lastWhole then
		self.lastWhole = whole
		for _, fn in ipairs(self.secondHandlers) do
			fn(whole)
		end
	end
	if self.remaining <= 0 then
		self.running = false
		for _, fn in ipairs(self.finishedHandlers) do
			fn()
		end
	end
end

function RoundTimer:format()
	local seconds = math.ceil(self.remaining)
	return string.format("%d:%02d", seconds // 60, seconds % 60)
end

return RoundTimer
```
