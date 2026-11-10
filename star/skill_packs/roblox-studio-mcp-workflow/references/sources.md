# Sources for roblox-studio-mcp-workflow

Original field notes written 2026-10-13; Studio MCP/Open Cloud permissions reviewed 2026-11-10 against the current official Creator Hub pages. The field evidence comes from the owner's private Paintball port project, a Roblox Studio port that
Claude and Codex ran from 2026-09-20 to 2026-10-08. It was read only and rewritten as general lessons; no game assets
or code were copied. The official pages are from the Roblox Creator Documentation (CC-BY-4.0), found through the STAR
Knowledge index.

| Label | Evidence |
|---|---|
| F1 | Project CLAUDE.md: the core loop, require-coverage lint, cloud-save confirmation line, real window screenshots versus MCP screen capture, and recovery notes (a stray Delete key deleted the map, one undo restored it, then the parts were locked and a guard script added) |
| F2 | Project deploy skill (pb-deploy): install in Edit, stop Play first, run a smoke test, and never claim a save without the log line |
| F3 | Project INTEGRATOR_RUNBOOK.md and AGENTS.md: installs of selected modules only, dependency closure, restoring Edit swaps, input safety |
| F4 | Project handoff log CONTINUE_IMMEDIATELY.md: an empty map was cloud-saved and restored from version history; a Studio auto-update reopened the place; a runtime clone was saved into the place and fixed with Archivable = false; a long loader timed out until it yielded |
| S1 | https://create.roblox.com/docs/studio/mcp |
| S2 | https://create.roblox.com/docs/studio/testing-modes |
| S3 | https://create.roblox.com/docs/projects/version-history |
| S4 | https://create.roblox.com/docs/reference/engine/classes/ChangeHistoryService |
| S5 | https://create.roblox.com/docs/reference/engine/classes/RunService |
| S6 | https://create.roblox.com/docs/reference/engine/classes/BasePart |
| S7 | Studio MCP Open Cloud integration: open_cloud_invoke, per-game and per-person permissions, Safe/Balanced/Full access/Custom levels, scope categories, approved upload folders, Network capability/domain allowlist, and unavailable scopes | https://create.roblox.com/docs/studio/mcp-open-cloud |
| S8 | Open Cloud scope names, target types and supported endpoints | https://create.roblox.com/docs/cloud/reference/scopes |
| S9 | Studio data-store access shares live experience data; use a separate test experience and enable Studio API Services only there | https://create.roblox.com/docs/cloud-services/data-stores |

API names verified with the knowledge service /api-lookup on 2026-10-13: RunService:IsRunning, Instance:FindFirstChild,
Instance.AncestryChanged, BasePart.Locked, Instance.Archivable, ChangeHistoryService:Undo, Instance:GetDescendants.
Two behaviours come from the project's own testing on one machine and are not documented: MCP screen capture showing
SurfaceAppearance white, and Studio reopening the place after an auto-update.
