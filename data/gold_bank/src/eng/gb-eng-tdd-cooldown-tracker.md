---
id: gb-eng-tdd-cooldown-tracker
category: engineering-test-first
topics: test-first, cooldowns, injected clock, abilities, pure module
source: original
test_block: 2
---
# Request
Test-first please: a cooldown tracker for abilities, keyed by ability name, one tracker per player. `tryUse(name)` succeeds when off cooldown and starts it; `remaining(name)` returns seconds left (0 if ready); `reduceAll(seconds)` shortens every active cooldown (for a "cooldown reduction" pickup). It must be testable without waiting in real time.

# Answer
Make time an input: the tracker takes a clock function, so the spec drives a fake clock instead of waiting. The tests cover first use, reuse during the cooldown, exact expiry, reduction and independence between abilities.

```lua
--!strict
-- Script: ServerScriptService.Tests.CooldownSpec
local Cooldowns = require(game:GetService("ReplicatedStorage").Cooldowns)

local failures = 0
local function test(name: string, fn: () -> ())
	local ok, err = pcall(fn)
	if not ok then
		failures += 1
		warn(`FAIL {name}: {err}`)
	end
end

local now = 0
local function clock(): number
	return now
end

test("first use succeeds and starts the cooldown", function()
	now = 0
	local cd = Cooldowns.new({ Dash = 3 }, clock)
	assert(cd:tryUse("Dash"))
	assert(not cd:tryUse("Dash"))
	assert(cd:remaining("Dash") == 3)
end)
test("ready exactly when the duration has passed", function()
	now = 0
	local cd = Cooldowns.new({ Dash = 3 }, clock)
	cd:tryUse("Dash")
	now = 2.999
	assert(not cd:tryUse("Dash"))
	now = 3
	assert(cd:remaining("Dash") == 0 and cd:tryUse("Dash"))
end)
test("reduceAll shortens active cooldowns only", function()
	now = 0
	local cd = Cooldowns.new({ Dash = 3, Blast = 10 }, clock)
	cd:tryUse("Blast")
	cd:reduceAll(4)
	assert(cd:remaining("Blast") == 6 and cd:remaining("Dash") == 0)
end)
test("unknown abilities are refused", function()
	local cd = Cooldowns.new({ Dash = 3 }, clock)
	assert(not cd:tryUse("Teleport"))
end)

print(`Cooldown spec: {failures} failure(s)`)
```

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Cooldowns
export type Tracker = {
	tryUse: (self: Tracker, name: string) -> boolean,
	remaining: (self: Tracker, name: string) -> number,
	reduceAll: (self: Tracker, seconds: number) -> (),
}

local Cooldowns = {}

function Cooldowns.new(durations: { [string]: number }, clock: (() -> number)?): Tracker
	local now = clock or os.clock
	local readyAt: { [string]: number } = {}
	local tracker = {} :: Tracker

	function tracker.remaining(_self: Tracker, name: string): number
		local at = readyAt[name]
		return if at then math.max(0, at - now()) else 0
	end

	function tracker.tryUse(self: Tracker, name: string): boolean
		local duration = durations[name]
		if duration == nil or self:remaining(name) > 0 then
			return false
		end
		readyAt[name] = now() + duration
		return true
	end

	function tracker.reduceAll(_self: Tracker, seconds: number): ()
		for name, at in readyAt do
			readyAt[name] = at - math.max(0, seconds)
		end
	end

	return tracker
end

return Cooldowns
```

- The default clock is `os.clock`, so game code just calls `Cooldowns.new(ABILITY_COOLDOWNS)`; only the spec passes a fake clock.
- Refusing unknown names means a client asking for `"Teleport"` through a remote cannot use an ability the server never defined.
- `reduceAll` only moves existing deadlines, so abilities that were already ready stay ready instead of going negative in a way that matters.

# Test
```lua
local now = 0
local clock = function()
	return now
end
local cd = item.new({ Dash = 3, Blast = 10 }, clock)
check("first use then blocked", cd:tryUse("Dash") and not cd:tryUse("Dash") and cd:remaining("Dash") == 3)
now = 2.999
check("still cooling", not cd:tryUse("Dash"))
now = 3
check("ready exactly at expiry", cd:remaining("Dash") == 0 and cd:tryUse("Dash"))
cd:tryUse("Blast")
cd:reduceAll(4)
check("reduceAll shortens active", cd:remaining("Blast") == 6)
check("unknown refused", not cd:tryUse("Teleport"))
local real = item.new({ Dash = 1 })
check("default clock uses virtual time", real:tryUse("Dash") and not real:tryUse("Dash"))
__advance(1.01)
check("default clock expires", real:tryUse("Dash"))
```
