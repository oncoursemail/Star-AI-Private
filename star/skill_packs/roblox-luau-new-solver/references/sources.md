# Sources for roblox-luau-new-solver

| Claim in the skill | Source |
|---|---|
| --!nocheck / --!nonstrict / --!strict meaning; Workspace.LuauTypeCheckMode sets the default; class, enum and optional types | https://create.roblox.com/docs/luau/type-checking (CC-BY-4.0, creator-docs 4e795e6) |
| Workspace.UseNewLuauTypeSolver is an Enum.RolloutState that selects the solver; Default follows the engine-wide rollout; LuauTypeCheckMode controls the mode | https://create.roblox.com/docs/reference/engine/classes/Workspace#UseNewLuauTypeSolver , https://create.roblox.com/docs/reference/engine/classes/Workspace#LuauTypeCheckMode , https://create.roblox.com/docs/reference/engine/enums/LuauTypeCheckMode , https://create.roblox.com/docs/reference/engine/enums/RolloutState |
| General release 2025-11-20; default for nocheck/nonstrict; strict stays on the old solver until UseNewLuauTypeSolver is Enabled; old solver available through 2026; read-only/write-only properties, refinements, type functions, casts; known issues (long errors, blocked types, edit-time performance); no runtime effect | DevForum announcement "General Release: Luau's New Type Solver" https://devforum.roblox.com/t/general-release-luau's-new-type-solver/4084991 (as summarised in docs/research/roblox-2026-20261023.md section 1.1, tag [C]) |
| Type syntax (read/write properties, type functions, export type) | https://luau.org/typecheck |
| Template default Nonstrict | docs/research/roblox-2026-20261023.md section 1.1 [C] |

API names verified with the knowledge service /api-lookup on 2026-10-25 (all found, none deprecated): Workspace.UseNewLuauTypeSolver, Workspace.LuauTypeCheckMode.
