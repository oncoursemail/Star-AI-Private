---
id: gb-world-round-countdown-cancel
category: round-systems
topics: countdown, task.cancel, task.delay, round timer, early end
source: original
---
# Request
I start a round timer with `task.delay(120, endRound)`, but when someone wins early the delayed `endRound` still fires two minutes later and ends the next round in the middle. I also need a per-second countdown for the UI. How do I make a timer I can cancel?

# Answer
Run the countdown in one thread you keep a reference to, tick once per second, and call `task.cancel` on it when the round ends early. The timer object reports whether the cancel actually stopped something, so double endings are easy to detect.

```lua
--!strict
-- ModuleScript: ServerScriptService.Countdown
export type Countdown = {
	cancelTimer: () -> boolean,
	isRunning: () -> boolean,
}

local Countdown = {}

function Countdown.start(seconds: number, onTick: (remaining: number) -> (), onExpired: () -> ()): Countdown
	local running = true
	local thread = task.spawn(function()
		for remaining = seconds, 1, -1 do
			onTick(remaining)
			task.wait(1)
		end
		running = false
		onTick(0)
		onExpired()
	end)

	return {
		cancelTimer = function(): boolean
			if not running then
				return false
			end
			running = false
			task.cancel(thread)
			return true
		end,
		isRunning = function(): boolean
			return running
		end,
	}
end

return Countdown
```

Using it for a round, with the UI reading an attribute:

```lua
--!strict
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Countdown = require(script.Parent:WaitForChild("Countdown"))

local roundTimer: { cancelTimer: () -> boolean }? = nil

local function endRound(reason: string)
	if roundTimer then
		roundTimer.cancelTimer()
		roundTimer = nil
	end
	ReplicatedStorage:SetAttribute("RoundEndReason", reason)
end

local function startRound()
	roundTimer = Countdown.start(120, function(remaining)
		ReplicatedStorage:SetAttribute("TimeLeft", remaining)
	end, function()
		roundTimer = nil
		endRound("Time")
	end)
end

return { startRound = startRound, endRound = endRound }
```

- `task.cancel` stops the thread wherever it is waiting, so neither the remaining ticks nor `onExpired` run after an early win.
- A fire-and-forget `task.delay` cannot be told apart from the next round's timer; holding the handle in `roundTimer` ties each timer to its round.
- Ticking with `task.wait(1)` can drift by a frame per tick; for long timers compute `remaining` from `os.clock()` against an end time instead.

# Test
```lua
local ticks, expired = {}, 0
local timer = item.start(3, function(n)
	table.insert(ticks, n)
end, function()
	expired += 1
end)
check("first tick immediately", ticks[1] == 3 and timer.isRunning())
__advance(3.1)
check("counts down to zero then expires", ticks[#ticks] == 0 and #ticks == 4 and expired == 1)
check("finished timer cannot be cancelled", timer.cancelTimer() == false)

local ticks2, expired2 = 0, 0
local early = item.start(10, function()
	ticks2 += 1
end, function()
	expired2 += 1
end)
__advance(2.5)
check("cancel stops a running timer", early.cancelTimer() == true and not early.isRunning())
__advance(20)
check("no ticks or expiry after cancel", ticks2 == 3 and expired2 == 0)
check("second cancel reports nothing to stop", early.cancelTimer() == false)
```
