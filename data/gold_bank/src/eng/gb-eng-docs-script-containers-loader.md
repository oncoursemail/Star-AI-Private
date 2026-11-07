---
id: gb-eng-docs-script-containers-loader
category: docs-question
topics: script containers, ServerScriptService, ReplicatedStorage, ModuleScript loader, project structure
source: original
---
# Request
I'm confused about where code should live: ServerScriptService, ServerStorage, ReplicatedStorage, ReplicatedFirst, StarterPlayerScripts, StarterCharacterScripts. Some tutorials use dozens of Scripts, others one Script that requires modules. What's the standard layout and why?

# Answer
- ServerScriptService: server Scripts and server-only ModuleScripts. Never replicated, so clients cannot read the code.
- ServerStorage: server-only assets (maps, tools to clone); ModuleScripts here also work and are hidden from clients.
- ReplicatedStorage: ModuleScripts and assets both sides need (shared types, config, RemoteEvents).
- ReplicatedFirst: a tiny LocalScript for the loading screen; it runs before anything else replicates.
- StarterPlayerScripts: client code that runs once per session. StarterCharacterScripts: client code copied into each new character, restarting every life.

The common layout is one Script on the server and one LocalScript on the client that require your systems as ModuleScripts and start them in a fixed order, so load order is explicit instead of depending on which Script happens to run first.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Bootstrap (used by the single server Script and the single client LocalScript)
export type System = { name: string?, init: (() -> ())?, start: (() -> ())? }

local Bootstrap = {}

function Bootstrap.run(moduleScripts: { Instance }, load: (ModuleScript) -> any): { string }
	local systems: { { name: string, system: System } } = {}
	for _, moduleScript in moduleScripts do
		if moduleScript:IsA("ModuleScript") then
			table.insert(systems, { name = moduleScript.Name, system = load(moduleScript) :: System })
		end
	end
	table.sort(systems, function(a: { name: string, system: System }, b: { name: string, system: System }): boolean
		return a.name < b.name
	end)
	local started: { string } = {}
	-- phase 1: init everything (create remotes, read config) before any system starts talking to another
	for _, entry in systems do
		if entry.system.init then
			entry.system.init()
		end
	end
	-- phase 2: start (connect events, spawn loops)
	for _, entry in systems do
		if entry.system.start then
			task.spawn(entry.system.start)
		end
		table.insert(started, entry.name)
	end
	return started
end

return Bootstrap
```

- Server Script in ServerScriptService: `Bootstrap.run(ServerScriptService.Systems:GetChildren(), require)`; client LocalScript in StarterPlayerScripts does the same with its client systems folder.
- Two phases mean a system's `start` can safely call another system that was set up in `init`, whatever their names.
- `start` runs in `task.spawn`, so a system with a long-running loop does not block the others from starting.

# Test
```lua
local folder = Instance.new("Folder")
local log = {}
local fakes = {}
for _, name in { "Shop", "Combat", "Data" } do
	local m = Instance.new("ModuleScript")
	m.Name = name
	m.Parent = folder
	fakes[m] = {
		init = function() table.insert(log, "init " .. name) end,
		start = function() table.insert(log, "start " .. name) end,
	}
end
local note = Instance.new("StringValue")
note.Parent = folder
local started = item.run(folder:GetChildren(), function(m)
	return fakes[m]
end)
check("all inits before any start", log[1] == "init Combat" and log[3] == "init Shop" and log[4] == "start Combat")
check("deterministic order by name", started[1] == "Combat" and started[2] == "Data" and started[3] == "Shop")
check("non-module children ignored", #started == 3 and #log == 6)
check("systems without hooks allowed", #item.run({ folder:FindFirstChild("Data") }, function() return {} end) == 1)
```
