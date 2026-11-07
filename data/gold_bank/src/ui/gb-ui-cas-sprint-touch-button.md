---
id: gb-ui-cas-sprint-touch-button
category: ui-interaction
topics: ContextActionService, touch button, sprint toggle, mobile, gamepad
source: original
---
# Request
My sprint works with Left Shift on PC, but mobile players have no way to sprint and console players can't either. I'd rather not build a separate on-screen button myself. What's the cleanest way?

# Answer
Bind the action with ContextActionService and pass `true` for `createTouchButton`: one handler then serves Left Shift, the controller's left stick click and an automatic mobile button. Make it a toggle, because holding a touch button while steering is awkward, and unbind when the character goes away.

```lua
--!strict
-- ModuleScript: StarterPlayerScripts.Sprint
local ContextActionService = game:GetService("ContextActionService")

local Sprint = {}

local ACTION = "SprintToggle"
local WALK_SPEED = 16
local SPRINT_SPEED = 24

function Sprint.bind(humanoid: Humanoid): () -> ()
	local sprinting = false

	local function apply()
		humanoid.WalkSpeed = if sprinting then SPRINT_SPEED else WALK_SPEED
		ContextActionService:SetTitle(ACTION, if sprinting then "Walk" else "Run")
	end

	local function onAction(_name: string, state: Enum.UserInputState, _input: InputObject): Enum.ContextActionResult
		if state ~= Enum.UserInputState.Begin then
			return Enum.ContextActionResult.Pass
		end
		sprinting = not sprinting
		apply()
		return Enum.ContextActionResult.Sink
	end

	ContextActionService:BindAction(ACTION, onAction, true, Enum.KeyCode.LeftShift, Enum.KeyCode.ButtonL3)
	ContextActionService:SetPosition(ACTION, UDim2.new(1, -150, 1, -150))
	apply()

	local diedConnection: RBXScriptConnection? = nil
	local function unbind()
		if diedConnection then
			diedConnection:Disconnect()
			diedConnection = nil
		end
		ContextActionService:UnbindAction(ACTION)
		sprinting = false
	end
	diedConnection = humanoid.Died:Connect(unbind)

	return unbind
end

return Sprint
```

```lua
--!strict
-- LocalScript: StarterPlayerScripts.SprintClient
local Players = game:GetService("Players")
local Sprint = require(script.Parent:WaitForChild("Sprint"))

local player = Players.LocalPlayer

local function onCharacter(character: Model)
	Sprint.bind(character:WaitForChild("Humanoid") :: Humanoid)
end

if player.Character then
	onCharacter(player.Character)
end
player.CharacterAdded:Connect(onCharacter)
```

- The touch button only appears on touch devices; PC and console players never see it.
- The WalkSpeed property itself does not replicate, but the client simulates its own character, so everyone sees the faster movement; that also means the server cannot trust it, so speed the player pays for must be set and checked on the server.
- Rebinding the same action name replaces the old binding, so a respawn never leaves two handlers.

# Test
```lua
local CAS = game:GetService("ContextActionService")
local player = __makePlayer(1, "Runner")
local character = __makeCharacter(player)
local humanoid = character.Humanoid
local unbind = item.bind(humanoid)
local bound = CAS.__bound.SprintToggle
check("bound for keyboard and gamepad", bound ~= nil and bound.inputs[1] == Enum.KeyCode.LeftShift and bound.inputs[2] == Enum.KeyCode.ButtonL3)
check("starts walking", humanoid.WalkSpeed == 16)
bound.fn("SprintToggle", Enum.UserInputState.Begin, {})
check("press toggles sprint on", humanoid.WalkSpeed == 24)
check("release is ignored", bound.fn("SprintToggle", Enum.UserInputState.End, {}) == Enum.ContextActionResult.Pass and humanoid.WalkSpeed == 24)
bound.fn("SprintToggle", Enum.UserInputState.Begin, {})
check("second press walks again", humanoid.WalkSpeed == 16)
humanoid.Health = 0
check("dying unbinds the action", CAS.__bound.SprintToggle == nil)
unbind()
check("unbind is safe to call twice", CAS.__bound.SprintToggle == nil)
```
