---
id: gb-world-anim-footstep-markers
category: animation
topics: footsteps, GetMarkerReachedSignal, raycast material, Sound, client
source: original
---
# Request
How do I play footstep sounds that match the floor (grass, wood, concrete) exactly when the foot lands in my custom run animation? I put a "Footstep" marker on each foot plant.

# Answer
Listen to the marker on the client, cast a short ray down from the root to read the floor material, and play the sound named after that material (falling back to "Default"). No sound plays when the ray finds nothing, so jumping and falling stay silent.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Footsteps
local RAY_LENGTH = 5

local Footsteps = {}

function Footsteps.attach(track: AnimationTrack, character: Model, sounds: Instance): RBXScriptConnection
	local root = character:FindFirstChild("HumanoidRootPart")
	assert(root and root:IsA("BasePart"), "character needs a HumanoidRootPart")

	local params = RaycastParams.new()
	params.FilterType = Enum.RaycastFilterType.Exclude
	params.FilterDescendantsInstances = { character }
	local random = Random.new()

	return track:GetMarkerReachedSignal("Footstep"):Connect(function()
		local result = workspace:Raycast(root.Position, Vector3.new(0, -RAY_LENGTH, 0), params)
		if result == nil then
			return
		end
		local sound = sounds:FindFirstChild(result.Material.Name) or sounds:FindFirstChild("Default")
		if sound and sound:IsA("Sound") then
			sound.PlaybackSpeed = random:NextNumber(0.92, 1.08)
			sound:Play()
		end
	end)
end

return Footsteps
```

In the LocalScript that plays the run animation:

```lua
--!strict
local Players = game:GetService("Players")
local Footsteps = require(game:GetService("ReplicatedStorage"):WaitForChild("Footsteps"))

local character = Players.LocalPlayer.Character or Players.LocalPlayer.CharacterAdded:Wait()
local animator = character:WaitForChild("Humanoid"):WaitForChild("Animator")
local runTrack = animator:LoadAnimation(script:WaitForChild("Run"))
-- FootstepSounds is an Attachment in the root: a Sound is only positional when its parent is a BasePart or Attachment.
local sounds = character:WaitForChild("HumanoidRootPart"):WaitForChild("FootstepSounds")

local connection = Footsteps.attach(runTrack, character, sounds)
character.Destroying:Connect(function()
	connection:Disconnect()
end)
```

- Name the Sound children after `Enum.Material` names ("Grass", "WoodPlanks", "Concrete") plus one "Default"; adding a surface is just adding a Sound.
- The character is excluded from the ray so the legs never count as the floor.
- Small random `PlaybackSpeed` changes stop the repeated sample from sounding mechanical.
- Keep the Sounds under an Attachment (or the root part itself), not a Folder: under a Folder they play at full volume everywhere instead of fading with distance.

# Test
```lua
local floor = Instance.new("Part")
floor.Anchored = true
floor.Size = Vector3.new(40, 1, 40)
floor.Position = Vector3.new(0, 0, 0)
floor.Material = Enum.Material.Grass
floor.Parent = workspace
local player = __makePlayer(3, "Walker")
local character = __makeCharacter(player, Vector3.new(0, 3, 0))
local sounds = Instance.new("Folder")
local grass = Instance.new("Sound")
grass.Name = "Grass"
grass.Parent = sounds
local default = Instance.new("Sound")
default.Name = "Default"
default.Parent = sounds
local track = character.Humanoid.Animator:LoadAnimation(Instance.new("Animation"))
local connection = item.attach(track, character, sounds)
local marker = track:GetMarkerReachedSignal("Footstep")

marker:Fire()
check("grass floor plays the grass sound", grass.__plays == 1 and default.__plays == nil)
floor.Material = Enum.Material.Concrete
marker:Fire()
check("unknown material falls back to Default", default.__plays == 1)
character.HumanoidRootPart.Position = Vector3.new(0, 30, 0)
marker:Fire()
check("no sound in the air", grass.__plays == 1 and default.__plays == 1)
check("pitch is varied within range", grass.PlaybackSpeed >= 0.92 and grass.PlaybackSpeed <= 1.08)
connection:Disconnect()
```
