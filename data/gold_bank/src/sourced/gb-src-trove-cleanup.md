---
id: gb-src-trove-cleanup
category: performance
topics: memory leaks, cleanup, connections, Trove, Destroy, per-round objects
source: adapted
source_id: rbxutil
source_path: modules/trove/init.luau
source_commit: 31f9120fca021e3dec275b42bc7047d626962082
---
# Request
Each round I create parts, connect events, start loops and so on. When the round ends I try to clean up by hand but I always forget something and the server memory keeps climbing. Is there a pattern to track everything a round creates and clean it all at once?

# Answer
Use a cleanup container (the "trove" or "maid" pattern): register every instance, connection, thread and cleanup function as you create it, then call `clean()` at round end. Each kind gets the right cleanup: `Destroy`, `Disconnect`, `task.cancel`, or a call.

```lua
--!strict
export type Trove = {
	add: <T>(object: T) -> T,
	connect: (signal: RBXScriptSignal, fn: (...any) -> ()) -> RBXScriptConnection,
	clean: () -> (),
}

local Trove = {}

local function cleanupObject(object: any)
	local kind = typeof(object)
	if kind == "function" then
		task.spawn(object)
	elseif kind == "thread" then
		pcall(task.cancel, object)
	elseif kind == "RBXScriptConnection" then
		object:Disconnect()
	elseif kind == "Instance" then
		object:Destroy()
	elseif type(object) == "table" and type(object.Destroy) == "function" then
		local destroy: (any) -> () = object.Destroy
		destroy(object)
	else
		error("Trove cannot clean " .. kind)
	end
end

function Trove.new(): Trove
	local objects: { any } = {}
	local cleaning = false

	local function add<T>(object: T): T
		assert(not cleaning, "cannot add while cleaning")
		table.insert(objects, object)
		return object
	end

	local function connect(signal: RBXScriptSignal, fn: (...any) -> ()): RBXScriptConnection
		return add(signal:Connect(fn))
	end

	local function clean()
		if cleaning then
			return
		end
		cleaning = true
		for i = #objects, 1, -1 do
			cleanupObject(objects[i])
			objects[i] = nil
		end
		cleaning = false
	end

	return { add = add, connect = connect, clean = clean }
end

return Trove
```

Round usage:

```lua
--!strict
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local Trove = require(ReplicatedStorage:WaitForChild("Trove"))

local function runRound(arenaTemplate: Model, durationSeconds: number)
	local trove = Trove.new()
	local arena = trove.add(arenaTemplate:Clone())
	arena.Parent = workspace
	trove.connect(RunService.Heartbeat, function()
		arena:SetAttribute("Alive", true)
	end)
	trove.add(function()
		print("Round cleaned up")
	end)
	task.wait(durationSeconds)
	trove.clean()
end

return runRound
```

- Objects are cleaned in reverse order of creation, so things built on top of others are removed first.
- `add` returns its argument, so creation and registration stay on one line and nothing is forgotten.
- Anything with a `Destroy` method (your own classes, another trove) can be added too.

# Test
```lua
local trove = item.new()
local part = trove.add(Instance.new("Part"))
part.Parent = workspace
local fired = 0
local event = Instance.new("BindableEvent")
local conn = trove.connect(event.Event, function()
	fired += 1
end)
local cleaned = false
trove.add(function()
	cleaned = true
end)
trove.add(task.delay(10, function()
	fired += 100
end))
event:Fire()
trove.clean()
event:Fire()
__advance(11)
check("connection disconnected and delayed thread cancelled", fired == 1 and conn.Connected == false)
check("part destroyed", part.Parent == nil)
check("cleanup function ran", cleaned)
local other = item.new()
other.add(5)
check("unsupported values raise an error on clean", pcall(other.clean) == false)
```
