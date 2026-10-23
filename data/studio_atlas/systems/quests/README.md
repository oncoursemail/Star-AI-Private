# Quest tracker

## API
- `Quests.new({ quests = { [id] = { title, objectives = {{ kind, target, count }}, requires?, repeatable? } }, maxActive?, onComplete, onProgress? }) -> tracker`.
- `tracker:Attach(player, state)` with `state = profile.Data.Quests = { Active = {}, Completed = {} }` (saved state is repaired against the definitions), `Detach`.
- `tracker:Accept(player, id) -> ok, reason`, `Abandon`, `Report(player, kind, target, amount?)`, `Progress`, `IsCompleted`.

## Wire it
Game systems report events: `tracker:Report(killer, "kill", "Zombie")`, `Report(player, "collect", "Bone")`. `onComplete` grants the reward (wallet, inventory) on the server.

## Pitfalls
- Report from server events only (a death, a pickup), never from a client message.
- Completion is removed from `Active` before `onComplete`, so a reward cannot be granted twice.
- Changing a quest's objectives is safe: old progress is clamped on attach.
