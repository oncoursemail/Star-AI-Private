---
id: gb-world-phys-pet-follow-align
category: physics
topics: AlignPosition, AlignOrientation, pet follow, constraints, Heartbeat
source: original
---
# Request
I have pets that follow the player. I'm setting the pet's CFrame every frame with a lerp and it looks jittery for other players and goes through walls. I heard AlignPosition is better. How do I set that up so the pet floats behind and to the side of the player?

# Answer
Let the physics engine move the pet: an `AlignPosition` and `AlignOrientation` in one-attachment mode pull the pet toward a target that you update on the server a few times per second. The target is an offset in the player's root space, so the pet stays behind and to the side whichever way the player faces; a ray from the player to that point pulls the target back in front of any wall. Network ownership goes to the pet's owner so the motion is smooth for them.

```lua
--!strict
-- ModuleScript: ServerScriptService.PetFollow
local RunService = game:GetService("RunService")

local PetFollow = {}

function PetFollow.targetFor(rootCFrame: CFrame, offset: Vector3): CFrame
	local flatLook = Vector3.new(rootCFrame.LookVector.X, 0, rootCFrame.LookVector.Z)
	local facing = if flatLook.Magnitude > 1e-3 then CFrame.lookAt(rootCFrame.Position, rootCFrame.Position + flatLook) else rootCFrame
	return facing * CFrame.new(offset)
end

function PetFollow.attach(pet: BasePart, owner: Player, offset: Vector3): () -> ()
	local attachment = Instance.new("Attachment")
	attachment.Parent = pet

	local alignPosition = Instance.new("AlignPosition")
	alignPosition.Mode = Enum.PositionAlignmentMode.OneAttachment
	alignPosition.Attachment0 = attachment
	alignPosition.Responsiveness = 25
	alignPosition.MaxForce = 1e5
	alignPosition.Parent = pet

	local alignOrientation = Instance.new("AlignOrientation")
	alignOrientation.Mode = Enum.OrientationAlignmentMode.OneAttachment
	alignOrientation.Attachment0 = attachment
	alignOrientation.Responsiveness = 20
	alignOrientation.Parent = pet

	pet.Anchored = false
	pet.CanCollide = false
	pet.Massless = true
	pet:SetNetworkOwner(owner)

	local params = RaycastParams.new()
	params.FilterType = Enum.RaycastFilterType.Exclude
	params.RespectCanCollide = true

	local sinceUpdate = 0
	local heartbeat = RunService.Heartbeat:Connect(function(dt: number)
		sinceUpdate += dt
		if sinceUpdate < 0.1 then
			return
		end
		sinceUpdate = 0
		local character = owner.Character
		local root = if character then character:FindFirstChild("HumanoidRootPart") else nil
		if root and root:IsA("BasePart") then
			local target = PetFollow.targetFor(root.CFrame, offset)
			params.FilterDescendantsInstances = { character, pet }
			-- Keep the goal on the player's side of any wall between them and the offset point.
			local wall = workspace:Raycast(root.Position, target.Position - root.Position, params)
			alignPosition.Position = if wall then wall.Position + wall.Normal * 1.5 else target.Position
			alignOrientation.CFrame = target
		end
	end)

	return function()
		heartbeat:Disconnect()
		attachment:Destroy()
		alignPosition:Destroy()
		alignOrientation:Destroy()
	end
end

return PetFollow
```

Usage when a pet is equipped: `local detach = PetFollow.attach(petPart, player, Vector3.new(3, 1, 4))` (right, up, behind), and call `detach()` when it is unequipped.

- Constraints are interpolated by the physics engine on every client, which removes the jitter of server-side CFrame writes arriving at network rate.
- Only the target is updated, and only 10 times per second; `Responsiveness` handles the smoothing between updates.
- Flattening the look vector keeps the pet level when the player looks up or down in first person.
- The pet stays non-colliding so it never shoves its owner; the wall ray keeps its goal out of walls instead.
- Giving the owner network ownership makes the pet's motion smooth for them; the target still comes from the server's view of the player, so it trails by about one round trip.

# Test
```lua
local target = item.targetFor(CFrame.new(0, 3, 0), Vector3.new(3, 1, 4))
check("offset is behind and to the right of a forward-facing root", (target.Position - Vector3.new(3, 4, 4)).Magnitude < 1e-9)
local turned = item.targetFor(CFrame.new(0, 3, 0) * CFrame.Angles(0, math.rad(90), 0), Vector3.new(0, 0, 4))
check("offset rotates with the root", (turned.Position - Vector3.new(4, 3, 0)).Magnitude < 1e-6)

local player = __makePlayer(34, "PetOwner")
local character = __makeCharacter(player, Vector3.new(10, 3, 0))
local pet = Instance.new("Part")
pet.Anchored = true
pet.Parent = workspace
local detach = item.attach(pet, player, Vector3.new(3, 1, 4))
local align = pet:FindFirstChildOfClass("AlignPosition")
check("constraints created in one-attachment mode", align ~= nil and align.Mode == Enum.PositionAlignmentMode.OneAttachment and pet:FindFirstChildOfClass("AlignOrientation") ~= nil)
check("pet owned by the player and unanchored", pet:GetNetworkOwner() == player and pet.Anchored == false)
__frames(10)
check("target follows the owner's root", (align.Position - Vector3.new(13, 4, 4)).Magnitude < 1e-6)
local wall = Instance.new("Part")
wall.Anchored = true
wall.Size = Vector3.new(20, 10, 1)
wall.Position = Vector3.new(10, 4, 2)
wall.Parent = workspace
__frames(10)
check("a wall pulls the target back to the player's side", align.Position.Z < 1.5 and align.Position.Z > -0.5)
detach()
check("detach removes the constraints", pet:FindFirstChildOfClass("AlignPosition") == nil)
```
