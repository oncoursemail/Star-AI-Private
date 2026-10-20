---
id: gb-world-game-keycard-door
category: gameplay-systems
topics: ProximityPrompt, locked door, keycard, server validation, TweenService
source: original
---
# Request
I have a door with a ProximityPrompt that should only open if the player has the "Keycard" tool. Right now a LocalScript checks the backpack and opens the door, so it only opens for that player and exploiters can just delete the door. How should the door work?

# Answer
Handle `Triggered` on the server: the prompt's event already tells you which player used it, and the server checks they are alive, within range and own the keycard (equipped or in the backpack). The door then slides open with a tween that replicates to everyone and closes itself after a delay; triggers while it is moving are ignored.

```lua
--!strict
-- ModuleScript: ServerScriptService.KeycardDoor
local TweenService = game:GetService("TweenService")

export type Door = { isOpen: () -> boolean }

local KeycardDoor = {}

function KeycardDoor.hasKey(player: Player, keyName: string): boolean
	local character = player.Character
	local backpack = player:FindFirstChildOfClass("Backpack")
	return (character ~= nil and character:FindFirstChild(keyName) ~= nil)
		or (backpack ~= nil and backpack:FindFirstChild(keyName) ~= nil)
end

function KeycardDoor.bind(door: BasePart, prompt: ProximityPrompt, keyName: string, openOffset: Vector3, stayOpen: number): Door
	local closedCFrame = door.CFrame
	local info = TweenInfo.new(0.6, Enum.EasingStyle.Quad, Enum.EasingDirection.Out)
	local openTween = TweenService:Create(door, info, { CFrame = closedCFrame + openOffset })
	local closeTween = TweenService:Create(door, info, { CFrame = closedCFrame })
	local busy = false
	local open = false

	prompt.Triggered:Connect(function(player: Player)
		if busy then
			return
		end
		local character = player.Character
		local humanoid = if character then character:FindFirstChildOfClass("Humanoid") else nil
		if humanoid == nil or humanoid.Health <= 0 then
			return
		end
		if player:DistanceFromCharacter(door.Position) > prompt.MaxActivationDistance + 4 then
			return
		end
		if not KeycardDoor.hasKey(player, keyName) then
			prompt.ObjectText = "Keycard required"
			return
		end
		busy = true
		open = true
		prompt.Enabled = false
		openTween:Play()
		openTween.Completed:Wait()
		task.wait(stayOpen)
		closeTween:Play()
		closeTween.Completed:Wait()
		open = false
		prompt.Enabled = true
		busy = false
	end)

	return {
		isOpen = function(): boolean
			return open
		end,
	}
end

return KeycardDoor
```

- `Triggered` runs on the server with the real player who used the prompt, so the key check cannot be skipped by a modified client.
- The distance re-check (with a small margin for latency) rejects prompts fired by exploits from across the map.
- Disabling the prompt while the door moves hides it for everyone and the `busy` flag ignores any queued triggers.
- The door part should be Anchored; tweening an anchored part's CFrame moves it for all players, and the open state is visible to everyone.

# Test
```lua
local door = Instance.new("Part")
door.Anchored = true
door.Size = Vector3.new(6, 10, 1)
door.Position = Vector3.new(0, 5, 0)
door.Parent = workspace
local prompt = Instance.new("ProximityPrompt")
prompt.Parent = door
local handle = item.bind(door, prompt, "Keycard", Vector3.new(0, 11, 0), 3)

local guest = __makePlayer(141, "Guest")
__makeCharacter(guest, Vector3.new(0, 3, 5))
prompt.Triggered:Fire(guest)
__advance(1)
check("no keycard keeps it shut", not handle.isOpen() and door.Position == Vector3.new(0, 5, 0) and prompt.ObjectText == "Keycard required")

local guard = __makePlayer(142, "Guard")
__makeCharacter(guard, Vector3.new(0, 3, 6))
local card = Instance.new("Tool")
card.Name = "Keycard"
card.Parent = guard.Backpack
prompt.Triggered:Fire(guard)
__advance(0.7)
check("keycard in the backpack opens it for everyone", handle.isOpen() and door.Position == Vector3.new(0, 16, 0) and prompt.Enabled == false)
prompt.Triggered:Fire(guard)
__advance(3.7)
check("closes on its own after the delay", not handle.isOpen() and door.Position == Vector3.new(0, 5, 0) and prompt.Enabled)

local far = __makePlayer(143, "Far")
__makeCharacter(far, Vector3.new(0, 3, 200))
Instance.new("Tool").Parent = far.Backpack
far.Backpack.Tool.Name = "Keycard"
prompt.Triggered:Fire(far)
__advance(1)
check("triggers from far away are rejected", not handle.isOpen())
```
