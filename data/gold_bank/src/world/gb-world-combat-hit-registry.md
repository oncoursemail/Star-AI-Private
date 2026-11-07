---
id: gb-world-combat-hit-registry
category: combat-hitbox
topics: debounce per target, multi-hit attack, target cap, swing registry, timing
source: original
---
# Request
I have two kinds of attacks: normal swings that should hit each enemy once, and a spinning attack that lasts 2 seconds and should hit each enemy every 0.3 seconds, up to 5 enemies total. Right now I use one global debounce and it's a mess. How should I track hits?

# Answer
Create a small registry per attack instance. With no interval it allows each target once; with an interval it allows the same target again after that many seconds; a target cap limits how many different targets one attack can ever affect. The hitbox code asks the registry before applying damage.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.HitRegistry
export type Registry = {
	tryRegister: (target: Instance) -> boolean,
	targetCount: () -> number,
}

local HitRegistry = {}

function HitRegistry.new(tickInterval: number?, maxTargets: number?): Registry
	local lastHit: { [Instance]: number } = {}
	local targets = 0

	return {
		tryRegister = function(target: Instance): boolean
			local now = os.clock()
			local previous = lastHit[target]
			if previous == nil then
				if maxTargets and targets >= maxTargets then
					return false
				end
				targets += 1
				lastHit[target] = now
				return true
			end
			if tickInterval and now - previous >= tickInterval then
				lastHit[target] = now
				return true
			end
			return false
		end,
		targetCount = function(): number
			return targets
		end,
	}
end

return HitRegistry
```

Used inside the spinning attack's hitbox loop:

```lua
--!strict
local HitRegistry = require(game:GetService("ReplicatedStorage"):WaitForChild("HitRegistry"))

local function spinAttack(queryTargets: () -> { Humanoid }, damage: number, duration: number)
	local registry = HitRegistry.new(0.3, 5)
	local endsAt = os.clock() + duration
	while os.clock() < endsAt do
		for _, humanoid in queryTargets() do
			if registry.tryRegister(humanoid) then
				humanoid:TakeDamage(damage)
			end
		end
		task.wait(0.05)
	end
end

return spinAttack
```

- One registry per swing replaces global debounces, so two players attacking the same enemy never block each other.
- The cap counts distinct targets, so the spin can keep ticking on its first five victims while a sixth walking in is ignored.
- Key on the Humanoid (or character Model), never on individual parts, otherwise each limb counts as a new target.

# Test
```lua
local a, b, c = Instance.new("Humanoid"), Instance.new("Humanoid"), Instance.new("Humanoid")
local single = item.new()
check("first hit allowed", single.tryRegister(a))
__advance(5)
check("single-hit attack never repeats a target", not single.tryRegister(a))
check("other targets still allowed", single.tryRegister(b))

local spin = item.new(0.3, 2)
check("spin hits a target", spin.tryRegister(a))
__advance(0.1)
check("too soon for the same target", not spin.tryRegister(a))
__advance(0.25)
check("ticks again after the interval", spin.tryRegister(a))
check("second target allowed", spin.tryRegister(b))
check("cap stops a third target", not spin.tryRegister(c) and spin.targetCount() == 2)
__advance(0.31)
check("capped targets keep ticking", spin.tryRegister(b))
```
