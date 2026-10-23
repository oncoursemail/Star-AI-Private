---
id: gb-ui-round-timer-label
category: ui-text
topics: countdown, time format, m:ss, Heartbeat, label update
source: original
---
# Request
My round timer label shows things like "1:5" instead of "1:05", jumps from 60 to "1:0", and I update it with `task.wait(1)` which drifts behind the real round end. Can you write a correct timer label?

# Answer
Format with zero padding (`%d:%02d`, and hours when needed) and compute the remaining time from a fixed end time each frame instead of counting down with waits, so it cannot drift. Round up, so the label reads 0:01 until the round truly ends, and only write Text when the shown string changes.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.TimerLabel
local RunService = game:GetService("RunService")

local TimerLabel = {}

function TimerLabel.format(seconds: number): string
	local total = math.max(0, math.ceil(seconds))
	local h = total // 3600
	local m = (total % 3600) // 60
	local s = total % 60
	if h > 0 then
		return string.format("%d:%02d:%02d", h, m, s)
	end
	return string.format("%d:%02d", m, s)
end

-- `now` defaults to os.clock; pass `function() return workspace:GetServerTimeNow() end` when the end time comes from the server.
function TimerLabel.run(label: TextLabel, endsAt: number, now: (() -> number)?, onDone: (() -> ())?): RBXScriptConnection
	local clock = now or os.clock
	local connection: RBXScriptConnection
	local function update()
		local left = endsAt - clock()
		local text = TimerLabel.format(left)
		if label.Text ~= text then
			label.Text = text
		end
		if left <= 0 then
			connection:Disconnect()
			if onDone then
				onDone()
			end
		end
	end
	connection = RunService.Heartbeat:Connect(update)
	update()
	return connection
end

return TimerLabel
```

- Using the server's end time with `workspace:GetServerTimeNow()` keeps every client's timer in sync even if some joined late.
- `//` is integer division, so no `math.floor` noise is needed in the formatter.
- The text changes once a second, so the per-frame work is one small `string.format` and a comparison.

# Test
```lua
check("pads seconds", item.format(65) == "1:05")
check("a minute exactly", item.format(60) == "1:00")
check("rounds up partial seconds", item.format(0.2) == "0:01")
check("hours shown when needed", item.format(3725) == "1:02:05")
check("negative clamps", item.format(-3) == "0:00")
local label = Instance.new("TextLabel")
local done = 0
item.run(label, os.clock() + 3, nil, function()
	done += 1
end)
check("starts at the full time", label.Text == "0:03")
__frames(90, 1 / 60)
check("follows the clock", label.Text == "0:02" or label.Text == "0:01")
__frames(120, 1 / 60)
check("ends once at zero", label.Text == "0:00" and done == 1)
```
