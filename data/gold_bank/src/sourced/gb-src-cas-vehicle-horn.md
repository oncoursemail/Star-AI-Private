---
id: gb-src-cas-vehicle-horn
category: ui-interaction
topics: ContextActionService, BindAction, UnbindAction, mobile button, gamepad, VehicleSeat, input
source: adapted
source_id: creator-docs
source_path: content/en-us/reference/engine/classes/ContextActionService.yaml
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I want a car horn: H on keyboard, Y on gamepad and an on-screen button on mobile, but only while the player is sitting in the driver seat. Holding it should keep honking. With UserInputService I'd have to build the mobile button myself. Is there a cleaner way?

# Answer
`ContextActionService:BindAction` binds one handler to several inputs and can create the touch button for you. Bind when the local player sits in the driver seat, unbind when they leave, and play or stop the looping horn from the input state.

```lua
--!strict
local ContextActionService = game:GetService("ContextActionService")

local ACTION = "HonkHorn"

local Horn = {}

function Horn.handler(sound: Sound)
	return function(_actionName: string, state: Enum.UserInputState, _input: InputObject): Enum.ContextActionResult
		if state == Enum.UserInputState.Begin then
			sound:Play()
		elseif state == Enum.UserInputState.End or state == Enum.UserInputState.Cancel then
			sound:Stop()
		end
		return Enum.ContextActionResult.Sink
	end
end

function Horn.bindToSeat(humanoid: Humanoid, driverSeat: VehicleSeat, sound: Sound): RBXScriptConnection
	sound.Looped = true
	return humanoid.Seated:Connect(function(active: boolean, seat: Instance?)
		if active and seat == driverSeat then
			ContextActionService:BindAction(ACTION, Horn.handler(sound), true, Enum.KeyCode.H, Enum.KeyCode.ButtonY)
			ContextActionService:SetTitle(ACTION, "Horn")
		else
			ContextActionService:UnbindAction(ACTION)
			sound:Stop()
		end
	end)
end

return Horn
```

- Passing `true` as the third argument creates a touch button on mobile; `SetTitle` labels it.
- Handling `Cancel` stops the horn if the binding is removed or overridden while the key is held.
- Returning `Sink` keeps H from also triggering lower-priority bindings while driving.
- The horn sound is local; if other players should hear it, fire a remote and let the server play a sound in the car.

# Test
```lua
local ContextActionService = game:GetService("ContextActionService")
local sound = Instance.new("Sound")
local handle = item.handler(sound)
handle("HonkHorn", Enum.UserInputState.Begin, nil)
check("begin plays the horn", sound.Playing == true)
local result = handle("HonkHorn", Enum.UserInputState.End, nil)
check("end stops the horn and sinks input", sound.Playing == false and result == Enum.ContextActionResult.Sink)
local seated = Instance.new("BindableEvent")
local humanoid = { Seated = seated.Event }
local seat = Instance.new("VehicleSeat")
item.bindToSeat(humanoid, seat, sound)
seated:Fire(true, seat)
check("bound while seated", ContextActionService.__bound.HonkHorn ~= nil and sound.Looped == true)
seated:Fire(false, nil)
check("unbound after leaving the seat", ContextActionService.__bound.HonkHorn == nil)
```
