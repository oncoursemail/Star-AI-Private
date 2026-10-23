---
id: gb-src-tagged-conveyors
category: world-collectionservice
topics: CollectionService, tags, GetInstanceAddedSignal, GetInstanceRemovedSignal, AssemblyLinearVelocity, conveyor
source: adapted
source_id: creator-docs
source_path: content/en-us/reference/engine/classes/CollectionService.yaml
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
My factory map has about 80 conveyor belt parts, each with its own copy of a script that moves things along. Editing the speed means changing 80 scripts. How do I drive all of them from one script, including conveyors I spawn later?

# Answer
Tag every belt "Conveyor" and give it a `Speed` attribute. One server script sets up each tagged part as it appears and undoes it when the tag is removed. An anchored part with `AssemblyLinearVelocity` set carries whatever stands on it without moving itself.

```lua
--!strict
local CollectionService = game:GetService("CollectionService")

local TAG = "Conveyor"
local DEFAULT_SPEED = 10

local connections: { [Instance]: RBXScriptConnection } = {}

local function apply(belt: BasePart)
	local speed = belt:GetAttribute("Speed")
	if typeof(speed) ~= "number" then
		speed = DEFAULT_SPEED
	end
	belt.AssemblyLinearVelocity = belt.CFrame.LookVector * speed
end

local function onAdded(instance: Instance)
	if not instance:IsA("BasePart") then
		return
	end
	instance.Anchored = true
	apply(instance)
	connections[instance] = instance:GetAttributeChangedSignal("Speed"):Connect(function()
		apply(instance)
	end)
end

local function onRemoved(instance: Instance)
	local connection = connections[instance]
	if connection then
		connection:Disconnect()
		connections[instance] = nil
	end
	if instance:IsA("BasePart") then
		instance.AssemblyLinearVelocity = Vector3.zero
	end
end

for _, belt in CollectionService:GetTagged(TAG) do
	onAdded(belt)
end
CollectionService:GetInstanceAddedSignal(TAG):Connect(onAdded)
CollectionService:GetInstanceRemovedSignal(TAG):Connect(onRemoved)
```

- The belt pushes along its front face (`LookVector`); rotate a belt to change direction, set `Speed` negative to reverse it.
- The removed signal also fires when a tagged part is destroyed, so the connection table does not leak.
- Changing `Speed` at runtime (for example a "power surge" event) updates the belt immediately through the attribute signal.

# Test
```lua
local CollectionService = game:GetService("CollectionService")
local belt = Instance.new("Part")
belt.CFrame = CFrame.new(0, 0, 0)
belt.Parent = workspace
CollectionService:AddTag(belt, "Conveyor")
```

```lua
local CollectionService = game:GetService("CollectionService")
local belt = workspace:FindFirstChildOfClass("Part")
check("existing belt anchored and moving forward", belt.Anchored == true and (belt.AssemblyLinearVelocity - Vector3.new(0, 0, -10)).Magnitude < 1e-4)
belt:SetAttribute("Speed", 25)
check("speed attribute applied live", math.abs(belt.AssemblyLinearVelocity.Magnitude - 25) < 1e-4)
local late = Instance.new("Part")
late.Parent = workspace
CollectionService:AddTag(late, "Conveyor")
check("belt tagged later is set up", late.AssemblyLinearVelocity.Magnitude > 0)
CollectionService:RemoveTag(belt, "Conveyor")
check("untagged belt stops", belt.AssemblyLinearVelocity == Vector3.zero)
belt:SetAttribute("Speed", 50)
check("no longer reacts after removal", belt.AssemblyLinearVelocity == Vector3.zero)
```
