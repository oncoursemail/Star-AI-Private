---
id: gb-world-rig-rigid-back-item
category: rig-prop-alignment
topics: RigidConstraint, BodyBackAttachment, cosmetic, Massless, character
source: original
---
# Request
I want to put a cosmetic jetpack on the player's back when they spawn. What's the cleanest way to attach a multi-part model to the character so it follows every animation and doesn't mess with movement?

# Answer
Attach it attachment-to-attachment with a `RigidConstraint`: the jetpack's mount attachment snaps onto the character's `BodyBackAttachment`, so there is no CFrame maths at all. Make every part massless and non-colliding so the character controller does not feel the extra parts.

```lua
--!strict
-- ModuleScript: ServerScriptService.BackItem
local BackItem = {}

function BackItem.attach(character: Model, template: Model, mountName: string): Model?
	local torso = character:FindFirstChild("UpperTorso") or character:FindFirstChild("Torso")
	local bodyBack = if torso then torso:FindFirstChild("BodyBackAttachment") else nil
	if bodyBack == nil then
		return nil
	end

	local old = character:FindFirstChild(template.Name)
	if old then
		old:Destroy()
	end

	local backItem = template:Clone()
	local mount = backItem:FindFirstChild(mountName, true)
	assert(mount and mount:IsA("Attachment"), string.format("template needs an Attachment named %s", mountName))

	for _, descendant in backItem:GetDescendants() do
		if descendant:IsA("BasePart") then
			descendant.Anchored = false
			descendant.CanCollide = false
			descendant.CanTouch = false
			descendant.CanQuery = false
			descendant.Massless = true
		end
	end

	local rigid = Instance.new("RigidConstraint")
	rigid.Attachment0 = bodyBack
	rigid.Attachment1 = mount
	rigid.Parent = mount.Parent
	backItem.Parent = character
	return backItem
end

return BackItem
```

Hooking it to spawns on the server:

```lua
--!strict
local Players = game:GetService("Players")
local ServerStorage = game:GetService("ServerStorage")
local BackItem = require(script.Parent:WaitForChild("BackItem"))

local jetpack = ServerStorage:WaitForChild("Jetpack")

local function onCharacter(character: Model)
	character:WaitForChild("Humanoid")
	BackItem.attach(character, jetpack, "Mount")
end

local function onPlayer(player: Player)
	player.CharacterAdded:Connect(onCharacter)
	if player.Character then
		onCharacter(player.Character)
	end
end

Players.PlayerAdded:Connect(onPlayer)
for _, player in Players:GetPlayers() do
	onPlayer(player)
end
```

- The jetpack's own parts must be welded to the part holding the Mount attachment; the constraint only holds that one part.
- `CanQuery = false` keeps raycasts and hitboxes from treating the cosmetic as part of the body, which matters for headshot and hit checks.
- Supporting R6 just needs a `BodyBackAttachment` on the Torso, which is why the lookup tries both.

# Test
```lua
local player = __makePlayer(6, "Flyer")
local character = __makeCharacter(player)
local torso = Instance.new("Part")
torso.Name = "UpperTorso"
torso.Parent = character
local back = Instance.new("Attachment")
back.Name = "BodyBackAttachment"
back.Parent = torso

local template = Instance.new("Model")
template.Name = "Jetpack"
local body = Instance.new("Part")
body.Anchored = true
body.Parent = template
local mount = Instance.new("Attachment")
mount.Name = "Mount"
mount.Parent = body

local worn = item.attach(character, template, "Mount")
local rigid = worn and worn:FindFirstChildWhichIsA("RigidConstraint", true)
check("rigid constraint joins back and mount", rigid ~= nil and rigid.Attachment0 == back and rigid.Attachment1.Name == "Mount")
check("parts are massless and non-colliding", worn.Part.Massless and not worn.Part.CanCollide and not worn.Part.Anchored)
item.attach(character, template, "Mount")
local copies = 0
for _, child in character:GetChildren() do
	if child.Name == "Jetpack" then
		copies += 1
	end
end
check("re-attaching keeps one copy", copies == 1)
check("no back attachment returns nil", item.attach(Instance.new("Model"), template, "Mount") == nil)
check("template is untouched", template.Parent == nil and body.Anchored == true)
```
