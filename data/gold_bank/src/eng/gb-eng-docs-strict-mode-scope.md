---
id: gb-eng-docs-strict-mode-scope
category: docs-question
topics: --!strict, type checking, runtime validation, any, type casts
source: original
---
# Request
If I put `--!strict` at the top of my scripts, does that mean bad values can't get into my functions anymore? What exactly does strict mode check, and what does it not do?

# Answer
`--!strict` makes the analyzer (Script Editor squiggles, Script Analysis) infer and check types for the whole file and report mismatches such as passing a string where a number is annotated, reading a field that does not exist on a known table type, or using a possibly-nil value without a check. It is purely edit-time: types are erased when the script runs, so nothing is checked at runtime. Data from outside your code (RemoteEvent arguments, DataStore values, JSON, attributes) can still be anything and must be validated by code.

```lua
--!strict
-- ModuleScript: ServerScriptService.Gift (static types for callers, runtime checks for the network)
local MAX_GIFT = 1000

local Gift = {}

-- Called by trusted server code: the annotation is enough, the analyzer checks every call site.
function Gift.clampAmount(amount: number): number
	return math.clamp(math.floor(amount), 1, MAX_GIFT)
end

-- Called with values that came from a client: annotate as unknown and check at runtime.
function Gift.parseRequest(targetId: unknown, amount: unknown): (number?, number?)
	if type(targetId) ~= "number" or targetId % 1 ~= 0 or targetId <= 0 then
		return nil, nil
	end
	if type(amount) ~= "number" or amount ~= amount then
		return nil, nil
	end
	return targetId, Gift.clampAmount(amount)
end

return Gift
```

- Strict mode does catch: wrong argument types, missing table fields on typed tables, calling a possibly-nil value, misspelled locals, returning the wrong type. It does not catch: values typed `any` (anything goes, unchecked), wrong values smuggled in with `::` casts, or anything that only happens at runtime.
- `--!nonstrict` (the default) infers less and reports fewer errors; `--!nocheck` turns checking off for the file. The mode never changes how the code executes.
- A function annotated `(amount: number)` will still receive a string at runtime if a remote passes one; that is why network entry points take `unknown` and refine with `type`/`typeof` before calling typed internals.

# Test
```lua
check("typed helper clamps", item.clampAmount(5000) == 1000 and item.clampAmount(0.5) == 1)
local target, amount = item.parseRequest(42, 250.7)
check("valid request parsed", target == 42 and amount == 250)
check("string amount rejected at runtime", item.parseRequest(42, "250") == nil)
check("NaN rejected", item.parseRequest(42, 0 / 0) == nil)
check("bad target rejected", item.parseRequest(-1, 10) == nil and item.parseRequest(1.5, 10) == nil and item.parseRequest({}, 10) == nil)
check("annotation is not a runtime guard: a table reaches math.floor and errors there", select(1, pcall(item.clampAmount, {})) == false)
```
