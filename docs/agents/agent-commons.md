# Agent Commons (#424) - first slice

Done: `star/acp_adapter.py` - opt-in (`enabled=True` required) ACP client over stdio. Advertises no fs/terminal
capability, rejects agent permission requests unless the host passes `approve`, keeps tool calls as
`agent_reported` receipts, states ok/unavailable/auth_required/timeout/cancelled/error. Tested with a fake
agent (simulation) in `tests/test_acp_adapter.py`. No settings/UI wiring yet.

Slice 2 (`star/fleet-handoff-20261020`): the adapter is now used by the agent fleet (`FleetTask.acp_prompt`,
`docs/agents/agent-fleet.md`): worktree isolation, host-side approval of writes, host-run tests, receipts on disk.
`agent_fleet.probe_agents()` reports installed/missing CLIs honestly (auth and quota "unknown").

Left: stream() and tool-approval UI, real OpenCode/Gemini/goose runs on authorized hardware (gate 1 needs real
hardware or a labelled simulation: the tests are the simulation), JSON-RPC (Pi) variant, mission/event stream into
chat, host-verified evidence beyond the test receipt, sandbox grants, resource admission, React inspector,
benchmarks (gates 2-4).
