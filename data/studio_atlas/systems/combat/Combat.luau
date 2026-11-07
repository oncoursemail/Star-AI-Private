--!strict
-- Server-authoritative hit validation. The client only says "I hit this target with this weapon"; the server
-- checks the weapon is owned and equipped, the cooldown, both bodies are alive, teams, range and line of sight
-- from SERVER positions, and applies the damage from its own weapon table.

export type Vec = { X: number, Y: number, Z: number }
export type Weapon = { damage: number, range: number, cooldown: number }
export type Combatant = { position: Vec, health: number, team: string? }
export type Config = {
	now: () -> number, -- os.clock
	weapons: { [string]: Weapon },
	getCombatant: (entity: any) -> Combatant?, -- from the character's root part and Humanoid, on the server
	hasLineOfSight: (from: Vec, to: Vec) -> boolean, -- a server raycast that ignores both characters
	applyDamage: (target: any, amount: number, attacker: any, weapon: string) -> (),
	owns: ((attacker: any, weapon: string) -> boolean)?,
	lagLeeway: number?, -- studs of slack for latency (default 6)
	cooldownLeeway: number?, -- fraction of the cooldown that may be skipped for jitter (default 0.1)
}
export type Combat = {
	Equip: (self: Combat, attacker: any, weapon: string) -> boolean,
	TryHit: (self: Combat, attacker: any, target: any) -> (boolean, string?),
	Forget: (self: Combat, attacker: any) -> (),
}

local Combats = {}

local function distance(a: Vec, b: Vec): number
	local dx, dy, dz = a.X - b.X, a.Y - b.Y, a.Z - b.Z
	return math.sqrt(dx * dx + dy * dy + dz * dz)
end

function Combats.new(cfg: Config): Combat
	local lagLeeway = cfg.lagLeeway or 6
	local cooldownLeeway = cfg.cooldownLeeway or 0.1
	local equipped: { [any]: string } = {}
	local lastHit: { [any]: number } = {}
	local combat = {} :: Combat

	function combat.Equip(_self, attacker, weapon)
		if cfg.weapons[weapon] == nil or (cfg.owns and not cfg.owns(attacker, weapon)) then
			return false
		end
		equipped[attacker] = weapon
		return true
	end

	function combat.TryHit(_self, attacker, target)
		local name = equipped[attacker]
		local weapon = if name then cfg.weapons[name] else nil
		if name == nil or weapon == nil then
			return false, "no weapon equipped"
		end
		if attacker == target then
			return false, "self hit"
		end
		local now = cfg.now()
		local last = lastHit[attacker]
		if last ~= nil and now - last < weapon.cooldown * (1 - cooldownLeeway) then
			return false, "cooldown"
		end
		local from, to = cfg.getCombatant(attacker), cfg.getCombatant(target)
		if from == nil or to == nil or from.health <= 0 or to.health <= 0 then
			return false, "not alive"
		end
		if from.team ~= nil and from.team == to.team then
			return false, "same team"
		end
		if distance(from.position, to.position) > weapon.range + lagLeeway then
			return false, "out of range"
		end
		if not cfg.hasLineOfSight(from.position, to.position) then
			return false, "no line of sight"
		end
		lastHit[attacker] = now
		cfg.applyDamage(target, weapon.damage, attacker, name)
		return true, nil
	end

	function combat.Forget(_self, attacker)
		equipped[attacker] = nil
		lastHit[attacker] = nil
	end

	return combat
end

return Combats
