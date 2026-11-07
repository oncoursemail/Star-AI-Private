---
id: gb-data-remote-projectile-fire
category: remote-security
topics: RemoteEvent, hitscan, server raycast, fire rate, ammo
source: original
---
# Request
For my blaster, the client sends `Fire:FireServer(origin, direction)` and the server raycasts. Exploiters fire from behind walls and much faster than the gun should allow. What should the server check?

# Answer
Ignore the client's origin and start the ray at the server's view of the character's head; accept only a direction (finite, non-zero, normalised by the server). Enforce fire rate and ammo on the server, then raycast with the shooter's character excluded and apply the weapon's own damage.

```lua
--!strict
-- ModuleScript: ServerScriptService.Blaster
local Players = game:GetService("Players")

export type Weapon = { damage: number, range: number, fireInterval: number, magazine: number }
type State = { lastShot: number, ammo: number }

local Blaster = {}

function Blaster.new(weapon: Weapon): (player: Player, direction: unknown) -> Instance?
	local states: { [Player]: State } = {}

	Players.PlayerRemoving:Connect(function(player: Player)
		states[player] = nil
	end)

	local function validDirection(value: unknown): Vector3?
		local kind = typeof(value)
		if kind ~= "Vector3" then
			return nil
		end
		local v = value :: any
		local length = v.Magnitude
		if length ~= length or length < 0.5 or length > 2 then
			return nil -- clients send unit vectors; anything else is tampered
		end
		return v.Unit
	end

	-- Returns the Instance that was hit (for effects), or nil.
	return function(player: Player, directionArg: unknown): Instance?
		local direction = validDirection(directionArg)
		local character: Model? = player.Character
		if direction == nil or character == nil then
			return nil
		end
		local head: BasePart? = character:FindFirstChild("Head")
		local humanoid: Humanoid? = character:FindFirstChildOfClass("Humanoid")
		if head == nil or humanoid == nil or humanoid.Health <= 0 then
			return nil
		end
		local state = states[player] or { lastShot = -math.huge, ammo = weapon.magazine }
		states[player] = state
		local now = os.clock()
		if now - state.lastShot < weapon.fireInterval or state.ammo <= 0 then
			return nil
		end
		state.lastShot = now
		state.ammo -= 1

		local params = RaycastParams.new()
		params.FilterType = Enum.RaycastFilterType.Exclude
		params.FilterDescendantsInstances = { character }
		local result = workspace:Raycast(head.Position, direction * weapon.range, params)
		if result == nil then
			return nil
		end
		local hitModel = result.Instance:FindFirstAncestorOfClass("Model")
		local victim: Humanoid? = if hitModel then hitModel:FindFirstChildOfClass("Humanoid") else nil
		if victim and victim.Health > 0 then
			victim:TakeDamage(weapon.damage)
		end
		return result.Instance
	end
end

return Blaster
```

- Starting the ray at the server-side head is what stops shots from behind walls: the client can aim anywhere, but only from where the server says it stands.
- The client still raycasts locally for instant hit markers; the server's result decides damage.
- Reloading is a server timer that refills `ammo`; never accept an ammo count from the client.
- Allow a small timing tolerance (a few milliseconds below `fireInterval`) if honest players on high ping get shots dropped.

# Test
```lua
local fire = item.new({ damage = 25, range = 100, fireInterval = 0.25, magazine = 3 })
local shooter = __makePlayer(1, "Shooter")
local target = __makePlayer(2, "Target")
__makeCharacter(shooter, Vector3.new(0, 3, 0))
local victim = __makeCharacter(target, Vector3.new(0, 3, -30))
local aim = Vector3.new(0, -1.5, -30).Unit

local hit = fire(shooter, aim)
check("a valid shot hits and damages the target", hit ~= nil and victim.Humanoid.Health == 75)
fire(shooter, aim)
check("shots faster than the fire rate are dropped", victim.Humanoid.Health == 75)

__advance(0.3)
check("tampered (non-unit) directions are refused", fire(shooter, aim * 50) == nil and victim.Humanoid.Health == 75)
check("NaN and non-vector directions are refused", fire(shooter, Vector3.new(0 / 0, 0, 0)) == nil and fire(shooter, "forward") == nil)

fire(shooter, aim)
__advance(0.3)
fire(shooter, aim)
__advance(0.3)
fire(shooter, aim)
check("magazine limits total shots", victim.Humanoid.Health == 25)
```
