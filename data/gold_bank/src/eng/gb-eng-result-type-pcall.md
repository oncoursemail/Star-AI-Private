---
id: gb-eng-result-type-pcall
category: luau-typing
topics: result type, pcall, error handling, generics, union types
source: original
---
# Request
`pcall` returns `(boolean, any)` and I keep mixing up whether the second value is the result or the error message. Is there a typed way to wrap calls that can fail, so callers have to check before using the value?

# Answer
Wrap `pcall` in a function that returns a tagged `Result<T>`: either `{ ok: true, value: T }` or `{ ok: false, err: string }`. Checking `result.ok` refines the union, so the value is only reachable on the success branch.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Result
export type Result<T> = { ok: true, value: T } | { ok: false, err: string }

local Result = {}

function Result.try<T, A...>(fn: (A...) -> T, ...: A...): Result<T>
	local ok, valueOrErr = pcall(fn, ...)
	if ok then
		return { ok = true, value = valueOrErr }
	end
	return { ok = false, err = tostring(valueOrErr) }
end

function Result.unwrapOr<T>(result: Result<T>, fallback: T): T
	if result.ok then
		return result.value
	end
	return fallback
end

function Result.map<T, U>(result: Result<T>, fn: (T) -> U): Result<U>
	if result.ok then
		return Result.try(fn, result.value)
	end
	return result
end

return Result
```

- Usage: `local r = Result.try(store.GetAsync, store, key)`; `if r.ok then use(r.value) else warn(r.err) end`. Writing `r.value` without the check is a type error.
- `map` chains a transformation and passes failures through untouched, so a sequence of steps needs one error check at the end.
- `tostring(valueOrErr)` normalises errors thrown as tables or Instances into a string the caller can log.

# Test
```lua
local good = item.try(function(a, b)
	return a + b
end, 2, 3)
check("success holds value", good.ok and good.value == 5)
local bad = item.try(function()
	error("boom", 0)
end)
check("failure holds message", not bad.ok and bad.err == "boom")
check("unwrapOr success", item.unwrapOr(good, 0) == 5)
check("unwrapOr failure falls back", item.unwrapOr(bad, -1) == -1)
local doubled = item.map(good, function(v)
	return v * 2
end)
check("map transforms success", doubled.ok and doubled.value == 10)
check("map passes failure through", item.map(bad, function(v)
	return v
end).err == "boom")
local thrown = item.map(good, function()
	error({ code = 7 })
end)
check("map catches errors in fn", not thrown.ok and type(thrown.err) == "string")
```
