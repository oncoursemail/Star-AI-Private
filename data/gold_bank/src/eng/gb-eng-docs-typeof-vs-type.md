---
id: gb-eng-docs-typeof-vs-type
category: docs-question
topics: typeof, type, Roblox datatypes, IsA, argument validation
source: original
---
# Request
When should I use `type()` versus `typeof()`? I saw `type(part)` return "userdata" and got confused. And how does `IsA` fit in?

# Answer
`type` only knows the core Luau types (nil, boolean, number, string, table, function, thread, userdata, buffer, vector), so most Roblox values (Instances, CFrames, Color3s) are just "userdata" to it, and Vector3, which is built on Luau's native vector type, reports "vector". `typeof` additionally names Roblox datatypes: "Instance", "Vector3", "CFrame", "Color3", "EnumItem", and so on. Neither tells you the class of an Instance: use `typeof(x) == "Instance"` first, then `x:IsA("BasePart")`, which also accepts subclasses.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Describe
local Describe = {}

function Describe.value(x: unknown): string
	local kind = typeof(x)
	if kind == "Instance" then
		local instance = x :: Instance
		return `Instance<{instance.ClassName}>`
	elseif kind == "EnumItem" then
		return `EnumItem<{tostring(x)}>`
	end
	return kind
end

function Describe.isPart(x: unknown): boolean
	return typeof(x) == "Instance" and (x :: Instance):IsA("BasePart")
end

return Describe
```

- `x.ClassName == "Part"` misses `MeshPart`, `WedgePart` and other subclasses, while `IsA("BasePart")` accepts them all; prefer `IsA` for checks and `ClassName` only for exact display.
- On the server, validate RemoteEvent arguments with `typeof`: `type` would accept a CFrame, a Color3 and an Instance alike as "userdata".
- Calling `x:IsA(...)` on something that is not an Instance errors, which is why the `typeof` check must come first.

# Test
```lua
local part = Instance.new("Part")
local mesh = Instance.new("MeshPart")
check("typeof names the Roblox datatype", typeof(Vector3.zero) == "Vector3" and item.value(Vector3.zero) == "Vector3")
check("instances named with class", item.value(part) == "Instance<Part>")
check("plain values pass through", item.value(5) == "number" and item.value(nil) == "nil" and item.value({}) == "table")
check("IsA accepts subclasses", item.isPart(mesh) and item.isPart(part))
check("non-instances rejected safely", not item.isPart(Vector3.zero) and not item.isPart("Part") and not item.isPart(Instance.new("Folder")))
```
