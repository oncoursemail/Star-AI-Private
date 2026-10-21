---
id: gb-eng-docs-attributes-vs-valueobjects
category: docs-question
topics: attributes, ValueBase, IntValue, replication, GetAttributeChangedSignal
source: original
---
# Request
Should I store things like a door's "Locked" flag or a player's "Level" in attributes or in BoolValue/IntValue objects? What are the real differences, and how do I listen for changes with each?

# Answer
Both replicate from server to client and both fire change events. Attributes are properties on the instance itself: no extra objects, cheaper to create, visible in the Properties panel, readable in one call with `GetAttributes`. Value objects are separate instances: they can be referenced, parented, cloned on their own, and ObjectValue can hold an Instance reference, which attributes cannot. Use attributes by default and Value objects when you need an Instance reference or something legacy expects them (leaderstats requires Value objects).

```lua
--!strict
-- ModuleScript: ReplicatedStorage.DoorState (same logic written both ways)
local DoorState = {}

-- Attribute version: state lives on the door model itself
function DoorState.watchAttribute(door: Instance, onChange: (locked: boolean) -> ()): RBXScriptConnection
	local function emit()
		onChange(door:GetAttribute("Locked") == true)
	end
	emit()
	return door:GetAttributeChangedSignal("Locked"):Connect(emit)
end

-- Value-object version: state lives in a BoolValue child
function DoorState.watchValue(door: Instance, onChange: (locked: boolean) -> ()): RBXScriptConnection?
	local value = door:FindFirstChild("Locked")
	if value == nil or not value:IsA("BoolValue") then
		return nil
	end
	onChange(value.Value)
	return value.Changed:Connect(function()
		onChange(value.Value)
	end)
end

return DoorState
```

- Attribute types are limited to simple data (string, number, boolean, Vector3, CFrame, Color3, UDim2, NumberRange, and similar); tables and Instances are not allowed, and setting an unsupported type errors.
- `ValueBase.Changed` fires only when `Value` changes (and passes the new value), unlike `Changed` on other classes, which fires for every property; `GetAttributeChangedSignal(name)` passes nothing. Reading the current value inside the handler works the same for both.
- Changes made on the client stay on that client in both cases; only server-side changes replicate.

# Test
```lua
local door = Instance.new("Model")
door.Parent = workspace
local seen = {}
local conn = item.watchAttribute(door, function(locked)
	table.insert(seen, locked)
end)
door:SetAttribute("Locked", true)
door:SetAttribute("Locked", false)
check("attribute watcher reports initial and changes", seen[1] == false and seen[2] == true and seen[3] == false)
conn:Disconnect()
door:SetAttribute("Locked", true)
check("disconnect stops attribute updates", #seen == 3)
check("unsupported attribute type errors", not pcall(function() door:SetAttribute("Owner", {}) end))
local bool = Instance.new("BoolValue")
bool.Name = "Locked"
bool.Parent = door
local values = {}
item.watchValue(door, function(locked)
	table.insert(values, locked)
end)
bool.Value = true
check("value watcher reports changes", values[1] == false and values[2] == true)
check("missing value object returns nil", item.watchValue(Instance.new("Model"), function() end) == nil)
```
