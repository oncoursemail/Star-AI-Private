# Session-locked DataStore profile

A key is owned by one server at a time. The lock lives in the stored record and changes only inside `UpdateAsync`.

## API
- `Profiles.new(cfg) -> Manager`: `store` (a DataStore), `jobId` (`game.JobId`), `now` (`os.time`), `wait` (`task.wait`), `spawn` (`task.spawn`), `defaults`, `schemaVersion`, `migrations[n]` (schema n to n+1), optional `lockTimeout` (300 s), `attempts` (6).
- `manager:Load(key) -> Profile?, reason?`: reason is `"locked"`, `"newer"` or `"datastore"`; kick the player with a message on nil.
- `profile.Data`: plain table, change it freely on the server. `profile:Save()` and `profile:Release() -> boolean`.
- `manager:AutosaveAll()` (call every 60 s, refreshes the lock), `manager:ReleaseAll()`, `manager:BindToClose(game)`.

## Wire it
`Players.PlayerAdded`: `Load("Player_" .. UserId)`, keep it in a table keyed by player. `PlayerRemoving`: `profile:Release()`. Also call `manager:BindToClose(game)` once, and run `AutosaveAll` from a loop.

## Pitfalls
- `Active` turns false when another server took the key: stop using the data and kick the player.
- Never write `profile.Data` from a client value; validate first.
- Add a migration for every schema bump, otherwise `Profiles.new` asserts.
- Shutdown has about 30 s: `ReleaseAll` uses 3 attempts per player.
- Studio playtests need API access enabled to hit the real DataStore.
