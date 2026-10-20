---
id: gb-world-tool-offhand-weld
category: tool-attachment
topics: offhand, Weld C0 C1, LeftGripAttachment, shield, Tool attribute
source: original
---
# Request
Tools only go in the right hand. My sword-and-shield tool should also put a shield on the left hand while equipped. The shield model lives in ServerStorage and the tool has an attribute `Offhand = "RoundShield"`. Can you write the server part?

# Answer
On equip, clone the named model from a fixed ServerStorage folder and hold it with a `Weld` whose C0/C1 come from the hand's `LeftGripAttachment` and the shield's grip attachment, so it snaps into place immediately with no physics settling. Remove it on unequip and when the humanoid dies. The attribute is only used as a lookup key inside that folder.

```lua
--!strict
-- ModuleScript: ServerScriptService.Offhand
local ServerStorage = game:GetService("ServerStorage")

local Offhand = {}

function Offhand.bind(tool: Tool, library: Instance?): () -> ()
	local folder = library or ServerStorage:WaitForChild("OffhandItems")
	local equipped: Instance? = nil
	local diedConnection: RBXScriptConnection? = nil

	local function remove()
		if diedConnection then
			diedConnection:Disconnect()
			diedConnection = nil
		end
		if equipped then
			equipped:Destroy()
			equipped = nil
		end
	end

	local function onEquipped()
		remove()
		local name = tool:GetAttribute("Offhand")
		local template = if type(name) == "string" then folder:FindFirstChild(name) else nil
		local character = tool.Parent
		local hand = if character then character:FindFirstChild("LeftHand") else nil
		local handGrip = if hand then hand:FindFirstChild("LeftGripAttachment") else nil
		local humanoid = if character then character:FindFirstChildOfClass("Humanoid") else nil
		if template == nil or not template:IsA("Model") or handGrip == nil or humanoid == nil then
			return
		end

		local shield = template:Clone()
		local primary = shield.PrimaryPart
		local shieldGrip = if primary then primary:FindFirstChild("Grip") else nil
		if primary == nil or shieldGrip == nil then
			shield:Destroy()
			return
		end
		for _, part in shield:GetDescendants() do
			if part:IsA("BasePart") then
				part.Anchored = false
				part.Massless = true
			end
		end
		local weld = Instance.new("Weld")
		weld.Part0 = hand
		weld.Part1 = primary
		weld.C0 = handGrip.CFrame
		weld.C1 = shieldGrip.CFrame
		weld.Parent = primary
		shield.Name = "Offhand"
		shield.Parent = character
		equipped = shield
		diedConnection = humanoid.Died:Connect(remove)
	end

	local equippedConnection = tool.Equipped:Connect(onEquipped)
	local unequippedConnection = tool.Unequipped:Connect(remove)
	return function()
		remove()
		equippedConnection:Disconnect()
		unequippedConnection:Disconnect()
	end
end

return Offhand
```

- The attribute picks a model by name inside one trusted folder, so even a tampered attribute could only choose another shield, never an arbitrary instance.
- A Weld with C0/C1 places the shield in the same frame it is created; a WeldConstraint would weld wherever the clone happened to spawn.
- The shield's parts must be welded to its PrimaryPart in Studio, and `Massless` stops it from unbalancing the character.

# Test
```lua
local library = Instance.new("Folder")
local template = Instance.new("Model")
template.Name = "RoundShield"
local plate = Instance.new("Part")
plate.Parent = template
template.PrimaryPart = plate
local grip = Instance.new("Attachment")
grip.Name = "Grip"
grip.CFrame = CFrame.new(0, 0, 0.3)
grip.Parent = plate
template.Parent = library

local player = __makePlayer(9, "Knight")
local character = __makeCharacter(player)
local leftHand = Instance.new("Part")
leftHand.Name = "LeftHand"
leftHand.Parent = character
local handGrip = Instance.new("Attachment")
handGrip.Name = "LeftGripAttachment"
handGrip.Parent = leftHand

local tool = Instance.new("Tool")
tool:SetAttribute("Offhand", "RoundShield")
local unbind = item.bind(tool, library)
tool.Parent = character
tool.Equipped:Fire()
local shield = character:FindFirstChild("Offhand")
local weld = shield and shield.PrimaryPart:FindFirstChildOfClass("Weld")
check("shield welded to the left hand", weld ~= nil and weld.Part0 == leftHand and weld.C1 == grip.CFrame)
tool.Unequipped:Fire()
check("removed on unequip", character:FindFirstChild("Offhand") == nil)
tool.Equipped:Fire()
character.Humanoid.Health = 0
check("removed on death", character:FindFirstChild("Offhand") == nil)
tool:SetAttribute("Offhand", "Nonexistent")
character.Humanoid.Health = 100
tool.Equipped:Fire()
check("unknown offhand name does nothing", character:FindFirstChild("Offhand") == nil)
unbind()
tool:SetAttribute("Offhand", "RoundShield")
tool.Equipped:Fire()
check("unbind stops equipping", character:FindFirstChild("Offhand") == nil)
```
