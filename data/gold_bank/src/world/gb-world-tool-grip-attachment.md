---
id: gb-world-tool-grip-attachment
category: tool-attachment
topics: Tool.Grip, Attachment, grip offset, Handle, sword
source: original
---
# Request
My sword is held sideways and too low. I've been guessing numbers for `tool.GripPos` and `GripForward` for an hour. Is there a less painful way to set the grip, especially since I have 12 sword skins with different handles?

# Answer
`Tool.Grip` is just the Handle-space CFrame that gets snapped to the hand's grip attachment. Put an Attachment named "GripPoint" in each Handle, position and rotate it visually in Studio where the palm should be, and copy its CFrame into `Grip` when the tool loads. Each skin carries its own grip, no numbers to guess.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.ToolGrip
local ToolGrip = {}

function ToolGrip.applyFromAttachment(tool: Tool, attachmentName: string, correction: CFrame?): boolean
	local handle = tool:FindFirstChild("Handle")
	local point = if handle then handle:FindFirstChild(attachmentName) else nil
	if point == nil or not point:IsA("Attachment") then
		return false
	end
	tool.Grip = if correction then point.CFrame:ToWorldSpace(correction) else point.CFrame
	return true
end

return ToolGrip
```

Applying it to every tool in a folder from a server Script, before tools are handed out:

```lua
--!strict
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerStorage = game:GetService("ServerStorage")
local ToolGrip = require(ReplicatedStorage:WaitForChild("ToolGrip"))

for _, tool in ServerStorage:WaitForChild("Swords"):GetChildren() do
	if tool:IsA("Tool") and not ToolGrip.applyFromAttachment(tool, "GripPoint") then
		warn(string.format("%s has no Handle.GripPoint attachment; keeping its default grip", tool.Name))
	end
end
```

- Setting `Grip` once per tool is enough; it replicates and is used every time the tool is equipped.
- The optional `correction` handles a whole batch of handles modelled on a different axis, e.g. `CFrame.Angles(0, math.rad(90), 0)`.
- `Grip` is copied once, so moving GripPoint during a playtest changes nothing; tune it in edit mode (or edit the equipped tool's `Grip` live and move GripPoint to match afterwards).

# Test
```lua
local tool = Instance.new("Tool")
local handle = Instance.new("Part")
handle.Name = "Handle"
handle.Parent = tool
local point = Instance.new("Attachment")
point.Name = "GripPoint"
point.CFrame = CFrame.new(0, -1.5, 0) * CFrame.Angles(0, 0, math.rad(90))
point.Parent = handle

check("grip copied from the attachment", item.applyFromAttachment(tool, "GripPoint") and tool.Grip == point.CFrame)
local turn = CFrame.Angles(0, math.rad(90), 0)
item.applyFromAttachment(tool, "GripPoint", turn)
check("correction is applied in attachment space", (tool.Grip.Position - point.CFrame.Position).Magnitude < 1e-6 and tool.Grip ~= point.CFrame)
check("missing attachment returns false", item.applyFromAttachment(tool, "Missing") == false)
check("missing handle returns false", item.applyFromAttachment(Instance.new("Tool"), "GripPoint") == false)
```
