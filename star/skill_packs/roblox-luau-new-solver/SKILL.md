---
name: roblox-luau-new-solver
description: Luau's new type solver on Roblox (general release November 2025) - which scripts use it, the Workspace settings, what changed for strict code and how to write types that check cleanly under both solvers.
---
# Luau type checking with the new type solver

Modes (first line of a script): `--!nocheck` (no checks), `--!nonstrict` (only annotated types are asserted; the
default for new places' templates), `--!strict` (all inferred and annotated types are asserted).
`Workspace.LuauTypeCheckMode` sets the default mode for every script; a script's own `--!` line overrides it.

Which solver runs:
- The new type solver is generally available (since 2025-11-20) and is the default for nocheck and nonstrict scripts.
- `Workspace.UseNewLuauTypeSolver` (an `Enum.RolloutState`: Default follows the engine-wide rollout) selects the
  solver; strict projects stay on the old solver until it is set to Enabled. The old solver remains available through
  2026. Both are edit-time analysis only: neither changes how code runs.

What the new solver adds or changes:
- Better refinements (`if typeof(x) == "string" then`, `if x then`, `x ~= nil` narrow types more precisely).
- Read-only and write-only table properties: `type Config = { read Name: string, write Count: number }`.
- Type functions (`type function`) for computing types; more permissive casts with `::`.
- Known rough edges: long or unclear error messages, "blocked type" errors on complex generic code, slower
  edit-time analysis in very large scripts. Simplify the types (smaller generics, explicit annotations on function
  parameters and return values) instead of silencing errors with `any`.

Write types that check under both solvers:
- Annotate function parameters and return types of module APIs; let locals infer.
- Use the Roblox class names as types (`local part: BasePart`, `Enum.Material`), `?` for optional values, and
  `typeof()` / `:IsA()` before using an Instance as a narrower class.
- Prefer `{T}` arrays and `{[K]: V}` maps over untyped tables; export shared types from ModuleScripts with
  `export type`.
