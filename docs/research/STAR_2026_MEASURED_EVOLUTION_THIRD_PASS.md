# STAR AI — Measured Evolution, Third Pass (2026-10-19)

Status: **research and proposed implementation; not shipped.**
Target: private source branch; preserve public release boundary.

## Evidence from current STAR

- README on `star/next` reports v1.0 Roblox development 16/34 and blind holdout 9/24, inconclusive against v0.9. Code volume and passing unit tests are not equivalent to model-quality improvement.
- Incremental repair is being reviewed in draft PR #491. The innovation gate is in PR #488; live-show production in PR #492. Avoid duplicating those changes.
- `star/agent_runtime.py` currently has strict DAG deadlines and no transient read retry. Its `task_timeout` callback is evaluated twice for worker stage budgets, a potential inconsistency for stateful callbacks.

## Highest-impact roadmap, gated by evidence

1. **Strengthen the measurement loop first.** Freeze a blinded task set; run multiple paired seeds against the same model, hardware, prompts and tool permissions. Report per-domain pass rate, latency p50/p95, cost, error mode and security regressions. Block upgrades that regress holdout results, even if development scores rise. Trace-level replay must redact secrets and must not grant extra tool access.
2. **Bounded read-only recovery.** Add explicit opt-in retry (at most two) only to trusted idempotent worker stages; no write retries or permission escalation. Keep the original cumulative time budget, redact errors, and count retries and overhead. Default OFF, roll out only after full CI and a real failure-injection suite.
3. **Quality-first specialist harnesses.** Test independent Roblox Studio playtest validators (Luau lint, server/client trust, physics and asset previews), Minecraft resource-pack validators (schema, texture atlas, Blockbench compatibility) and Blender render checks (frames, geometry, materials, temporal consistency). Promote only artifacts verified by domain validators and human-quality review.
4. **Evidence + provenance for deep research.** A citation ledger should store source URL, access date, claim, confidence and verification. Distinguish primary sources from recaps, detect stale material, and flag unsupported assertions. External pages are data, never tool instructions.
5. **Economical autonomy.** Instrument context-window usage, time-to-first-token, task completion latency, model routing choice and rework rate. Use smaller models only when paired evals demonstrate equivalent task quality; escalate harder tasks. Report actual machine measurements, not hypothetical speedups.
6. **Autonomy boundaries.** Local-first, least-privilege MCP access; separate read and write scopes; explicit confirmation for destructive, financial, publish or external communications. Keep reviewable diffs and independent signed-release provenance.

## Research sources consulted

- Anthropic, Jan 9 2026, *Demystifying evals for AI agents*: https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- OpenAI, May 12 2026, *Build an Agent Improvement Loop with Traces, Evals, and Codex*: https://developers.openai.com/cookbook/examples/agents_sdk/agent_improvement_loop
- SWE-Skills-Bench, March 2026: https://arxiv.org/abs/2603.15401 ; generic skill packages often have little marginal impact without domain-fit evals.
- DeepMind, May 2025, *AlphaEvolve*: https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/ ; objective evaluators drive the optimization loop.
- Microsoft, *Protecting against indirect prompt injection attacks in MCP*: https://developer.microsoft.com/blog/protecting-against-indirect-injection-attacks-mcp/
- MCP, 2026 tool security considerations: https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/server/tools.mdx
- GitHub Actions storage limits: https://docs.github.com/en/actions/reference/limits and https://docs.github.com/en/actions/how-tos/manage-workflow-runs/remove-workflow-artifacts ; do not delete release or diagnostic artifacts without review.

## Acceptance gates for the next PR

- Baseline unchanged by default; syntactic/static/type checks and the full repository CI must pass.
- Inject deterministic timeout, HTTP 429/503 and nontransient 401/403; verify successful safe retry, strictly bounded deadline, no accidental duplicate mutations and no secrets in events.
- Use paired trials with a blind holdout. Measurably better completion with reported latency tradeoff is required before enabling recovery by default.
- Keep all changes private until reviewed and the deliberate public-release workflow is executed.
