Reference fix.

```lua
-- Damage: hit damage for the paintball markers, with distance falloff and armor.
local Damage = {}

Damage.BASE = {
	pistol = 20,
	rifle = 34,
	shotgun = 12,
	sniper = 80,
}
Damage.PELLETS = {
	shotgun = 8,
}
Damage.FALLOFF_START = 40
Damage.FALLOFF_END = 120
Damage.MIN_FACTOR = 0.4
Damage.HEADSHOT_MULTIPLIER = 2
Damage.SHOTGUN_HEADSHOT_MULTIPLIER = 1.25
Damage.MAX_ARMOR = 0.8

-- 1 up to FALLOFF_START studs, then linear down to MIN_FACTOR at FALLOFF_END.
function Damage.falloff(distance)
	if distance <= Damage.FALLOFF_START then
		return 1
	end
	if distance >= Damage.FALLOFF_END then
		return Damage.MIN_FACTOR
	end
	local t = (distance - Damage.FALLOFF_START) / (Damage.FALLOFF_END - Damage.FALLOFF_START)
	return 1 - t * (1 - Damage.MIN_FACTOR)
end

function Damage.pellets(weapon)
	return Damage.PELLETS[weapon] or 1
end

-- Damage of one hit (one pellet for the shotgun). armor is 0..1 (fraction blocked).
function Damage.compute(weapon, distance, armor, headshot)
	local base = Damage.BASE[weapon]
	if base == nil then
		error("unknown weapon " .. tostring(weapon))
	end
	local dmg = base * Damage.falloff(distance)
	if headshot then
		dmg *= if weapon == "shotgun" then Damage.SHOTGUN_HEADSHOT_MULTIPLIER else Damage.HEADSHOT_MULTIPLIER
	end
	local blocked = math.clamp(armor or 0, 0, Damage.MAX_ARMOR)
	dmg = dmg * (1 - blocked)
	return math.floor(dmg + 0.5)
end

-- Total damage when every pellet hits.
function Damage.volley(weapon, distance, armor)
	return Damage.compute(weapon, distance, armor) * Damage.pellets(weapon)
end

return Damage
```
