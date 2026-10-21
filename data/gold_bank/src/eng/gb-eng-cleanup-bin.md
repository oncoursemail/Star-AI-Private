---
id: gb-eng-cleanup-bin
category: engineering-algorithm
topics: maid, trove, cleanup, connections, memory leaks
source: original
---
# Request
Every system I write ends with a long `cleanup()` that disconnects five connections, destroys three instances and cancels a thread, and I always forget one. People mention Maid/Trove objects. Can you write a small cleanup object like that, without a library?

# Answer
A cleanup bin collects anything that needs tearing down (connections, instances, threads, functions, other bins) and cleans them all in reverse order with one call. Cleaning is idempotent, so calling it twice, or from both a Destroying handler and a manual stop, is safe.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.CleanupBin
export type Bin = {
	add: <T>(self: Bin, item: T) -> T,
	connect: (self: Bin, signal: RBXScriptSignal, handler: (...any) -> ()) -> RBXScriptConnection,
	clean: (self: Bin) -> (),
	cleaned: boolean,
}

local CleanupBin = {}

local function dispose(item: any)
	local kind = typeof(item)
	if kind == "RBXScriptConnection" then
		item:Disconnect()
	elseif kind == "Instance" then
		item:Destroy()
	elseif kind == "thread" then
		if coroutine.status(item) ~= "dead" then
			pcall(task.cancel, item)
		end
	elseif kind == "function" then
		item()
	elseif kind == "table" then
		item:clean() -- another bin, or any object with a clean method
	else
		error(`cannot clean up a value of type {kind}`, 3)
	end
end

function CleanupBin.new(): Bin
	local items: { any } = {}
	local bin = { cleaned = false } :: Bin

	function bin.add<T>(self: Bin, item: T): T
		if self.cleaned then
			-- adding after clean-up (e.g. a late async callback): dispose right away instead of leaking
			dispose(item)
			return item
		end
		table.insert(items, item)
		return item
	end

	function bin.connect(self: Bin, signal: RBXScriptSignal, handler: (...any) -> ()): RBXScriptConnection
		return self:add(signal:Connect(handler))
	end

	function bin.clean(self: Bin)
		self.cleaned = true
		while #items > 0 do
			local item = items[#items]
			items[#items] = nil
			dispose(item)
		end
	end

	return bin
end

return CleanupBin
```

- Typical use per character: `local bin = CleanupBin.new(); bin:connect(humanoid.Died, onDied); bin:add(effectPart); character.Destroying:Once(function() bin:clean() end)`.
- Reverse order matters: things added later often depend on earlier ones (a connection on a part that the bin also owns), so they are torn down first.
- Adding to an already-cleaned bin disposes the item immediately, which closes the classic leak where an async load finishes after the player left.

# Test
```lua
local bin = item.new()
local part = Instance.new("Part")
part.Parent = workspace
local signalFired = 0
local event = Instance.new("BindableEvent")
bin:connect(event.Event, function()
	signalFired += 1
end)
bin:add(part)
local order = {}
bin:add(function() table.insert(order, "first") end)
bin:add(function() table.insert(order, "second") end)
local thread = task.delay(10, function()
	signalFired += 100
end)
bin:add(thread)
local child = item.new()
local childCleaned = false
child:add(function() childCleaned = true end)
bin:add(child)
event:Fire()
bin:clean()
event:Fire()
__advance(11)
check("connection disconnected", signalFired == 1)
check("instance destroyed", part.Parent == nil)
check("reverse order", order[1] == "second" and order[2] == "first")
check("nested bin cleaned", childCleaned)
bin:clean()
check("second clean is harmless", #order == 2)
local late = Instance.new("Part")
late.Parent = workspace
bin:add(late)
check("late add disposed immediately", late.Parent == nil)
local odd = item.new()
odd:add(42)
check("unsupported value errors on clean", not pcall(function() odd:clean() end))
```
