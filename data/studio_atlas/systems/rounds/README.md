# Round state machine

Intermission, Round, Cleanup, repeat. Driven by `Step(dt)` so it is deterministic.

## API
- `Machine.new({ minPlayers, intermission, roundLength, cleanup }, hooks) -> rounds`. Hooks: `getPlayers()`, `onState(state, timeLeft)`, `startRound(participants)`, `endRound(winners, reason)`, `cleanup()`.
- `rounds:Step(dt)`, `rounds:Eliminate(player)`, `rounds:PlayerRemoving(player)`, `rounds:GetState() -> state, timeLeft`, `rounds:IsParticipant(player)`.

## Wire it
One loop: `RunService.Heartbeat:Connect(function(dt) rounds:Step(dt) end)` (or `task.wait(1)` and `Step(1)`). Call `Eliminate` from the death handler and `PlayerRemoving` from `Players.PlayerRemoving`. Replicate state in `onState` with an attribute on a folder in ReplicatedStorage.

## Pitfalls
- Participants are fixed when the round starts; a mid-round joiner spectates until the next round (spawn them in the lobby).
- The round ends on timeout, on one player left (when more than one started), or when everyone left.
- Do the real cleanup in the `cleanup` hook, after players have seen the result screen.
