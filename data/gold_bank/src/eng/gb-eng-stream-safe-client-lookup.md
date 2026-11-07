---
id: gb-eng-stream-safe-client-lookup
category: performance-streaming
topics: StreamingEnabled, WaitForChild timeout, client lookup, nil handling, shop counter
source: original
---
# Request
After enabling StreamingEnabled my LocalScript errors with "Counter is not a valid member of Model" on `workspace.Town.Shop.Counter.ProximityPrompt`, but only for players who spawn far away. I can't just use `WaitForChild` everywhere because some of these parts may never stream in for that player. What's the right way to look up parts from the client?

# Answer
Under streaming, any part of the path may be missing for a while, or may never arrive if the player stays far away. Resolve the path step by step with `WaitForChild` and a timeout so it never errors or hangs forever, and for things the player only needs when nearby, react when they appear instead of blocking startup.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.StreamPath (client)
local StreamPath = {}

-- Resolves "Town/Shop/Counter" under root, waiting at most `timeout` seconds in total. Returns nil on timeout.
function StreamPath.resolve(root: Instance, path: string, timeout: number): Instance?
	local deadline = os.clock() + timeout
	local node: Instance = root
	for name in string.gmatch(path, "[^/]+") do
		local remaining = deadline - os.clock()
		if remaining <= 0 then
			return nil
		end
		local child = node:WaitForChild(name, remaining)
		if child == nil then
			return nil
		end
		node = child
	end
	return node
end

-- Calls onReady every time the path becomes available (it can stream out and back in).
function StreamPath.whenAvailable(root: Instance, path: string, onReady: (Instance) -> ()): () -> ()
	local running = true
	local current: Instance? = nil
	task.spawn(function()
		while running do
			if current == nil or current.Parent == nil then
				local found = StreamPath.resolve(root, path, 5)
				if found and running and found ~= current then
					current = found
					onReady(found)
				end
			end
			task.wait(1)
		end
	end)
	return function()
		running = false
	end
end

return StreamPath
```

- Startup code: `local counter = StreamPath.resolve(workspace, "Town/Shop/Counter", 10)` and handle nil (show the shop UI without the counter highlight) instead of assuming it exists.
- For UI tied to a nearby object, `StreamPath.whenAvailable(workspace, "Town/Shop/Counter", setupPrompt)` re-runs setup each time the counter streams back in, because the client receives a fresh copy each time.
- Data the client always needs (prices, quest targets) should not live only in workspace parts; replicate it through ReplicatedStorage or attributes on non-streamed containers.

# Test
```lua
local town = Instance.new("Model")
town.Name = "Town"
town.Parent = workspace
local result = "pending"
task.spawn(function()
	result = item.resolve(workspace, "Town/Shop/Counter", 3)
end)
__advance(1)
local shop = Instance.new("Model")
shop.Name = "Shop"
shop.Parent = town
local counter = Instance.new("Part")
counter.Name = "Counter"
counter.Parent = shop
__advance(0.5)
check("resolves once the parts stream in", result == counter)
local missing = "pending"
task.spawn(function()
	missing = item.resolve(workspace, "Town/Bank/Vault", 2)
end)
__advance(3)
check("times out with nil instead of erroring", missing == nil)
local readyCount = 0
local stop = item.whenAvailable(workspace, "Town/Shop/Counter", function()
	readyCount += 1
end)
__advance(0.1)
check("whenAvailable fires for present part", readyCount == 1)
counter:Destroy()
__advance(2)
local copy = Instance.new("Part")
copy.Name = "Counter"
copy.Parent = shop
__advance(2)
check("fires again after streaming back in", readyCount == 2)
stop()
```
