---
id: gb-eng-tagged-union-damage
category: luau-typing
topics: union types, type refinement, tagged union, singleton types, damage
source: original
---
# Request
My damage function takes a table that is sometimes a melee hit, sometimes a projectile with a travel distance, and sometimes fall damage with a height. Right now it is typed `{[string]: any}` and I keep misspelling fields. How do I type this so strict mode knows which fields exist in each case?

# Answer
Use a tagged union: every variant has a `kind` field with a string singleton type, and checking `kind` refines the table to that variant inside the branch.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.DamageRules
export type MeleeHit = { kind: "melee", base: number, critical: boolean }
export type ProjectileHit = { kind: "projectile", base: number, distance: number }
export type FallHit = { kind: "fall", height: number }
export type DamageEvent = MeleeHit | ProjectileHit | FallHit

local SAFE_FALL_HEIGHT = 12
local FALL_DAMAGE_PER_STUD = 2.5
local FALLOFF_START = 50
local FALLOFF_END = 150

local DamageRules = {}

function DamageRules.compute(event: DamageEvent): number
	if event.kind == "melee" then
		return if event.critical then event.base * 2 else event.base
	elseif event.kind == "projectile" then
		-- full damage up close, linear falloff to half damage at long range
		local t = math.clamp((event.distance - FALLOFF_START) / (FALLOFF_END - FALLOFF_START), 0, 1)
		return event.base * (1 - 0.5 * t)
	else
		local excess = event.height - SAFE_FALL_HEIGHT
		return if excess > 0 then excess * FALL_DAMAGE_PER_STUD else 0
	end
end

return DamageRules
```

- Inside `if event.kind == "melee"` the analyzer knows `event` is `MeleeHit`, so `event.distance` there is an error instead of a silent nil.
- The final `else` is refined to `FallHit` because the other two variants are already excluded; adding a fourth variant without handling it makes `event.height` fail to type-check, which points you at the missing branch.
- Building an event: `DamageRules.compute({ kind = "projectile", base = 30, distance = 120 })`; a typo such as `kind = "projectil"` is rejected at edit time.

# Test
```lua
check("melee normal", item.compute({ kind = "melee", base = 10, critical = false }) == 10)
check("melee critical doubles", item.compute({ kind = "melee", base = 10, critical = true }) == 20)
check("projectile close is full", item.compute({ kind = "projectile", base = 40, distance = 10 }) == 40)
check("projectile mid falloff", item.compute({ kind = "projectile", base = 40, distance = 100 }) == 30)
check("projectile far floors at half", item.compute({ kind = "projectile", base = 40, distance = 999 }) == 20)
check("short fall is free", item.compute({ kind = "fall", height = 8 }) == 0)
check("long fall hurts", item.compute({ kind = "fall", height = 22 }) == 25)
```
