---
id: gb-world-combat-iframes-teams
category: combat-hitbox
topics: damage service, invincibility frames, friendly fire, ForceField, teams
source: original
---
# Request
Every weapon in my game calls `humanoid:TakeDamage` directly, so I can't add invincibility frames after getting hit or a friendly-fire toggle without editing 15 scripts. Can you write one central damage function that handles i-frames, teams and spawn ForceFields?

# Answer
Route all damage through one server module. It rejects bad amounts, dead or shielded victims, self-damage, teammates (unless friendly fire is on) and victims still inside their i-frame window, then applies the damage and starts a new window. It returns whether damage happened so weapons only play hit effects for real hits.

```lua
--!strict
-- ModuleScript: ServerScriptService.DamageService
local Players = game:GetService("Players")

export type Options = { iframes: number, friendlyFire: boolean }
export type Service = {
	tryDamage: (attacker: Player?, victim: Humanoid, amount: number) -> boolean,
}

local DamageService = {}

function DamageService.new(options: Options): Service
	local lastDamaged: { [Humanoid]: number } = {}

	local function tryDamage(attacker: Player?, victim: Humanoid, amount: number): boolean
		if amount ~= amount or amount <= 0 or amount == math.huge then
			return false
		end
		local character = victim.Parent
		if character == nil or victim.Health <= 0 or character:FindFirstChildOfClass("ForceField") then
			return false
		end
		local victimPlayer = Players:GetPlayerFromCharacter(character)
		if attacker and victimPlayer then
			if attacker == victimPlayer then
				return false
			end
			if not options.friendlyFire and attacker.Team ~= nil and attacker.Team == victimPlayer.Team then
				return false
			end
		end
		local now = os.clock()
		local last = lastDamaged[victim]
		if last and now - last < options.iframes then
			return false
		end
		lastDamaged[victim] = now
		-- Drop the entry when its window ends, so humanoids that are gone are not kept in the table.
		task.delay(options.iframes, function()
			if lastDamaged[victim] == now then
				lastDamaged[victim] = nil
			end
		end)
		victim:TakeDamage(amount)
		return true
	end

	return { tryDamage = tryDamage }
end

return DamageService
```

Weapons then call `if Damage.tryDamage(player, humanoid, 25) then playHitEffect() end` with one shared `Damage = DamageService.new({ iframes = 0.4, friendlyFire = false })`.

- `TakeDamage` already ignores characters with a ForceField; checking it first also keeps the i-frame timer and hit effects from triggering on shielded players.
- NaN and infinite amounts are refused, which matters as soon as any damage value is computed from client-provided data.
- NPCs (no Player) always take damage from players, and a nil attacker (lava, fall damage) skips the team logic but still respects i-frames.

# Test
```lua
local service = item.new({ iframes = 0.5, friendlyFire = false })
local red = Instance.new("Team")
red.Parent = game:GetService("Teams")
local blue = Instance.new("Team")
blue.Parent = game:GetService("Teams")
local a = __makePlayer(45, "Red1")
local aChar = __makeCharacter(a)
a.Team = red
local b = __makePlayer(46, "Red2")
local bChar = __makeCharacter(b)
b.Team = red
local c = __makePlayer(47, "Blue1")
local cChar = __makeCharacter(c)
c.Team = blue

check("enemy takes damage", service.tryDamage(a, cChar.Humanoid, 20) and cChar.Humanoid.Health == 80)
check("i-frames block the follow-up", not service.tryDamage(a, cChar.Humanoid, 20) and cChar.Humanoid.Health == 80)
__advance(0.6)
check("damage allowed after i-frames", service.tryDamage(a, cChar.Humanoid, 20) and cChar.Humanoid.Health == 60)
check("teammate protected", not service.tryDamage(a, bChar.Humanoid, 20) and bChar.Humanoid.Health == 100)
check("self damage refused", not service.tryDamage(a, aChar.Humanoid, 20))
check("NaN and negative refused", not service.tryDamage(a, bChar.Humanoid, 0 / 0) and not service.tryDamage(c, aChar.Humanoid, -5))
Instance.new("ForceField").Parent = aChar
check("spawn forcefield blocks damage", not service.tryDamage(c, aChar.Humanoid, 20) and aChar.Humanoid.Health == 100)
local ff = item.new({ iframes = 0, friendlyFire = true })
check("friendly fire option", ff.tryDamage(a, bChar.Humanoid, 10) and bChar.Humanoid.Health == 90)
```
