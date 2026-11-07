---
id: gb-data-remote-arg-validators
category: remote-security
topics: RemoteEvent, argument validation, NaN, typeof, string length
source: original
---
# Request
I keep writing the same `if type(x) ~= "number"` checks in every RemoteEvent handler and I still miss cases like NaN. Can you write a small validation module I can reuse for numbers, integers, strings, Vector3s, allowed options and Instances?

# Answer
Each validator takes the raw `unknown` argument and returns the typed value when it passes, or `nil`. Handlers then read like a list of requirements, and NaN, infinity, invalid UTF-8 and wrong Instance classes are rejected in one place.

```lua
--!strict
-- ModuleScript: ServerScriptService.Check
local Check = {}

function Check.finite(value: unknown): number?
	if type(value) == "number" and value == value and value ~= math.huge and value ~= -math.huge then
		return value
	end
	return nil
end

function Check.number(value: unknown, min: number, max: number): number?
	local n = Check.finite(value)
	if n and n >= min and n <= max then
		return n
	end
	return nil
end

function Check.integer(value: unknown, min: number, max: number): number?
	local n = Check.number(value, min, max)
	if n and n % 1 == 0 then
		return n
	end
	return nil
end

function Check.text(value: unknown, maxLength: number): string?
	if type(value) == "string" and #value <= maxLength and utf8.len(value) ~= nil then
		return value
	end
	return nil
end

-- allowed is a server-owned set such as { Red = true, Blue = true }.
function Check.option(value: unknown, allowed: { [string]: boolean }): string?
	if type(value) == "string" and allowed[value] == true then
		return value
	end
	return nil
end

function Check.vector3(value: unknown, maxMagnitude: number): Vector3?
	local kind = typeof(value)
	if kind ~= "Vector3" then
		return nil
	end
	local v = value :: any
	if Check.finite(v.X) and Check.finite(v.Y) and Check.finite(v.Z) and v.Magnitude <= maxMagnitude then
		return v
	end
	return nil
end

function Check.instance(value: unknown, className: string): Instance?
	local kind = typeof(value)
	if kind == "Instance" and (value :: any):IsA(className) then
		return value :: any
	end
	return nil
end

return Check
```

Usage in a handler:

```lua
--!strict
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerScriptService = game:GetService("ServerScriptService")
local Check = require(ServerScriptService.Check)

local paint = ReplicatedStorage:WaitForChild("PaintPart") :: RemoteEvent
local COLORS = { Red = true, Blue = true, Green = true }

local function onPaint(player: Player, slotArg: unknown, colorArg: unknown, labelArg: unknown)
	local slot = Check.integer(slotArg, 1, 20)
	local color = Check.option(colorArg, COLORS)
	local label = Check.text(labelArg, 30)
	if slot == nil or color == nil or label == nil then
		return
	end
	print(player.Name, "paints slot", slot, color, label)
end

paint.OnServerEvent:Connect(onPaint)
```

- NaN fails every comparison, so `if amount > 100 then return end` lets NaN straight through; `Check.finite` catches it with `value == value`.
- `#value` counts bytes, which bounds memory and DataStore size; filter any text other players will see before storing it.
- Look options up in a server table instead of trusting the string: an exploiter can send "__index" or any other key.

# Test
```lua
check("finite rejects NaN and inf", item.finite(0 / 0) == nil and item.finite(math.huge) == nil and item.finite(3) == 3)
check("number enforces range", item.number(5, 0, 10) == 5 and item.number(11, 0, 10) == nil and item.number("5", 0, 10) == nil)
check("integer rejects fractions", item.integer(2.5, 0, 10) == nil and item.integer(4, 0, 10) == 4)
check("text enforces length and type", item.text("hi", 5) == "hi" and item.text("toolongtext", 5) == nil and item.text(12, 5) == nil)
check("text rejects invalid UTF-8", item.text("\255\254", 10) == nil)
local allowed = { Red = true }
check("option only accepts listed values", item.option("Red", allowed) == "Red" and item.option("__index", allowed) == nil
	and item.option("Purple", allowed) == nil)
check("vector3 checks magnitude and type", item.vector3(Vector3.new(1, 2, 2), 5) ~= nil
	and item.vector3(Vector3.new(100, 0, 0), 5) == nil and item.vector3({ X = 1, Y = 1, Z = 1 }, 5) == nil)
check("vector3 rejects NaN components", item.vector3(Vector3.new(0 / 0, 0, 0), 5) == nil)
local part = Instance.new("Part")
check("instance checks class", item.instance(part, "BasePart") == part and item.instance(part, "Tool") == nil
	and item.instance("Part", "BasePart") == nil)
```
