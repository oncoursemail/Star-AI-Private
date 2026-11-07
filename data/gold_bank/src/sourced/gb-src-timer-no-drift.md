---
id: gb-src-timer-no-drift
category: engineering-algorithm
topics: timer, Heartbeat, drift, interval, catch-up ticks, passive income
source: adapted
source_id: rbxutil
source_path: modules/timer/init.luau
source_commit: 31f9120fca021e3dec275b42bc7047d626962082
---
# Request
I give players passive income every 1 second with `while true do task.wait(1) payAll() end`, but over an hour players get noticeably fewer payouts than 3600. Why, and what's a better timer?

# Answer
`task.wait(1)` resumes on the first frame after at least one second, so each loop is a bit longer than 1 s and the error adds up. Schedule ticks against a fixed start time instead: tick n is due at `start + n * interval`, and if a frame is late you fire every tick that is due.

```lua
--!strict
local RunService = game:GetService("RunService")

local Timer = {}

function Timer.ticksDue(start: number, interval: number, ticksFired: number, now: number): number
	local total = math.floor((now - start) / interval)
	return math.max(0, total - ticksFired)
end

function Timer.every(interval: number, callback: (tickNumber: number) -> ()): RBXScriptConnection
	assert(interval > 0, "interval must be positive")
	local start = os.clock()
	local fired = 0
	return RunService.Heartbeat:Connect(function()
		for _ = 1, Timer.ticksDue(start, interval, fired, os.clock()) do
			fired += 1
			callback(fired)
		end
	end)
end

return Timer
```

Usage: `local incomeTimer = Timer.every(1, payAll)`; stop it with `incomeTimer:Disconnect()`.

- The due-time is computed from the start, so a late frame shifts nothing: the next tick is still due at its exact time.
- After a long hitch every missed tick fires, so players never lose income to lag.
- `Heartbeat` runs once per frame, which is plenty for second-scale timers and costs one subtraction per frame.

# Test
```lua
check("no ticks before the first interval", item.ticksDue(0, 1, 0, 0.99) == 0)
check("catch-up after a hitch", item.ticksDue(0, 1, 2, 5.2) == 3)
check("already fired ticks not repeated", item.ticksDue(0, 1, 5, 5.9) == 0)
local count = 0
local conn = item.every(1, function()
	count += 1
end)
__frames(600, 1 / 60 + 0.0005)
check("about 10 ticks over 10.3 s without drift loss", count == 10)
conn:Disconnect()
__frames(120, 1 / 60)
check("stops after disconnect", count == 10)
```
