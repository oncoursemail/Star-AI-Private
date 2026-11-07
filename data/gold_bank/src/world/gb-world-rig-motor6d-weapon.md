---
id: gb-world-rig-motor6d-weapon
category: rig-prop-alignment
topics: Motor6D, animated weapon, RequiresHandle, C0 C1, Tool
source: original
---
# Request
I animated a sword spin where the sword itself rotates in the hand, but in game the sword stays stiff because the tool's grip is a weld. How do people make tools that animations can move?

# Answer
Join the weapon to the hand with a Motor6D instead of the automatic grip weld. Name the weapon part something other than "Handle" and turn `RequiresHandle` off so Roblox does not create its own RightGrip weld, then create the Motor6D on the server when the tool is equipped. Animations that key that motor will now move the sword.

```lua
--!strict
-- ModuleScript: ServerScriptService.WeaponMotor
local MOTOR_NAME = "WeaponMotor"

local WeaponMotor = {}

function WeaponMotor.connect(character: Model, weaponPart: BasePart): Motor6D?
	local hand = character:FindFirstChild("RightHand")
	if hand == nil then
		return nil
	end
	local old = hand:FindFirstChild(MOTOR_NAME)
	if old then
		old:Destroy()
	end
	local handGrip = hand:FindFirstChild("RightGripAttachment")
	local weaponGrip = weaponPart:FindFirstChild("GripAttachment")

	local motor = Instance.new("Motor6D")
	motor.Name = MOTOR_NAME
	motor.Part0 = hand
	motor.Part1 = weaponPart
	motor.C0 = if handGrip then handGrip.CFrame else CFrame.identity
	motor.C1 = if weaponGrip then weaponGrip.CFrame else CFrame.identity
	motor.Parent = hand
	return motor
end

function WeaponMotor.disconnect(character: Model)
	local hand = character:FindFirstChild("RightHand")
	local motor = if hand then hand:FindFirstChild(MOTOR_NAME) else nil
	if motor then
		motor:Destroy()
	end
end

return WeaponMotor
```

Server Script inside the tool (the sword part is named "BodyAttach"):

```lua
--!strict
local ServerScriptService = game:GetService("ServerScriptService")
local WeaponMotor = require(ServerScriptService:WaitForChild("WeaponMotor"))

local tool = script.Parent
tool.RequiresHandle = false
local blade = tool:WaitForChild("BodyAttach")
-- Remembered on equip: by the time Unequipped fires the tool is already back in the Backpack.
local holder: Model? = nil

tool.Equipped:Connect(function()
	local character = tool.Parent
	if character and character:IsA("Model") then
		holder = character
		WeaponMotor.connect(character, blade)
	end
end)

tool.Unequipped:Connect(function()
	if holder then
		WeaponMotor.disconnect(holder)
		holder = nil
	end
end)
```

- When animating, add the same Motor6D (Part0 RightHand, Part1 BodyAttach, same name) to the rig in the Animation Editor, otherwise the editor has no joint to key.
- C0/C1 come from attachments so the rest pose matches the grip you set up in Studio, and the animation only adds rotation on top.
- Creating the motor on the server makes it replicate to everyone, which the animation needs to show the sword moving for other players.
- The blade must be unanchored and its other parts welded to BodyAttach.

# Test
```lua
local player = __makePlayer(5, "Spinner")
local character = __makeCharacter(player)
local handGrip = Instance.new("Attachment")
handGrip.Name = "RightGripAttachment"
handGrip.CFrame = CFrame.new(0, -0.4, 0)
handGrip.Parent = character.RightHand
local blade = Instance.new("Part")
local bladeGrip = Instance.new("Attachment")
bladeGrip.Name = "GripAttachment"
bladeGrip.CFrame = CFrame.new(0, -2, 0)
bladeGrip.Parent = blade

local motor = item.connect(character, blade)
check("motor joins hand and blade", motor ~= nil and motor.Part0 == character.RightHand and motor.Part1 == blade)
check("C0 and C1 come from the attachments", motor.C0 == handGrip.CFrame and motor.C1 == bladeGrip.CFrame)
item.connect(character, blade)
local count = 0
for _, child in character.RightHand:GetChildren() do
	if child.Name == "WeaponMotor" then
		count += 1
	end
end
check("reconnecting replaces the old motor", count == 1)
item.disconnect(character)
check("disconnect removes the motor", character.RightHand:FindFirstChild("WeaponMotor") == nil)
check("no hand means no motor", item.connect(Instance.new("Model"), blade) == nil)
```
