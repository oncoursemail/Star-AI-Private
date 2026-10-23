---
id: gb-eng-debug-stale-character-ref
category: engineering-debugging
topics: respawn, Character, stale reference, CharacterAdded, LocalScript
source: original
---
# Request
My sprint key works until I die. After respawning, pressing Shift does nothing (no error either). The LocalScript is in StarterPlayerScripts:

```lua
local player = game.Players.LocalPlayer
local character = player.Character or player.CharacterAdded:Wait()
local humanoid = character:WaitForChild("Humanoid")

game:GetService("UserInputService").InputBegan:Connect(function(input, processed)
	if not processed and input.KeyCode == Enum.KeyCode.LeftShift then
		humanoid.WalkSpeed = 28
	end
end)
```

# Answer
Scripts in StarterPlayerScripts run once per session, not once per life. `character` and `humanoid` are captured at startup, so after a respawn the script keeps setting WalkSpeed on the old, destroyed Humanoid. Track the current humanoid in a variable that a `CharacterAdded` handler updates, and read it at the moment of the key press.

```lua
--!strict
-- ModuleScript: StarterPlayer.StarterPlayerScripts.Sprint (required by a LocalScript)
local SPRINT_SPEED = 28
local WALK_SPEED = 16

local Sprint = {}

function Sprint.start(player: Player, input: any): () -> ()
	local humanoid: Humanoid? = nil

	local function onCharacter(character: Model)
		humanoid = nil
		local h = character:WaitForChild("Humanoid", 10)
		if h and h:IsA("Humanoid") and character == player.Character then
			humanoid = h
		end
	end

	local connections = {
		player.CharacterAdded:Connect(onCharacter),
		input.InputBegan:Connect(function(key: InputObject, processed: boolean)
			if not processed and key.KeyCode == Enum.KeyCode.LeftShift and humanoid then
				humanoid.WalkSpeed = SPRINT_SPEED
			end
		end),
		input.InputEnded:Connect(function(key: InputObject)
			if key.KeyCode == Enum.KeyCode.LeftShift and humanoid then
				humanoid.WalkSpeed = WALK_SPEED
			end
		end),
	}
	if player.Character then
		task.spawn(onCharacter, player.Character)
	end

	return function()
		for _, connection in connections do
			connection:Disconnect()
		end
	end
end

return Sprint
```

- LocalScript: `require(script.Parent.Sprint).start(game:GetService("Players").LocalPlayer, game:GetService("UserInputService"))`.
- The alternative is a LocalScript in StarterCharacterScripts, which is copied into every new character and so naturally starts fresh each life; use that for code that is only about the current body.
- `character == player.Character` after the wait drops a humanoid that belongs to a character that already respawned again while we were waiting.

# Test
```lua
__setClient(true)
local p = __makePlayer(1, "Runner")
__makeCharacter(p)
local uis = game:GetService("UserInputService")
local stop = item.start(p, uis)
local shift = { KeyCode = Enum.KeyCode.LeftShift }
uis.InputBegan:Fire(shift, false)
local firstHumanoid = p.Character:FindFirstChildOfClass("Humanoid")
check("sprint on first life", firstHumanoid.WalkSpeed == 28)
uis.InputEnded:Fire(shift)
check("walk again on release", firstHumanoid.WalkSpeed == 16)
__makeCharacter(p)
uis.InputBegan:Fire(shift, false)
local secondHumanoid = p.Character:FindFirstChildOfClass("Humanoid")
check("sprint works after respawn", secondHumanoid.WalkSpeed == 28 and secondHumanoid ~= firstHumanoid)
uis.InputEnded:Fire(shift)
uis.InputBegan:Fire(shift, true)
check("ignored when typing in chat", secondHumanoid.WalkSpeed == 16)
stop()
uis.InputBegan:Fire(shift, false)
check("stop disconnects", secondHumanoid.WalkSpeed == 16)
```
