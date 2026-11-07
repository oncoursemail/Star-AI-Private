---
id: gb-world-game-double-jump
category: gameplay-systems
topics: double jump, JumpRequest, HumanoidStateType, client movement, air jumps
source: original
---
# Request
How do I add a double jump? I tried listening to the space key and setting `Humanoid.Jump = true` again in the air, but nothing happens, and on mobile there's no space key anyway.

# Answer
`Humanoid.Jump` is ignored while airborne, so force the jump state instead: on `UserInputService.JumpRequest` (which covers keyboard, gamepad and the mobile jump button), if the character is falling and still has air jumps left, call `ChangeState(Jumping)`. Landing resets the count. The decision logic lives in a small object you can test without input.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.AirJumps
export type AirJumps = {
	onJumpRequest: () -> boolean,
	remaining: () -> number,
	disconnect: () -> (),
}

local AirJumps = {}

function AirJumps.new(humanoid: Humanoid, maxAirJumps: number, minAirTime: number): AirJumps
	local remaining = maxAirJumps
	local leftGroundAt = math.huge

	local stateConnection = humanoid.StateChanged:Connect(function(_old: Enum.HumanoidStateType, new: Enum.HumanoidStateType)
		if new == Enum.HumanoidStateType.Landed or new == Enum.HumanoidStateType.Running then
			remaining = maxAirJumps
			leftGroundAt = math.huge
		elseif new == Enum.HumanoidStateType.Freefall or new == Enum.HumanoidStateType.Jumping then
			if leftGroundAt == math.huge then
				leftGroundAt = os.clock()
			end
		end
	end)

	local function onJumpRequest(): boolean
		local state = humanoid:GetState()
		local airborne = state == Enum.HumanoidStateType.Freefall or state == Enum.HumanoidStateType.Jumping
		-- The first press already triggers the normal jump; ignore the same press echoing within minAirTime.
		if not airborne or remaining <= 0 or os.clock() - leftGroundAt < minAirTime or humanoid.Health <= 0 then
			return false
		end
		remaining -= 1
		humanoid:ChangeState(Enum.HumanoidStateType.Jumping)
		return true
	end

	return {
		onJumpRequest = onJumpRequest,
		remaining = function(): number
			return remaining
		end,
		disconnect = function()
			stateConnection:Disconnect()
		end,
	}
end

return AirJumps
```

The LocalScript in StarterCharacterScripts:

```lua
--!strict
local UserInputService = game:GetService("UserInputService")
local AirJumps = require(game:GetService("ReplicatedStorage"):WaitForChild("AirJumps"))

local humanoid = script.Parent:WaitForChild("Humanoid")
local jumps = AirJumps.new(humanoid, 1, 0.15)

local connection = UserInputService.JumpRequest:Connect(jumps.onJumpRequest)
humanoid.Died:Connect(function()
	connection:Disconnect()
	jumps.disconnect()
end)
```

- `JumpRequest` fires for every input device, which is why there is no key handling; it can fire several times per press, hence the small `minAirTime`.
- The character is simulated by the player's client, so changing its state locally is enough and replicates as normal movement.
- Movement abilities are client-trusted by nature; if double jump is a paid perk, the server should still check that players without it never stay airborne longer than one jump allows.

# Test
```lua
local rig = __buildRig()
local humanoid = rig.Humanoid
local jumps = item.new(humanoid, 1, 0.15)

check("no air jump while grounded", jumps.onJumpRequest() == false)
humanoid:ChangeState(Enum.HumanoidStateType.Freefall)
humanoid.StateChanged:Fire(Enum.HumanoidStateType.Running, Enum.HumanoidStateType.Freefall)
check("the same press echoing right after takeoff is ignored", jumps.onJumpRequest() == false)
__advance(0.3)
check("air jump allowed while falling", jumps.onJumpRequest() == true and humanoid:GetState() == Enum.HumanoidStateType.Jumping)
check("only one air jump", jumps.onJumpRequest() == false and jumps.remaining() == 0)
humanoid:ChangeState(Enum.HumanoidStateType.Landed)
humanoid.StateChanged:Fire(Enum.HumanoidStateType.Freefall, Enum.HumanoidStateType.Landed)
check("landing restores the air jump", jumps.remaining() == 1)
humanoid:ChangeState(Enum.HumanoidStateType.Freefall)
humanoid.StateChanged:Fire(Enum.HumanoidStateType.Landed, Enum.HumanoidStateType.Freefall)
__advance(0.3)
humanoid.Health = 0
check("dead characters cannot jump", jumps.onJumpRequest() == false)
jumps.disconnect()
```
