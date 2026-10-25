# Sources for roblox-server-authority

Official Roblox Creator Documentation (CC-BY-4.0), creator-docs commit 4e795e6 (2026-10-24) in the STAR Knowledge index.

| Claim in the skill | Documentation page |
|---|---|
| Server as source of truth, client prediction, misprediction, rollback and resimulation | https://create.roblox.com/docs/projects/server-authority |
| Workspace setup: AuthorityMode Server sets NextGenerationReplication, PlayerScriptsUseInputActionSystem, SignalBehavior Deferred, UseFixedSimulation, StreamingEnabled | https://create.roblox.com/docs/projects/server-authority, "Setup" |
| BindToSimulation in a ModuleScript loaded by a Script and a LocalScript; resimulation re-runs bound functions | https://create.roblox.com/docs/projects/server-authority, "Simulation sync" |
| time() synchronized and fixed-step; tick(), os.time(), os.clock() not synchronized and not rolled back | https://create.roblox.com/docs/projects/server-authority, "Simulation sync" |
| SetPredictionMode; automatic prediction near the local character | https://create.roblox.com/docs/projects/server-authority, "Network ownership and prediction" |
| Attributes for custom state; first 64 attributes, 50-character names and string values | https://create.roblox.com/docs/projects/server-authority, "State sync with attributes", "Attribute limits" |
| Simulation Access label; task.spawn keeps restrictions, task.defer escapes them | https://create.roblox.com/docs/projects/server-authority, "Simulation access" |
| Input Action System; InputContexts under the Player; do not use UserInputService.InputBegan in the simulation | https://create.roblox.com/docs/projects/server-authority, "Input actions" |
| RemoteEvents not ordered relative to property/attribute updates | https://create.roblox.com/docs/projects/server-authority, "Remote events" |
| Racing, Soccer, Laser Tag templates | https://create.roblox.com/docs/projects/server-authority, "Example projects" |
| Release to all creators July 2026 | Roblox newsroom 2026-07-09 (docs/research/roblox-2026-20261023.md section 1.2) |

API names verified with the knowledge service /api-lookup on 2026-10-25 (all found, none deprecated): Workspace.AuthorityMode, Workspace.NextGenerationReplication, Workspace.PlayerScriptsUseInputActionSystem, Workspace.SignalBehavior, Workspace.UseFixedSimulation, Workspace.StreamingEnabled, RunService:BindToSimulation, RunService:SetPredictionMode, InputContext, InputAction, InputBinding, UserInputService.InputBegan.
