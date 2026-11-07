---
id: gb-eng-perf-microprofiler-labels
category: performance
topics: MicroProfiler, debug.profilebegin, profileend, instrumentation, frame budget
source: original
---
# Request
The MicroProfiler shows a big "Heartbeat" bar on my server but I can't tell which of my systems is slow, since they all run from one Heartbeat loop. How do I label my own code in the profiler, and how do I make sure a label is always closed even if a system errors?

# Answer
Wrap each system's update in `debug.profilebegin(label)` / `debug.profileend()`; the label then appears as its own bar inside Heartbeat. A small runner calls each system in `pcall` so `profileend` always runs, and also keeps a rolling average per system that you can print without opening the profiler.

```lua
--!strict
-- ModuleScript: ServerScriptService.SystemRunner
export type System = { name: string, update: (dt: number) -> () }
export type Runner = { systems: { System }, avgMs: { [string]: number }, errors: { [string]: number } }

local SMOOTHING = 0.05

local SystemRunner = {}

function SystemRunner.new(systems: { System }): Runner
	return { systems = systems, avgMs = {}, errors = {} }
end

function SystemRunner.step(runner: Runner, dt: number): ()
	for _, system in runner.systems do
		local started = os.clock()
		debug.profilebegin(system.name)
		local ok, err = pcall(system.update, dt)
		debug.profileend() -- always paired with profilebegin, even when update errored
		local ms = (os.clock() - started) * 1000
		local previous = runner.avgMs[system.name]
		runner.avgMs[system.name] = if previous then previous + (ms - previous) * SMOOTHING else ms
		if not ok then
			runner.errors[system.name] = (runner.errors[system.name] or 0) + 1
			warn(`[{system.name}] {err}`)
		end
	end
end

function SystemRunner.report(runner: Runner): string
	local lines: { string } = {}
	for _, system in runner.systems do
		local avg = runner.avgMs[system.name] or 0
		table.insert(lines, string.format("%-12s %6.3f ms  errors %d", system.name, avg, runner.errors[system.name] or 0))
	end
	return table.concat(lines, "\n")
end

return SystemRunner
```

- Wiring: `local runner = SystemRunner.new({ { name = "AI", update = AI.update }, { name = "Loot", update = Loot.update } })` and `RunService.Heartbeat:Connect(function(dt) SystemRunner.step(runner, dt) end)`; each name then appears nested under Heartbeat. Ctrl+F6 opens the client MicroProfiler; for this server loop, record from the MicroProfiler tab of the Developer Console in server mode.
- An unpaired `profilebegin` corrupts the profiler's nesting for the rest of the frame, which is why the update runs in `pcall` and `profileend` comes right after it.
- Labels should be constant strings; building them per call (`"AI " .. npc.Name`) allocates every frame and floods the profiler with unique bars.

# Test
```lua
labels = {}
depth = 0
debug = setmetatable({
	profilebegin = function(name)
		depth += 1
		table.insert(labels, name)
	end,
	profileend = function()
		depth -= 1
	end,
}, { __index = debug })
```
```lua
local calls = 0
local runner = item.new({
	{ name = "Fast", update = function() calls += 1 end },
	{ name = "Broken", update = function() error("bad state", 0) end },
	{ name = "Slow", update = function() calls += 1 end },
})
item.step(runner, 1 / 60)
item.step(runner, 1 / 60)
check("every system ran despite the error", calls == 4)
check("labels balanced after an error", depth == 0)
check("labels use system names", labels[1] == "Fast" and labels[2] == "Broken" and labels[3] == "Slow")
check("errors counted", runner.errors.Broken == 2 and runner.errors.Fast == nil)
check("report lists systems", string.find(item.report(runner), "Broken", 1, true) ~= nil)
```
