---
name: roblox-server-authority
description: Roblox's server authority model (released July 2026) for competitive games - Workspace setup, BindToSimulation, client prediction and rollback, InputActions, attribute limits and what not to use inside the simulation.
---
# Server authority model (server-owned simulation with client prediction)

The server is the single source of truth; clients only report their own inputs, predict a few frames ahead and roll
back and resimulate when the server's authoritative state differs. This removes fly/speed/teleport exploits by design;
gameplay validation (costs, cooldowns, ownership) is still the server's job.

Setup (Workspace properties):
- `Workspace.AuthorityMode = Enum.AuthorityMode.Server` sets the other five: `NextGenerationReplication` on,
  `PlayerScriptsUseInputActionSystem` on, `SignalBehavior = Enum.SignalBehavior.Deferred`, `UseFixedSimulation` on,
  `StreamingEnabled` on.

Simulation code:
- Core logic lives in a ModuleScript (for example `ReplicatedStorage.Simulation`) whose `Initialize` calls
  `RunService:BindToSimulation(function(deltaTime) ... end)`; a Script and a LocalScript both `require` it and call
  `Initialize`, so server and client run the same simulation. During a resimulation Roblox re-runs the bound functions.
- Read inputs, touch synchronized physics objects and update game state only inside bound functions. Only members
  with the "Simulation Access" label can be used there (for example `BasePart.CFrame`).
- Time: use `time()`; with AuthorityMode Server it is synchronized, fixed-step and rewinds on resimulation.
  `tick()`, `os.time()` and `os.clock()` are local clocks that do not roll back: never use them for simulation logic.
- `task.spawn` from a bound function still runs under simulation restrictions; `task.defer` runs later, outside them.
- Prediction: instances with simulation access near the local character are predicted automatically; force it per
  instance with `RunService:SetPredictionMode(instance, mode)`. Cars, characters and other gameplay-critical objects
  can stay server-owned without input lag.

State and input:
- Custom state that the simulation needs (health, ammo, inventory) goes in attributes on predicted instances, written
  only from bound functions. A mismatch triggers a rollback. Replicated attributes: only the first 64 per instance,
  names at most 50 characters, string values at most 50 characters.
- Player input comes from the Input Action System (`InputContext` / `InputAction` / `InputBinding`), read inside
  `BindToSimulation` on both sides; InputContexts must be descendants of the Player (clone a folder from
  ReplicatedStorage into each player on `PlayerAdded`, and loop over players already in the game).
  Do not drive the simulation from `UserInputService.InputBegan`.
- RemoteEvents still work for discrete messages (scored a point, picked up an item) but are not ordered relative to
  property and attribute updates.
- Animations, sounds and effects on the client are predictions: play them so a rollback does not double them.

Templates to copy from: Racing, Soccer, Laser Tag.
