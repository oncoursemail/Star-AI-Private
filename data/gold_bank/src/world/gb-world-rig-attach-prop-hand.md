---
id: gb-world-rig-attach-prop-hand
category: rig-prop-alignment
topics: Attachment, WeldConstraint, PivotTo, ToObjectSpace, prop alignment
source: original
---
# Request
I'm giving NPCs a torch model to hold. I weld it to the RightHand but it always ends up at a weird angle or inside the arm because the weld just keeps wherever the torch happened to be. How do I line the torch up with the hand properly before welding?

# Answer
Put an Attachment in the torch where the hand should grip it, then move the whole model so that attachment lands exactly on the hand's `RightGripAttachment` and only then create the WeldConstraint. The offset between the model's pivot and its grip point is measured once with `ToObjectSpace`, so it works for any prop shape.

```lua
--!strict
-- ModuleScript: ServerScriptService.PropAttach
local PropAttach = {}

function PropAttach.attach(prop: Model, gripName: string, target: Attachment): WeldConstraint
	local primary = prop.PrimaryPart
	assert(primary, "prop needs a PrimaryPart")
	local grip = prop:FindFirstChild(gripName, true)
	assert(grip and grip:IsA("Attachment"), string.format("prop has no Attachment named %s", gripName))
	local targetPart = target.Parent
	assert(targetPart and targetPart:IsA("BasePart"), "target attachment must be inside a BasePart")

	-- Where the pivot sits relative to the grip, then place the pivot so the grip meets the target.
	local pivotFromGrip = grip.WorldCFrame:ToObjectSpace(prop:GetPivot())
	prop:PivotTo(target.WorldCFrame:ToWorldSpace(pivotFromGrip))

	for _, descendant in prop:GetDescendants() do
		if descendant:IsA("BasePart") then
			descendant.Anchored = false
			descendant.CanCollide = false
			descendant.Massless = true
		end
	end

	local weld = Instance.new("WeldConstraint")
	weld.Part0 = targetPart
	weld.Part1 = primary
	weld.Parent = primary
	prop.Parent = targetPart.Parent
	return weld
end

return PropAttach
```

Usage: `PropAttach.attach(torchTemplate:Clone(), "Grip", npc.RightHand.RightGripAttachment)`.

- A WeldConstraint freezes the offset that exists when it is created, so the alignment has to happen first; that is the bug in welding first.
- The torch's other parts must already be welded to its PrimaryPart (weld them once in Studio), otherwise only the PrimaryPart follows the hand.
- `Massless` keeps a heavy prop from tipping the NPC over, and `CanCollide = false` stops it from shoving into walls and other characters.
- Rotate the Grip attachment in Studio to change how the torch is held; no code changes needed.

# Test
```lua
local function worldOf(att)
	att.WorldCFrame = att.Parent.CFrame * att.CFrame
end
local rig = __buildRig(Vector3.new(0, 5, 0))
rig.Parent = workspace
local hand = rig.RightHand
local handAtt = Instance.new("Attachment")
handAtt.Name = "RightGripAttachment"
handAtt.CFrame = CFrame.new(0, -0.5, 0)
handAtt.Parent = hand
worldOf(handAtt)

local torch = Instance.new("Model")
local stick = Instance.new("Part")
stick.Position = Vector3.new(30, 0, 0)
stick.Parent = torch
torch.PrimaryPart = stick
local grip = Instance.new("Attachment")
grip.Name = "Grip"
grip.CFrame = CFrame.new(0, -1, 0)
grip.Parent = stick
worldOf(grip)

local weld = item.attach(torch, "Grip", handAtt)
local expected = handAtt.WorldCFrame.Position + Vector3.new(0, 1, 0)
check("grip lands on the hand attachment", (stick.Position - expected).Magnitude < 1e-6)
check("weld joins hand and prop", weld.Part0 == hand and weld.Part1 == stick)
check("prop parts are unanchored and massless", stick.Anchored == false and stick.Massless == true and stick.CanCollide == false)
check("prop is parented to the rig", torch.Parent == rig)
check("missing grip attachment errors", not pcall(item.attach, torch, "Nope", handAtt))
```
