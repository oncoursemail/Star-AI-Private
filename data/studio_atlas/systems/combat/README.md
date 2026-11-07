# Combat with hit validation

The client reports "I hit X". The server checks everything and applies its own damage.

## API
- `Combats.new({ now, weapons = { Sword = { damage, range, cooldown } }, getCombatant, hasLineOfSight, applyDamage, owns?, lagLeeway?, cooldownLeeway? }) -> combat`.
- `getCombatant(entity) -> { position, health, team? }?` reads the server-side root part and Humanoid.
- `combat:Equip(attacker, weapon) -> boolean`, `combat:TryHit(attacker, target) -> ok, reason`, `combat:Forget(attacker)`.

## Wire it
A RemoteEvent `Hit` with one validated argument (target id or Instance, resolved on the server) calls `TryHit`. `applyDamage` does `humanoid:TakeDamage(amount)`. `hasLineOfSight` is a server raycast with `RaycastParams` that excludes both characters.

## Pitfalls
- Damage, range and cooldown come from the weapon table, never from the client.
- `lagLeeway` (default 6 studs) covers latency; do not make it large, or reach hacks get easy.
- Refused hits do not start the cooldown; rate-limit the remote as well (see the remote layer).
- Call `Forget` on `PlayerRemoving`.
