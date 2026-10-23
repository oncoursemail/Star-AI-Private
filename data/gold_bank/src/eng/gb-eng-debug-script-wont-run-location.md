---
id: gb-eng-debug-script-wont-run-location
category: engineering-debugging
topics: script location, RunContext, LocalScript, ReplicatedStorage, script not running
source: original
---
# Request
I have two scripts that never run, not even a `print` at the top: a Script inside a folder in ReplicatedStorage that should set up remotes, and a LocalScript inside a part in Workspace that should make a door glow for the local player. No errors at all. What's going on?

# Answer
Scripts only run from specific containers. A Script with the default `RunContext` (Legacy) runs only under Workspace or ServerScriptService, so it sits inert in ReplicatedStorage. A LocalScript runs only when it is a descendant of something owned by the local player: PlayerScripts, PlayerGui, Backpack, the player's character, or ReplicatedFirst; inside a Workspace part it never runs. Move them, or set `RunContext` so the location stops mattering.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.ScriptPlacement (a small audit you can run from the command bar)
export type Problem = { path: string, reason: string }

local ScriptPlacement = {}

local SERVER_OK: { [string]: boolean } = { Workspace = true, ServerScriptService = true }
local SERVER_ONLY: { [string]: boolean } = { ServerScriptService = true, ServerStorage = true }
local CLIENT_OK: { [string]: boolean } = { PlayerScripts = true, PlayerGui = true, Backpack = true, ReplicatedFirst = true,
	StarterPlayerScripts = true, StarterCharacterScripts = true, StarterGui = true, StarterPack = true }

local function containerNames(instance: Instance): { [string]: boolean }
	local names: { [string]: boolean } = {}
	local node = instance.Parent
	while node do
		names[node.Name] = true
		names[node.ClassName] = true
		node = node.Parent
	end
	return names
end

function ScriptPlacement.check(instance: Instance): string?
	local above = containerNames(instance)
	if instance:IsA("LocalScript") then
		for name in CLIENT_OK do
			if above[name] then
				return nil
			end
		end
		return "LocalScript outside player-owned containers never runs"
	elseif instance:IsA("Script") then
		local context = instance.RunContext
		if context == Enum.RunContext.Client then
			for name in SERVER_ONLY do
				if above[name] then
					return "Client RunContext Script in a server-only container never reaches clients"
				end
			end
			return nil
		elseif context == Enum.RunContext.Server then
			return nil
		end
		for name in SERVER_OK do
			if above[name] then
				return nil
			end
		end
		return "Legacy Script outside Workspace/ServerScriptService never runs"
	end
	return nil
end

function ScriptPlacement.audit(root: Instance): { Problem }
	local problems: { Problem } = {}
	for _, descendant in root:GetDescendants() do
		local reason = ScriptPlacement.check(descendant)
		if reason then
			table.insert(problems, { path = descendant:GetFullName(), reason = reason })
		end
	end
	return problems
end

return ScriptPlacement
```

- Remote setup belongs in ServerScriptService (Script) with the RemoteEvents themselves placed in ReplicatedStorage.
- For the door, put a LocalScript in StarterPlayerScripts that finds the door (`workspace:WaitForChild("Door")`) and changes it locally; or use a Script with `RunContext = Client`, which runs on every client wherever clients can see it (Workspace, ReplicatedStorage), including inside the door; in ServerScriptService or ServerStorage it never reaches them.
- A Script with `RunContext = Server` in ReplicatedStorage would run, but its source is then replicated to clients; keep server code in ServerScriptService.

# Test
```lua
local rs = game:GetService("ReplicatedStorage")
local folder = Instance.new("Folder")
folder.Name = "Setup"
folder.Parent = rs
local inert = Instance.new("Script")
inert.Name = "MakeRemotes"
inert.RunContext = Enum.RunContext.Legacy
inert.Parent = folder
local door = Instance.new("Part")
door.Name = "Door"
door.Parent = workspace
local glow = Instance.new("LocalScript")
glow.Name = "Glow"
glow.Parent = door
local clientCtx = Instance.new("Script")
clientCtx.RunContext = Enum.RunContext.Client
clientCtx.Parent = door
local serverScript = Instance.new("Script")
serverScript.RunContext = Enum.RunContext.Legacy
serverScript.Parent = game:GetService("ServerScriptService")
check("legacy script in ReplicatedStorage flagged", item.check(inert) ~= nil)
check("LocalScript in workspace part flagged", item.check(glow) ~= nil)
check("RunContext Client script accepted in a replicated container", item.check(clientCtx) == nil)
local hiddenClient = Instance.new("Script")
hiddenClient.RunContext = Enum.RunContext.Client
hiddenClient.Parent = game:GetService("ServerScriptService")
check("RunContext Client script in ServerScriptService flagged", item.check(hiddenClient) ~= nil)
check("legacy script in ServerScriptService fine", item.check(serverScript) == nil)
local problems = item.audit(rs)
check("audit lists the inert script", #problems == 1 and problems[1].path == "ReplicatedStorage.Setup.MakeRemotes")
```
