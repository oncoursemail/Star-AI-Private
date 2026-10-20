---
id: gb-world-tool-weld-parts
category: tool-attachment
topics: WeldConstraint, Tool, Handle, multi-part tool, Massless
source: original
---
# Request
I built a hammer out of 5 parts and put it in a Tool. When I equip it, only the Handle comes with me and the rest falls on the floor (or the whole thing is stuck in the air if I anchor it). How do I fix it?

# Answer
Every non-Handle part needs to be welded to the Handle and nothing may be anchored. Run a welder once on the server when the tool is created: it adds a WeldConstraint per part (skipping parts it already welded, so running it twice is harmless), unanchors everything and makes the extra parts massless so the hammer does not drag the arm down.

```lua
--!strict
-- ModuleScript: ServerScriptService.ToolWelder
local WELD_NAME = "ToolWeld"

local ToolWelder = {}

function ToolWelder.weld(tool: Tool): number
	local handle = tool:FindFirstChild("Handle")
	assert(handle and handle:IsA("BasePart"), "tool needs a BasePart named Handle")
	local created = 0
	for _, part in tool:GetDescendants() do
		if part:IsA("BasePart") and part ~= handle then
			if part:FindFirstChild(WELD_NAME) == nil then
				local weld = Instance.new("WeldConstraint")
				weld.Name = WELD_NAME
				weld.Part0 = handle
				weld.Part1 = part
				weld.Parent = part
				created += 1
			end
			part.Anchored = false
			part.Massless = true
			part.CanCollide = false
		end
	end
	handle.Anchored = false
	return created
end

return ToolWelder
```

Usage, once for each tool template at server start: `ToolWelder.weld(ServerStorage.Tools.Hammer)`.

- A WeldConstraint keeps the offset parts have at the moment it is created, so the hammer keeps the exact shape you built.
- Anchored parts cannot move with the character, which is the "stuck in the air" case; unanchoring the Handle too is part of the fix.
- Leaving `CanCollide` on for decorative parts makes the tool bump into walls and push the player around while swinging.
- Weld the template once, not every clone at equip time; clones copy the welds.

# Test
```lua
local tool = Instance.new("Tool")
local handle = Instance.new("Part")
handle.Name = "Handle"
handle.Anchored = true
handle.Parent = tool
local head = Instance.new("Part")
head.Anchored = true
head.Parent = tool
local model = Instance.new("Model")
model.Parent = tool
local trim1 = Instance.new("Part")
trim1.Parent = model
local trim2 = Instance.new("Part")
trim2.Parent = model

check("welds every non-handle part", item.weld(tool) == 3)
check("running again adds nothing", item.weld(tool) == 0)
local weld = head:FindFirstChild("ToolWeld")
check("weld joins handle and part", weld ~= nil and weld.Part0 == handle and weld.Part1 == head)
check("nothing stays anchored", not handle.Anchored and not head.Anchored and trim1.Massless)
check("tool without a handle errors", not pcall(item.weld, Instance.new("Tool")))
```
