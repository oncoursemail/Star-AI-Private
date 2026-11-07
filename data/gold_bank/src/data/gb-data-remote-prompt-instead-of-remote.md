---
id: gb-data-remote-prompt-instead-of-remote
category: remote-security
topics: ProximityPrompt, remove RemoteEvent, server event, door, key item
source: original
---
# Request
My vault door opens when the client presses E near it: a LocalScript checks distance and fires `OpenVault:FireServer()`. I keep adding checks to the remote. Is there a simpler way?

# Answer
Yes: delete the remote. A ProximityPrompt's `Triggered` event fires on the server with the player who used it, so the whole interaction can live in a server Script with nothing for an exploiter to call. Keep the server rules anyway (key attribute, distance, a cooldown), because prompt events are still caused by client input.

```lua
--!strict
-- Script inside the vault door model (a Model with a Door part and a ProximityPrompt in it)
local door = script.Parent:WaitForChild("Door") :: BasePart
local prompt = door:WaitForChild("ProximityPrompt") :: ProximityPrompt

local OPEN_SECONDS = 4
local MAX_DISTANCE = prompt.MaxActivationDistance + 4 -- slack for latency
local isOpen = false

local function closeDoor()
	isOpen = false
	door.CanCollide = true
	door.Transparency = 0
	prompt.Enabled = true
end

local function onTriggered(player: Player)
	if isOpen or player:GetAttribute("HasVaultKey") ~= true then
		return
	end
	local character = player.Character
	local root: BasePart? = if character then character:FindFirstChild("HumanoidRootPart") else nil
	if root == nil or (root.Position - door.Position).Magnitude > MAX_DISTANCE then
		return
	end
	isOpen = true
	prompt.Enabled = false
	door.CanCollide = false
	door.Transparency = 0.7
	task.delay(OPEN_SECONDS, closeDoor)
end

prompt.Triggered:Connect(onTriggered)
```

- `HasVaultKey` is set by server code (quest reward, purchase); the prompt can be visible to everyone and still only open for key holders.
- Disabling the prompt while the door is open doubles as the cooldown and gives players visual feedback.
- The same swap works for shops, chests and NPC talks: if the client is only saying "I pressed the button here", a prompt (or ClickDetector) on the server is less code and less attack surface.

# Test
```lua
local model = Instance.new("Model")
local doorPart = Instance.new("Part")
doorPart.Name = "Door"
doorPart.Position = Vector3.new(0, 3, 0)
doorPart.Parent = model
local p = Instance.new("ProximityPrompt")
p.Parent = doorPart
model.Parent = workspace
script.Parent = model
```
```lua
local door = workspace:FindFirstChildOfClass("Model").Door
local prompt = door.ProximityPrompt
local keyHolder = __makePlayer(1, "KeyHolder")
local noKey = __makePlayer(2, "NoKey")
__makeCharacter(keyHolder, Vector3.new(0, 3, 6))
__makeCharacter(noKey, Vector3.new(0, 3, 6))
keyHolder:SetAttribute("HasVaultKey", true)

prompt.Triggered:Fire(noKey)
check("players without the key cannot open it", door.CanCollide == true)
prompt.Triggered:Fire(keyHolder)
check("key holder opens the door", door.CanCollide == false and prompt.Enabled == false)
__advance(4.1)
check("door closes again by itself", door.CanCollide == true and prompt.Enabled == true)

keyHolder.Character.HumanoidRootPart.Position = Vector3.new(0, 3, 200)
prompt.Triggered:Fire(keyHolder)
check("triggers from far away are refused", door.CanCollide == true)
```
