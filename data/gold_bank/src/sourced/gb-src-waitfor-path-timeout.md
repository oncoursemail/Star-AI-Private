---
id: gb-src-waitfor-path-timeout
category: performance-streaming
topics: WaitForChild, timeout, instance paths, infinite yield, client loading, StreamingEnabled
source: adapted
source_id: rbxutil
source_path: modules/wait-for/init.luau
source_commit: 31f9120fca021e3dec275b42bc7047d626962082
---
# Request
My LocalScript does `workspace:WaitForChild("Map"):WaitForChild("Shop"):WaitForChild("Counter")` and sometimes hangs forever with an "Infinite yield possible" warning (streaming, or a renamed part). I'd like one helper that waits for a whole path with a single overall timeout and tells me which part was missing.

# Answer
Walk the path one name at a time with `WaitForChild(name, remaining)`, where `remaining` is what is left of the total time budget. `WaitForChild` with a timeout returns nil instead of yielding forever, so the helper can return nil plus the name that never appeared.

```lua
--!strict
local WaitFor = {}

function WaitFor.path(root: Instance, names: { string }, timeout: number): (Instance?, string?)
	local deadline = os.clock() + timeout
	local current = root
	for _, name in names do
		local remaining = deadline - os.clock()
		local child = current:FindFirstChild(name)
		if child == nil and remaining > 0 then
			child = current:WaitForChild(name, remaining)
		end
		if child == nil then
			return nil, name
		end
		current = child
	end
	return current, nil
end

return WaitFor
```

Usage: `local counter, missing = WaitFor.path(workspace, { "Map", "Shop", "Counter" }, 10)`; if `counter` is nil, warn with `missing` and disable the shop prompt instead of hanging.

- One deadline covers the whole path, so three slow steps cannot add up to three full timeouts.
- `FindFirstChild` first avoids a yield when the child already exists.
- With StreamingEnabled, parts far away may never arrive; returning nil lets the caller retry when the player gets closer instead of blocking the script.

# Test
```lua
local map = Instance.new("Folder")
map.Name = "Map"
map.Parent = workspace
local shop = Instance.new("Folder")
shop.Name = "Shop"
shop.Parent = map
local result, missing
task.spawn(function()
	result, missing = item.path(workspace, { "Map", "Shop", "Counter" }, 5)
end)
check("still waiting for the missing child", result == nil and missing == nil)
local counter = Instance.new("Part")
counter.Name = "Counter"
counter.Parent = shop
__advance(0.1)
check("resolves when the child appears", result == counter)
local r2, m2
task.spawn(function()
	r2, m2 = item.path(workspace, { "Map", "Garage", "Door" }, 2)
end)
__advance(2.1)
check("times out and names the missing step", r2 == nil and m2 == "Garage")
local r3 = item.path(workspace, { "Map", "Shop" }, 0)
check("existing path resolves without waiting", r3 == shop)
```
