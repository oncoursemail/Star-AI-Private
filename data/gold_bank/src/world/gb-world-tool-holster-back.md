---
id: gb-world-tool-holster-back
category: tool-attachment
topics: holster, Tool, Unequipped, RigidConstraint, cosmetic copy
source: original
---
# Request
When my rifle is in the backpack I want a copy of it to show slung on the character's back, and hide it again while the rifle is equipped. How would you structure that on the server?

# Answer
Keep a cosmetic clone of the Handle, attached with a RigidConstraint from the torso's `BodyBackAttachment` to a "HolsterAttachment" placed in the Handle. Show it on `Unequipped`, hide it on `Equipped`, and rebuild nothing on each switch except that one clone.

```lua
--!strict
-- ModuleScript: ServerScriptService.Holster
export type Holster = {
	show: () -> boolean,
	hide: () -> (),
	isShown: () -> boolean,
}

local Holster = {}

function Holster.new(character: Model, tool: Tool): Holster
	local copy: Instance? = nil

	local function hide()
		if copy then
			copy:Destroy()
			copy = nil
		end
	end

	local function show(): boolean
		if copy then
			return true
		end
		local torso = character:FindFirstChild("UpperTorso") or character:FindFirstChild("Torso")
		local back = if torso then torso:FindFirstChild("BodyBackAttachment") else nil
		local handle = tool:FindFirstChild("Handle")
		if back == nil or handle == nil or handle:FindFirstChild("HolsterAttachment") == nil then
			return false
		end

		local clone = handle:Clone()
		clone.Name = string.format("Holstered%s", tool.Name)
		clone.Anchored = false
		clone.CanCollide = false
		clone.CanQuery = false
		clone.Massless = true
		for _, child in clone:GetChildren() do
			if child:IsA("Script") or child:IsA("LocalScript") or child:IsA("Sound") then
				child:Destroy()
			end
		end

		local rigid = Instance.new("RigidConstraint")
		rigid.Attachment0 = back
		rigid.Attachment1 = clone:FindFirstChild("HolsterAttachment")
		rigid.Parent = clone
		clone.Parent = character
		copy = clone
		return true
	end

	tool.Equipped:Connect(hide)
	tool.Unequipped:Connect(show)
	character.Destroying:Connect(hide)

	return {
		show = show,
		hide = hide,
		isShown = function(): boolean
			return copy ~= nil
		end,
	}
end

return Holster
```

When the character spawns with the rifle in the backpack, call `Holster.new(character, rifle).show()` once so it starts slung.

- Rotate and move the HolsterAttachment in the Handle to choose the sling angle; the constraint lines the two attachments up exactly.
- Scripts and sounds are stripped from the clone so the cosmetic never runs weapon code or plays fire sounds.
- `CanQuery = false` keeps the slung copy out of hit detection, so shots at the back hit the torso.

# Test
```lua
local player = __makePlayer(8, "Ranger")
local character = __makeCharacter(player)
local torso = Instance.new("Part")
torso.Name = "UpperTorso"
torso.Parent = character
local back = Instance.new("Attachment")
back.Name = "BodyBackAttachment"
back.Parent = torso
local rifle = Instance.new("Tool")
rifle.Name = "Rifle"
local handle = Instance.new("Part")
handle.Name = "Handle"
handle.Parent = rifle
local holsterAtt = Instance.new("Attachment")
holsterAtt.Name = "HolsterAttachment"
holsterAtt.Parent = handle
Instance.new("Sound").Parent = handle

local holster = item.new(character, rifle)
check("shows on the back", holster.show() and character:FindFirstChild("HolsteredRifle") ~= nil)
local slung = character.HolsteredRifle
check("attached by rigid constraint", slung.RigidConstraint.Attachment0 == back and slung:FindFirstChildOfClass("Sound") == nil)
rifle.Equipped:Fire()
check("hidden while equipped", character:FindFirstChild("HolsteredRifle") == nil and not holster.isShown())
rifle.Unequipped:Fire()
check("shown again on unequip", holster.isShown())
holster.show()
local count = 0
for _, child in character:GetChildren() do
	if child.Name == "HolsteredRifle" then
		count += 1
	end
end
check("never duplicated", count == 1)
check("no back attachment means no holster", item.new(Instance.new("Model"), rifle).show() == false)
```
