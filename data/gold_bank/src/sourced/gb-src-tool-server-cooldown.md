---
id: gb-src-tool-server-cooldown
category: tool-attachment
topics: Tool, Activated, Equipped, server script, cooldown, unanchor handle
source: adapted
source_id: creator-docs
source_path: content/en-us/players/tools.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I made a water spell Tool. When I equip it the model stays floating where it was in Studio, and when I click it fires as fast as I can click. I want a server-side 1.5 s cooldown and the tool to actually attach to the hand.

# Answer
Parts of a Tool must be unanchored or they will not follow the character's hand; unanchor them in Studio or when equipped. Handle `Activated` in a server Script inside the tool, where a cooldown cannot be bypassed by the client.

```lua
--!strict
local tool = script.Parent :: Tool

local COOLDOWN_SECONDS = 1.5

local lastUse = -math.huge

local function unanchorParts()
	for _, descendant in tool:GetDescendants() do
		if descendant:IsA("BasePart") then
			descendant.Anchored = false
		end
	end
end

local function onActivated()
	local now = os.clock()
	if now - lastUse < COOLDOWN_SECONDS then
		return
	end
	local character = tool.Parent
	local humanoid = if character then character:FindFirstChildOfClass("Humanoid") else nil
	if not humanoid or humanoid.Health <= 0 then
		return
	end
	lastUse = now
	tool:SetAttribute("Casts", (tool:GetAttribute("Casts") or 0) + 1)
	tool:SetAttribute("ReadyAt", workspace:GetServerTimeNow() + COOLDOWN_SECONDS)
end

tool.Equipped:Connect(unanchorParts)
tool.Activated:Connect(onActivated)
```

- `Tool.Activated` fires on the server too when the tool's owner clicks, so the server script needs no RemoteEvent.
- The cooldown lives in the server script; a client firing faster just gets ignored.
- `ReadyAt` in server time lets a LocalScript draw an accurate cooldown ring with `workspace:GetServerTimeNow()`.
- The tool needs a part named `Handle` (or `RequiresHandle = false`) for it to be held, and every other part must be welded to the Handle (for example with WeldConstraints); unwelded unanchored parts fall away.

# Test
```lua
local tool = Instance.new("Tool")
tool.Name = "WaterSpell"
local handle = Instance.new("Part")
handle.Name = "Handle"
handle.Anchored = true
handle.Parent = tool
script = { Parent = tool }
```

```lua
local tool = script.Parent
local p = __makePlayer(1, "Mage")
local character = __makeCharacter(p)
tool.Parent = character
tool.Equipped:Fire()
check("handle unanchored on equip", tool.Handle.Anchored == false)
tool:Activate()
tool:Activate()
check("second click inside cooldown ignored", tool:GetAttribute("Casts") == 1)
__advance(1.6)
tool:Activate()
check("works after cooldown", tool:GetAttribute("Casts") == 2)
character.Humanoid.Health = 0
__advance(1.6)
tool:Activate()
check("dead holder cannot cast", tool:GetAttribute("Casts") == 2)
```
