---
id: gb-world-phys-vehicle-ownership
category: physics
topics: network ownership, VehicleSeat, Occupant, SetNetworkOwner, vehicles
source: original
---
# Request
My cars feel laggy and rubber-band when players drive them, and sometimes a car parked near another player starts jittering. I've read I should set network ownership. When and to whom?

# Answer
Give the vehicle's assembly to the driver while they sit in the seat, so their inputs are simulated locally with no round trip, and give it back to the server when they get out so a parked car does not drift to whichever client is nearest. Watch the seat's `Occupant` property for both transitions.

```lua
--!strict
-- ModuleScript: ServerScriptService.VehicleOwnership
local Players = game:GetService("Players")

local VehicleOwnership = {}

function VehicleOwnership.bind(seat: VehicleSeat): RBXScriptConnection
	local function refresh()
		local occupant = seat.Occupant
		local character = if occupant then occupant.Parent else nil
		local driver = if character then Players:GetPlayerFromCharacter(character) else nil
		-- SetNetworkOwner affects the whole assembly the seat is welded into.
		if seat:CanSetNetworkOwnership() then
			seat:SetNetworkOwner(driver)
		end
	end
	refresh()
	return seat:GetPropertyChangedSignal("Occupant"):Connect(refresh)
end

return VehicleOwnership
```

Binding every car seat at startup and for cars spawned later:

```lua
--!strict
local CollectionService = game:GetService("CollectionService")
local VehicleOwnership = require(script.Parent:WaitForChild("VehicleOwnership"))

local function onSeat(seat: Instance)
	if seat:IsA("VehicleSeat") then
		VehicleOwnership.bind(seat)
	end
end

CollectionService:GetInstanceAddedSignal("CarSeat"):Connect(onSeat)
for _, seat in CollectionService:GetTagged("CarSeat") do
	onSeat(seat)
end
```

- `SetNetworkOwner(nil)` hands ownership to the server, which is what a parked car wants; NPC drivers also return nil from `GetPlayerFromCharacter`, keeping NPC cars server-simulated.
- `CanSetNetworkOwnership` is false when a part of the assembly is anchored (for example a car still locked in place at the spawner), and calling `SetNetworkOwner` then would error.
- The driver's client now has authority over the car's physics: validate anything gameplay-relevant (lap times, ramming damage) on the server from positions over time.

# Test
```lua
local car = Instance.new("Model")
local seat = Instance.new("VehicleSeat")
seat.Parent = car
car.Parent = workspace
local connection = item.bind(seat)
check("parked car starts server-owned", seat:GetNetworkOwner() == nil)

local driver = __makePlayer(33, "Driver")
local character = __makeCharacter(driver)
seat.Occupant = character.Humanoid
check("driver owns the car while seated", seat:GetNetworkOwner() == driver)
seat.Occupant = nil
check("ownership returns to the server on exit", seat:GetNetworkOwner() == nil)

local npc = __buildRig()
npc.Parent = workspace
seat.Occupant = npc.Humanoid
check("NPC driver keeps it server-owned", seat:GetNetworkOwner() == nil)
connection:Disconnect()
seat.Occupant = character.Humanoid
check("disconnected binding stops updating", seat:GetNetworkOwner() == nil)
```
