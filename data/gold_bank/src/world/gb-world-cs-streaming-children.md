---
id: gb-world-cs-streaming-children
category: world-collectionservice
topics: StreamingEnabled, CollectionService, ChildAdded, client, tagged models
source: original
---
# Request
After turning on StreamingEnabled, my client script for tagged doors errors with "Hinge is not a valid member" or hangs on `door:WaitForChild("Hinge")` forever. The door Model streams in before its parts sometimes. How do I handle tagged models whose children may not be there yet?

# Answer
Never block the tag handler. When a tagged door appears, check for the child; if it is missing, listen to `ChildAdded` until it arrives and set the door up then. If the door streams out (tag removed) before that, the pending listener is disconnected, so nothing waits forever and nothing runs on a half-loaded model.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.StreamedDoors
local CollectionService = game:GetService("CollectionService")

local StreamedDoors = {}

function StreamedDoors.watch(tag: string, childName: string, setup: (door: Instance, child: Instance) -> () -> ()): () -> ()
	local pending: { [Instance]: RBXScriptConnection } = {}
	local teardowns: { [Instance]: () -> () } = {}

	local function ready(door: Instance, child: Instance)
		local connection = pending[door]
		if connection then
			connection:Disconnect()
			pending[door] = nil
		end
		teardowns[door] = setup(door, child)
	end

	local function onAdded(door: Instance)
		if pending[door] or teardowns[door] then
			return
		end
		local child = door:FindFirstChild(childName)
		if child then
			ready(door, child)
			return
		end
		pending[door] = door.ChildAdded:Connect(function(added: Instance)
			if added.Name == childName then
				ready(door, added)
			end
		end)
	end

	local function onRemoved(door: Instance)
		local connection = pending[door]
		if connection then
			connection:Disconnect()
			pending[door] = nil
		end
		local teardown = teardowns[door]
		if teardown then
			teardowns[door] = nil
			teardown()
		end
	end

	local added = CollectionService:GetInstanceAddedSignal(tag):Connect(onAdded)
	local removed = CollectionService:GetInstanceRemovedSignal(tag):Connect(onRemoved)
	for _, door in CollectionService:GetTagged(tag) do
		onAdded(door)
	end

	return function()
		added:Disconnect()
		removed:Disconnect()
		for door in pending do
			onRemoved(door)
		end
		for door in teardowns do
			onRemoved(door)
		end
	end
end

return StreamedDoors
```

Usage: `StreamedDoors.watch("Door", "Hinge", function(door, hinge) ... return function() ... end end)`, where the returned function undoes whatever setup created.

- A blocking `WaitForChild` in the added handler stalls only that thread but leaks it forever when the model streams out before the child arrives; the ChildAdded listener is cancelled instead.
- Setting the door model's `ModelStreamingMode` to `Atomic` makes the whole model stream together, which removes the problem for small models; this pattern covers large ones that must stay non-atomic.
- Setup runs exactly once per streamed-in door, and its teardown runs on stream-out, so effects and connections never pile up while players walk back and forth.

# Test
```lua
local cs = game:GetService("CollectionService")
local setups, teardowns = 0, 0
local stop = item.watch("Door", "Hinge", function()
	setups += 1
	return function()
		teardowns += 1
	end
end)

local complete = Instance.new("Model")
Instance.new("Part").Parent = complete
complete.Part.Name = "Hinge"
complete.Parent = workspace
cs:AddTag(complete, "Door")
check("complete door is set up immediately", setups == 1)

local partial = Instance.new("Model")
partial.Parent = workspace
cs:AddTag(partial, "Door")
check("door without its child waits without setting up", setups == 1)
local other = Instance.new("Part")
other.Name = "Frame"
other.Parent = partial
check("unrelated children do not trigger setup", setups == 1)
local hinge = Instance.new("Part")
hinge.Name = "Hinge"
hinge.Parent = partial
check("setup runs when the child streams in", setups == 2)

local gone = Instance.new("Model")
gone.Parent = workspace
cs:AddTag(gone, "Door")
cs:RemoveTag(gone, "Door")
local late = Instance.new("Part")
late.Name = "Hinge"
late.Parent = gone
check("a door that streamed out never sets up", setups == 2)
cs:RemoveTag(complete, "Door")
check("stream-out runs the teardown", teardowns == 1)
stop()
check("stop tears down remaining doors", teardowns == 2)
```
