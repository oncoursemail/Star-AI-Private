---
id: gb-eng-tdd-quest-progress
category: engineering-test-first
topics: test-first, quest tracker, events, completion callback, idempotent
source: original
test_block: 2
---
# Request
Test-first request: a quest progress tracker. A quest has objectives like "kill 5 Wolf" or "collect 3 Herb". Game code reports events `record(kind, target, amount)`. Progress must not exceed the requirement, unrelated events are ignored, the completion callback fires exactly once even if more events arrive, and I need a snapshot I can save and later restore.

# Answer
The spec pins down capping, filtering, the exactly-once completion, and a save/restore round trip. The tracker keeps progress in a plain table keyed by objective index, which is what makes the snapshot trivially saveable.

```lua
--!strict
-- Script: ServerScriptService.Tests.QuestTrackerSpec
local QuestTracker = require(game:GetService("ServerScriptService").QuestTracker)

local failures = 0
local function test(name: string, fn: () -> ())
	local ok, err = pcall(fn)
	if not ok then
		failures += 1
		warn(`FAIL {name}: {err}`)
	end
end

local QUEST = { { kind = "kill", target = "Wolf", required = 5 }, { kind = "collect", target = "Herb", required = 3 } }

test("progress caps at the requirement", function()
	local t = QuestTracker.new(QUEST)
	t:record("kill", "Wolf", 9)
	assert(t:snapshot()[1] == 5)
end)
test("unrelated events are ignored", function()
	local t = QuestTracker.new(QUEST)
	t:record("kill", "Bear", 1)
	t:record("collect", "Wolf", 1)
	assert(t:snapshot()[1] == 0 and t:snapshot()[2] == 0)
end)
test("completion fires exactly once", function()
	local fired = 0
	local t = QuestTracker.new(QUEST, function() fired += 1 end)
	t:record("kill", "Wolf", 5)
	t:record("collect", "Herb", 3)
	t:record("collect", "Herb", 3)
	assert(fired == 1 and t:isComplete())
end)
test("snapshot round trip", function()
	local t = QuestTracker.new(QUEST)
	t:record("kill", "Wolf", 2)
	local restored = QuestTracker.new(QUEST, nil, t:snapshot())
	assert(restored:snapshot()[1] == 2)
end)

print(`QuestTracker spec: {failures} failure(s)`)
```

```lua
--!strict
-- ModuleScript: ServerScriptService.QuestTracker
export type Objective = { kind: string, target: string, required: number }
export type Tracker = {
	record: (self: Tracker, kind: string, target: string, amount: number) -> (),
	isComplete: (self: Tracker) -> boolean,
	snapshot: (self: Tracker) -> { number },
}

local QuestTracker = {}

function QuestTracker.new(objectives: { Objective }, onComplete: (() -> ())?, saved: { number }?): Tracker
	local progress: { number } = {}
	for i, objective in objectives do
		local value = saved and saved[i]
		progress[i] = if type(value) == "number" then math.clamp(math.floor(value), 0, objective.required) else 0
	end
	local completed = false
	local tracker = {} :: Tracker

	function tracker.isComplete(_self: Tracker): boolean
		for i, objective in objectives do
			if progress[i] < objective.required then
				return false
			end
		end
		return true
	end

	-- a restored, already-finished quest must not fire its reward again
	completed = tracker:isComplete()

	function tracker.record(self: Tracker, kind: string, target: string, amount: number): ()
		if completed or amount <= 0 then
			return
		end
		for i, objective in objectives do
			if objective.kind == kind and objective.target == target then
				progress[i] = math.min(objective.required, progress[i] + math.floor(amount))
			end
		end
		if self:isComplete() then
			completed = true
			if onComplete then
				task.spawn(onComplete)
			end
		end
	end

	function tracker.snapshot(_self: Tracker): { number }
		return table.clone(progress)
	end

	return tracker
end

return QuestTracker
```

- The `completed` flag, set before the callback runs, is what makes the reward exactly-once; checking `isComplete()` alone would pay out again on every later event.
- Restored progress is clamped to the current requirements, so lowering a quest's target in an update cannot leave a save stuck above 100%.
- `snapshot` returns a plain array of numbers, which a DataStore accepts as-is.

# Test
```lua
local QUEST = { { kind = "kill", target = "Wolf", required = 5 }, { kind = "collect", target = "Herb", required = 3 } }
local t = item.new(QUEST)
t:record("kill", "Wolf", 9)
check("caps", t:snapshot()[1] == 5)
t:record("kill", "Bear", 1)
t:record("collect", "Wolf", 1)
check("ignores unrelated", t:snapshot()[2] == 0)
local fired = 0
local t2 = item.new(QUEST, function() fired += 1 end)
t2:record("kill", "Wolf", 5)
check("not complete with one objective", fired == 0 and not t2:isComplete())
t2:record("collect", "Herb", 3)
t2:record("collect", "Herb", 3)
check("fires once", fired == 1 and t2:isComplete())
local restored = item.new(QUEST, function() fired += 1 end, t2:snapshot())
restored:record("kill", "Wolf", 1)
check("restored complete quest does not refire", fired == 1 and restored:isComplete())
local partial = item.new(QUEST, nil, { 2, 99 })
check("restore clamps", partial:snapshot()[1] == 2 and partial:snapshot()[2] == 3)
check("snapshot is a copy", (function()
	local s = partial:snapshot()
	s[1] = 100
	return partial:snapshot()[1] == 2
end)())
```
