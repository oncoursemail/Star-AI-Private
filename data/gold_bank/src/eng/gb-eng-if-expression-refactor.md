---
id: gb-eng-if-expression-refactor
category: luau-syntax
topics: if-expression, ternary, and-or pitfall, refactor, luau syntax
source: original
---
# Request
I use `cond and a or b` everywhere as a ternary, and today it broke: `local show = isAdmin and false or true` always gives true. Can you explain why and rewrite this helper with proper Luau syntax?

```lua
local function badgeFor(rank, isVip)
	local color = isVip and nil or Color3.new(1, 1, 1)
	local label = rank >= 100 and "Legend" or rank >= 50 and "Veteran" or rank >= 10 and "Regular" or "Newbie"
	local showCrown = isVip and false or true
	return label, color, showCrown
end
```

# Answer
`a and b or c` returns `c` whenever `b` is falsy, so it breaks exactly when the "true" value is `nil` or `false`. Luau's `if cond then x else y` expression evaluates only the chosen branch and returns `x` even when it is falsy.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Badge
local Badge = {}

function Badge.badgeFor(rank: number, isVip: boolean): (string, Color3?, boolean)
	local color: Color3? = if isVip then nil else Color3.new(1, 1, 1)
	local label = if rank >= 100 then "Legend"
		elseif rank >= 50 then "Veteran"
		elseif rank >= 10 then "Regular"
		else "Newbie"
	local showCrown = not isVip
	return label, color, showCrown
end

return Badge
```

- In the original, `isVip and nil or white` is white for VIPs too, and `isVip and false or true` is always `true`; both had the falsy-middle problem.
- `elseif` chains inside an if-expression read top to bottom like a statement and need a final `else`, so there is no missing case.
- `if isVip then false else true` would also be correct, but a boolean flip is simply `not isVip`.

# Test
```lua
local label, color, crown = item.badgeFor(120, true)
check("vip gets nil color", color == nil)
check("vip hides crown flag", crown == false)
check("legend label", label == "Legend")
local l2, c2, crown2 = item.badgeFor(55, false)
check("veteran non-vip", l2 == "Veteran" and c2 ~= nil and crown2 == true)
check("boundaries", select(1, item.badgeFor(10, false)) == "Regular" and select(1, item.badgeFor(9, false)) == "Newbie")
```
