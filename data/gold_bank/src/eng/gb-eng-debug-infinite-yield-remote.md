---
id: gb-eng-debug-infinite-yield-remote
category: engineering-debugging
topics: infinite yield, WaitForChild, replication, ServerStorage, timeout
source: original
---
# Request
My LocalScript prints `Infinite yield possible on 'ReplicatedStorage:WaitForChild("Remotes")'` and nothing after that line runs. The folder definitely exists, a server script creates it:

```lua
-- server Script
local folder = Instance.new("Folder")
folder.Name = "Remotes"
folder.Parent = game:GetService("ServerStorage")
local shoot = Instance.new("RemoteEvent")
shoot.Name = "Shoot"
shoot.Parent = folder

-- LocalScript
local remotes = game:GetService("ReplicatedStorage"):WaitForChild("Remotes")
local shoot = remotes:WaitForChild("Shoot")
```

# Answer
The folder is parented to ServerStorage, which never replicates to clients, so the client waits on ReplicatedStorage forever. Create remotes under ReplicatedStorage. On the client, wait with a timeout and a message that names the missing path, so the next mistake (a renamed or misplaced object) fails loudly instead of hanging silently.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Remotes (shared by server and client)
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local FOLDER_NAME = "Remotes"
local Remotes = {}

function Remotes.serverEnsure(names: { string }): Folder
	assert(RunService:IsServer(), "only the server creates remotes")
	local folder = ReplicatedStorage:FindFirstChild(FOLDER_NAME)
	if folder == nil then
		folder = Instance.new("Folder")
		folder.Name = FOLDER_NAME
		folder.Parent = ReplicatedStorage
	end
	for _, name in names do
		if folder:FindFirstChild(name) == nil then
			local remote = Instance.new("RemoteEvent")
			remote.Name = name
			remote.Parent = folder
		end
	end
	return folder
end

function Remotes.clientGet(name: string, timeout: number?): RemoteEvent?
	local limit = timeout or 10
	local folder = ReplicatedStorage:WaitForChild(FOLDER_NAME, limit)
	if folder == nil then
		warn(`ReplicatedStorage.{FOLDER_NAME} did not appear within {limit}s; is it created under ReplicatedStorage on the server?`)
		return nil
	end
	local remote = folder:WaitForChild(name, limit)
	if remote == nil or not remote:IsA("RemoteEvent") then
		warn(`{FOLDER_NAME}.{name} is missing or not a RemoteEvent`)
		return nil
	end
	return remote
end

return Remotes
```

- ServerStorage and ServerScriptService exist only on the server; anything a LocalScript needs must be in ReplicatedStorage, Workspace, or the player's PlayerGui/Backpack.
- `WaitForChild(name, timeout)` returns nil after the timeout instead of yielding forever, so the script can report the problem and carry on (for example, disable the gun UI).
- Even simpler: put the Remotes folder and its RemoteEvents in ReplicatedStorage in Studio. Objects saved in the place exist before any script runs, so neither side has to wait for the other.

# Test
```lua
local got
task.spawn(function()
	got = item.clientGet("Shoot", 2)
end)
check("client waits while folder is missing", got == nil)
__advance(1)
item.serverEnsure({ "Shoot", "Reload" })
__advance(0.5)
check("client resolves once server creates remote", got ~= nil and got.Name == "Shoot" and got:IsA("RemoteEvent"))
local folder = game:GetService("ReplicatedStorage"):FindFirstChild("Remotes")
check("folder under ReplicatedStorage", folder ~= nil and folder:FindFirstChild("Reload") ~= nil)
item.serverEnsure({ "Shoot" })
check("ensure is idempotent", #folder:GetChildren() == 2)
local missing = "pending"
task.spawn(function()
	missing = item.clientGet("DoesNotExist", 1)
end)
__advance(2)
check("timeout returns nil instead of hanging", missing == nil)
```
