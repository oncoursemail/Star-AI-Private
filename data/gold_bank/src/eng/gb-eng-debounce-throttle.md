---
id: gb-eng-debounce-throttle
category: engineering-algorithm
topics: debounce, throttle, task.delay, search box, rate limiting UI
source: original
---
# Request
Two related problems on the client: my search box filters a 2000-item catalog on every keystroke (laggy), and my "save settings" fires on every slider move. I think I need debounce for one and throttle for the other. What's the difference, and can you write both as reusable helpers?

# Answer
Debounce waits until calls stop for `delay` seconds and then runs once with the last arguments (search box). Throttle runs at most once per `interval`, immediately on the first call and then once more with the latest arguments at the end of the window (slider saves). Both are built on `task.delay` and `task.cancel`.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.RateHelpers
local RateHelpers = {}

function RateHelpers.debounce(delay: number, fn: (...any) -> ()): (...any) -> ()
	local pending: thread? = nil
	return function(...: any)
		if pending then
			task.cancel(pending)
		end
		local args = table.pack(...)
		pending = task.delay(delay, function()
			pending = nil
			fn(table.unpack(args, 1, args.n))
		end)
	end
end

function RateHelpers.throttle(interval: number, fn: (...any) -> ()): (...any) -> ()
	local lastRun = -math.huge
	local trailing: { n: number, [number]: any }? = nil
	local scheduled = false
	local function run(...: any)
		lastRun = os.clock()
		fn(...)
	end
	return function(...: any)
		local now = os.clock()
		if now - lastRun >= interval and not scheduled then
			run(...)
			return
		end
		trailing = table.pack(...)
		if scheduled then
			return
		end
		scheduled = true
		task.delay(math.max(0, lastRun + interval - now), function()
			scheduled = false
			local args = trailing
			trailing = nil
			if args then
				run(table.unpack(args, 1, args.n))
			end
		end)
	end
end

return RateHelpers
```

- Search: `box:GetPropertyChangedSignal("Text"):Connect(RateHelpers.debounce(0.25, function() refilter(box.Text) end))` filters once the player pauses typing.
- Settings: `RateHelpers.throttle(1, sendSettings)` sends at most once per second and always sends the final value, so the last slider position is never lost.
- These limit client work and traffic; the server still needs its own rate limit on the remote, because an exploiter can bypass any client-side throttle.

# Test
```lua
local searches = {}
local search = item.debounce(0.25, function(text)
	table.insert(searches, text)
end)
search("s")
__advance(0.1)
search("sw")
__advance(0.1)
search("swo")
check("nothing before quiet period", #searches == 0)
__advance(0.3)
check("debounce runs once with last args", #searches == 1 and searches[1] == "swo")

local saves = {}
local save = item.throttle(1, function(v)
	table.insert(saves, v)
end)
save(1)
check("throttle runs first call immediately", #saves == 1 and saves[1] == 1)
__advance(0.2)
save(2)
__advance(0.2)
save(3)
check("calls inside window wait", #saves == 1)
__advance(0.7)
check("trailing call uses latest value", #saves == 2 and saves[2] == 3)
__advance(2)
save(4)
check("next window runs immediately again", #saves == 3 and saves[3] == 4)
```
