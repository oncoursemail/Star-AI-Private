---
id: gb-world-cs-component-binder
category: world-collectionservice
topics: CollectionService, components, cleanup, janitor pattern, tag binder
source: original
---
# Request
I want a small reusable "component" system: I register a constructor for a tag, it runs for every tagged instance, and whatever the constructor connects or creates is cleaned up automatically when the tag is removed or the instance is destroyed. Something like a mini Trove/Janitor plus binder.

# Answer
Two pieces: a cleanup bag that collects connections, instances and functions and releases them all at once, and a binder that creates one bag per tagged instance, calls your constructor with it, and empties the bag when the instance loses the tag. Constructors never write their own teardown code.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.TagBinder
local CollectionService = game:GetService("CollectionService")

export type Bag = {
	add: (item: RBXScriptConnection | Instance | () -> ()) -> (),
	clean: () -> (),
}

local TagBinder = {}

function TagBinder.newBag(): Bag
	local items: { any } = {}
	return {
		add = function(item: RBXScriptConnection | Instance | () -> ())
			table.insert(items, item)
		end,
		clean = function()
			-- Release in reverse order, like a stack: later items may depend on earlier ones.
			for index = #items, 1, -1 do
				local item = items[index]
				local kind = typeof(item)
				if kind == "RBXScriptConnection" then
					item:Disconnect()
				elseif kind == "Instance" then
					item:Destroy()
				elseif kind == "function" then
					item()
				end
			end
			table.clear(items)
		end,
	}
end

function TagBinder.bind(tag: string, construct: (instance: Instance, bag: Bag) -> ()): () -> ()
	local bags: { [Instance]: Bag } = {}

	local function onAdded(instance: Instance)
		if bags[instance] then
			return
		end
		local bag = TagBinder.newBag()
		bags[instance] = bag
		local ok, err = pcall(construct, instance, bag)
		if not ok then
			warn(string.format("%s component failed on %s: %s", tag, instance:GetFullName(), tostring(err)))
		end
	end

	local function onRemoved(instance: Instance)
		local bag = bags[instance]
		if bag then
			bags[instance] = nil
			bag.clean()
		end
	end

	local added = CollectionService:GetInstanceAddedSignal(tag):Connect(onAdded)
	local removed = CollectionService:GetInstanceRemovedSignal(tag):Connect(onRemoved)
	for _, instance in CollectionService:GetTagged(tag) do
		onAdded(instance)
	end

	return function()
		added:Disconnect()
		removed:Disconnect()
		for instance in bags do
			onRemoved(instance)
		end
	end
end

return TagBinder
```

A component written with it, a lamp that glows while its `On` attribute is true:

```lua
--!strict
local TagBinder = require(game:GetService("ReplicatedStorage"):WaitForChild("TagBinder"))

TagBinder.bind("Lamp", function(lamp, bag)
	local light = Instance.new("PointLight")
	light.Parent = lamp
	bag.add(light)
	local function refresh()
		light.Enabled = lamp:GetAttribute("On") == true
	end
	bag.add(lamp:GetAttributeChangedSignal("On"):Connect(refresh))
	refresh()
end)
```

- Errors in one constructor are caught and reported with the instance path, so one broken lamp does not stop the other 199 from binding.
- Destroying a tagged instance fires the removed signal, so cleanup happens for deletions and for StreamingEnabled stream-outs, not only for explicit `RemoveTag`.
- The binder returns an unbind function that tears down every live component, which is what you want for hot-reloading or ending a minigame.

# Test
```lua
local cs = game:GetService("CollectionService")
local log = {}
local unbind = item.bind("Lamp", function(lamp, bag)
	local light = Instance.new("PointLight")
	light.Parent = lamp
	bag.add(light)
	bag.add(lamp:GetAttributeChangedSignal("On"):Connect(function()
		light.Enabled = lamp:GetAttribute("On") == true
	end))
	bag.add(function()
		table.insert(log, "cleaned " .. lamp.Name)
	end)
end)

local lamp = Instance.new("Part")
lamp.Name = "Lamp1"
lamp.Parent = workspace
cs:AddTag(lamp, "Lamp")
local light = lamp:FindFirstChildOfClass("PointLight")
lamp:SetAttribute("On", false)
check("component constructed for a new tag", light ~= nil and light.Enabled == false)
cs:RemoveTag(lamp, "Lamp")
check("removing the tag cleans everything", lamp:FindFirstChildOfClass("PointLight") == nil and log[1] == "cleaned Lamp1")
lamp:SetAttribute("On", true)
check("connections were disconnected", #log == 1)

local broken = item.bind("Broken", function()
	error("boom")
end)
local part = Instance.new("Part")
part.Parent = workspace
check("a failing constructor does not throw", pcall(cs.AddTag, cs, part, "Broken"))
cs:AddTag(lamp, "Lamp")
unbind()
check("unbind cleans live components", #log == 2 and lamp:FindFirstChildOfClass("PointLight") == nil)
broken()
```
