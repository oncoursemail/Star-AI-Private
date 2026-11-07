---
id: gb-data-inv-tools-from-inventory
category: server-authoritative-inventory
topics: Tools, Backpack, ServerStorage templates, respawn, inventory sync
source: original
---
# Request
My weapons are Tools. I save which tools a player owns, but after they respawn the tools are gone, and sometimes players end up with two of the same sword. How do I keep the Backpack in sync with the saved inventory?

# Answer
Treat the saved inventory as the truth and the Tools as a view of it: tool templates live in ServerStorage, and a `sync` function makes the Backpack plus character hold exactly one Tool per owned weapon, cloning missing ones and removing ones not owned. Run it on every spawn and after any inventory change.

```lua
--!strict
-- ModuleScript: ServerScriptService.ToolSync
local ServerStorage = game:GetService("ServerStorage")

local ToolSync = {}

local function templates(): Folder?
	local folder: Folder? = ServerStorage:FindFirstChild("ToolTemplates")
	return folder
end

-- owned is the server's set of weapon ids, e.g. { WoodSword = true, Bow = true }.
function ToolSync.sync(player: Player, owned: { [string]: boolean })
	local backpack = player:FindFirstChildOfClass("Backpack")
	local folder = templates()
	if backpack == nil or folder == nil then
		return
	end
	local present: { [string]: boolean } = {}
	local containers: { Instance } = { backpack }
	if player.Character then
		table.insert(containers, player.Character)
	end
	for _, container in containers do
		for _, child in container:GetChildren() do
			if child:IsA("Tool") then
				if not owned[child.Name] or present[child.Name] then
					child:Destroy() -- not owned anymore, or a duplicate
				else
					present[child.Name] = true
				end
			end
		end
	end
	for id in owned do
		local template = folder:FindFirstChild(id)
		if not present[id] and template and template:IsA("Tool") then
			local tool = template:Clone()
			-- A dropped Tool leaves the Backpack, so the next sync would hand out another copy.
			tool.CanBeDropped = false
			tool.Parent = backpack
		end
	end
end

return ToolSync
```

Hook it up where you load data: `player.CharacterAdded:Connect(function() ToolSync.sync(player, profile.weapons) end)`, and call `sync` again after buying, selling or trading a weapon.

- Templates in ServerStorage cannot be read or cloned by clients, so the only way to get a Tool is through `sync`.
- Checking both Backpack and Character covers an equipped tool, which is parented to the character while held. `CanBeDropped = false` closes the other gap: a dropped Tool sits in Workspace, where `sync` would not see it, so another player could pick it up while its owner gets a fresh copy.
- The Tool's name is its id here; if you rename display names, store the id in an attribute and compare that instead.

# Test
```lua
local folder = Instance.new("Folder")
folder.Name = "ToolTemplates"
for _, name in { "WoodSword", "Bow", "Staff" } do
	local tool = Instance.new("Tool")
	tool.Name = name
	tool.Parent = folder
end
folder.Parent = game:GetService("ServerStorage")
```
```lua
local p = __makePlayer(1, "Warrior")
__makeCharacter(p)
local owned = { WoodSword = true, Bow = true }
item.sync(p, owned)
local function countTools()
	local counts = {}
	for _, container in { p.Backpack, p.Character } do
		for _, child in container:GetChildren() do
			if child:IsA("Tool") then
				counts[child.Name] = (counts[child.Name] or 0) + 1
			end
		end
	end
	return counts
end
local c = countTools()
check("owned tools are given", c.WoodSword == 1 and c.Bow == 1 and c.Staff == nil)
check("given tools cannot be dropped and re-synced into copies", p.Backpack.Bow.CanBeDropped == false)

p.Backpack.Bow.Parent = p.Character
item.sync(p, owned)
c = countTools()
check("an equipped tool is not duplicated", c.Bow == 1)

local extra = Instance.new("Tool")
extra.Name = "WoodSword"
extra.Parent = p.Backpack
item.sync(p, owned)
check("duplicates are removed", countTools().WoodSword == 1)

owned.WoodSword = nil
item.sync(p, owned)
check("tools no longer owned are removed", countTools().WoodSword == nil)

__makeCharacter(p)
for _, child in p.Backpack:GetChildren() do
	child:Destroy()
end
item.sync(p, owned)
check("sync after respawn restores the tools", countTools().Bow == 1)
```
