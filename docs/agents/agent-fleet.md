# Agent fleet (Star-AI #406), first slice

Branch `star/agent-fleet-20261016`, PR to `star/next`, "Refs #406".

## Shipped in this slice
`star/agent_fleet.py` (opt-in, off unless `STAR_AGENT_FLEET=1` or `enabled=True`):
- `sample_resources()` / `plan_slots()`: live free RAM + CPU busy (via `resource_probes`) decide the slot count (cap 4);
  unmeasurable or busy machine gives 0 slots and an honest reason.
- `run_fleet()`: one git worktree + branch `star/fleet-<id>` per task, runs the task's CLI agent command (no shell),
  then the fleet itself runs the task's test command. Status `proposed` only if the agent made changes AND tests exit 0.
  Other statuses: disabled, cancelled, agent_failed, no_changes, tests_failed, error. No test command = never a pass.
- Cancel via a `threading.Event` (kills the running agent/test process). Exceptions in one worker become an `error` receipt.
- Never merges, pushes or publishes. Protected paths (Paintball, %APPDATA%\STAR) are refused.

Tests: `tests/test_agent_fleet.py` (8, offline, real git + python subprocesses).

## Slice 2 (branch `star/fleet-handoff-20261020`, Refs #406 #424)
- `FleetTask.acp_prompt` + `approve`: the task's command is an ACP agent (`star/acp_adapter.py`) started with cwd = the
  worktree; it can only change files when the host's `approve` callback says yes; its "end_turn" is never a pass, the
  fleet's own test command decides. States map to the existing receipts (`auth_required` -> `agent_failed`, etc.).
  A fleet cancel reaches a running ACP agent at its next message (the adapter polls between JSON lines).
- `receipts_file=`: every receipt + the measured resources + slot count appended as JSON lines (latency/load evidence).
- `fleet_worktrees(repo)`: lists leftover `star/fleet-*` worktrees after a crash; never deletes (owner reviews).
- `probe_agents()`: installed-or-not for `opencode`, `codex`, `claude` CLIs; auth/quota stay "unknown" (nothing launched).
- Tests: 4 more in `tests/test_agent_fleet.py` (12 total; fake ACP agent = simulation, no real CLI).

## Left of #406
- Capability tests against a real installed OpenCode/Codex/Claude CLI on authorized hardware (only simulation so far).
- Per-agent enable UI + "Run all enabled agents" button; pause/resume.
- Leases through `agent_resource_planner` (one-shot sizing only), VRAM budget, UI of budgets/blocked states.
- Diff review step in the app, integration with `orchestration.TaskPlan` dependencies.
- Acceptance items: real Windows packaged test, protected-project refusal in the packaged app.
