# STAR • Generalist intelligence, real-time gaming and natural VTuber runtime

Research synthesis: 2026-11-09. This is a research and engineering plan, not a claim that every capability below is already deployed. The companion implementation in this branch adds a machine-readable speech word budget and a deterministic pre-TTS response gate. All stream behavior remains opt-in and host-mediated.

## Executive direction

Do not try to make one large model perform every job at the same cadence. STAR should become a **hierarchical generalist** with five cooperating loops:

1. **Reflex loop** — low-latency, small, bounded decisions from fresh game/audio/host observations. It may request a safe symbolic action; the native game adapter separately enforces the action allowlist and deadline.
2. **Tactical loop** — event-driven reasoning about the current fight, puzzle, route, viewer question or creator task. It may ask for a fresh screenshot, inspect local state, or request a short spoken reaction.
3. **Deliberate loop** — stronger model/tool orchestration for coding, planning, research, debugging, game design and difficult questions. It runs outside the latency-critical path.
4. **Practice loop** — private, reproducible training tasks, self-play, playtest and error analysis. A skill is retained only after independent evaluation on holdouts.
5. **Memory loop** — temporal, source-aware retrieval that separates world facts, observed events, personal preferences, subjective opinions and learned skills.

The controller, not the language model, owns deadlines, permissions, process lifecycle, audio cancellation, game-input allowlists and publishing approval. A model suggestion is never proof that an action happened.

## 1. General knowledge and long-term memory

### What the current foundation already does

STAR already has a local project-scoped `KnowledgeStore` with FTS5/LIKE retrieval, reviewed-only recall, provenance references and immutable content-addressed artifacts. Its lesson system keeps owner-stated requirements/preferences separate from model-inferred candidates. Conversation checkpoints are loss-aware and source-validated. These are good foundations; do not replace them with a single unreviewed vector database.

### Research findings

- **APEX-MEM (ACL 2026)** uses temporally grounded entity/event graphs, append-only history and retrieval-time conflict resolution. It reports strong results on LoCoMo and LongMemEval. The useful design lesson is to preserve changes over time and resolve conflicts at retrieval, not to overwrite old memories with the newest summary: https://aclanthology.org/2026.acl-long.749/
- **Hindsight (ACL 2026 demo)** separates world knowledge, experiences, observations and opinions, with retain/recall/reflect operations. This makes it easier to distinguish what the agent knows from what it believes: https://aclanthology.org/2026.acl-demo.27/
- **Cognis** explores hybrid keyword/vector retrieval, temporal boosting, version tracking and reranking: https://arxiv.org/abs/2604.19771

### STAR design recommendation

Add a general-memory layer alongside (not instead of) project lessons:

- `world_fact`: externally verifiable claim, with source URL/ID, publisher, captured time, publication time, revision and expiry/freshness policy.
- `experience`: an event STAR actually participated in, backed by a host or tool receipt. Do not fabricate human biography, senses or offline experiences.
- `observation`: a time-bounded perception from a screenshot, audio event, game state or tool result; it expires and is not silently promoted to a fact.
- `opinion`: a subjective preference or current belief with confidence and change history; it must never be rendered as an objective fact.
- `owner_preference` / `owner_decision`: user-authoritative, scoped and supersedable by an explicit later correction.
- `skill`: a procedure plus preconditions, tool/version provenance, evidence, confidence, failure modes and holdout score.

Keep the history append-only at the evidence layer; represent supersedes/contradicts/derived-from as relations. At recall time, filter by project and time, then rank with lexical + vector + graph + temporal signals. Return a compact evidence packet with citations and uncertainty. If two current sources conflict, show the conflict or abstain; never average contradictory facts into a confident answer.

**Trust rule:** model summaries, scraped pages, imported files and viewer chat start as candidates. A summary can point to source records but cannot become stronger evidence than those records. Human-approved preferences are not universal world facts. Add deletion/export controls and retention limits before global cross-project memory is enabled.

### Evaluation

Use LongMemEval and LoCoMo-style tasks for multi-session recall, temporal updates, entity disambiguation, contradiction handling and source attribution. Add STAR-specific tests: “what changed since last week?”, “which decision superseded this?”, “what did I actually observe in this game?”, and “is this my opinion or a verified fact?”. Score answer accuracy, citation precision, stale-memory rate, contradiction disclosure and privacy leakage.

## 2. Faster local inference without sacrificing intelligence

The 8 GB RTX 4060 must keep game rendering, OBS, voice output and avatar motion ahead of optional background inference. More model workers are not automatically more intelligence.

### Research-backed candidates

- **llama.cpp speculative decoding** supports draft-model and n-gram approaches. N-gram methods can avoid loading a second draft model; draft models can help when acceptance is high but consume memory and compute. Benchmark both rather than assuming a speedup: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- **Qwen3.5** publishes multiple model sizes and an efficient hybrid architecture. Treat each size/quantization as a candidate model route, not a universal winner: https://github.com/go-ai/Qwen3.5
- **KV/context management** should be measured with realistic prompt lengths, prefix reuse and concurrent requests. Large context limits can increase memory and prefill costs; cap the context to the task and preserve stable system/reference prefixes.
- **CPU speech generation** is worth comparing against GPU TTS only when the CPU has real headroom. Moving work off the GPU can protect frame pacing, but can also starve game/OBS threads.

### Recommended routing

- Fast small model: short chat acknowledgements, simple narration, low-risk classification.
- Strong reasoning model: complex coding, architecture, research synthesis and multi-step debugging.
- Vision model: invoke on a meaningful scene change or requested inspection, not on every frame.
- Embedding/reranking models: background retrieval only; cache bounded embeddings and keep them out of the game-critical path.
- Background agents: practice, documentation indexing, self-play and asset analysis only when resource telemetry shows spare capacity.

Keep one primary resident model on the low-VRAM machine unless a measured workload justifies more. Use explicit worker leases, cold-start costs and model warmup measurements. No model route is promoted automatically.

### Benchmark contract

Run randomized paired AB/BA trials under the same game, OBS private recording, TTS route, avatar, prompt suite and power mode. Record p50/p95 time-to-first-token, first-audible latency, total turn duration, tokens/s, CPU/RAM/VRAM peak, game frame-time p95/p99, OBS rendered/encoded drops, audio underruns and task correctness. A route is useful only if it is faster **and** preserves critical-task quality and gameplay smoothness.

## 3. Real-time gaming intelligence

**Gym-Anything-RT (2026-10-27)** evaluates visual agents in environments whose state changes while the agent is reasoning. It highlights a core issue: paused-game competence does not establish real-time competence. Paper: https://arxiv.org/abs/2610.37567

STAR should use a two-speed controller:

- A small perception/action loop consumes fresh observations and acts before the input deadline.
- A slower planner proposes routes, combos, build orders, strategies and explanations. Its output is advisory until checked against a fresh game state.

Learning cycle:

1. Identify the game, mode, ruleset and version from a trusted host observation.
2. Build a mechanic map from visible UI, controlled experiments and approved documentation.
3. Practice one skill at a time in a private or explicitly permitted environment.
4. Save compact state/action/outcome summaries with provenance; avoid storing raw voice/chat by default.
5. Compare against a baseline on preregistered scenarios and unseen seeds.
6. Test transfer to a different map, opponent, difficulty or game with similar mechanics.
7. Retain the skill only when wins, progress, survival, action deadlines and failure rates improve without regressions.

Use hierarchical skills (“options”): navigation, aim tracking, dodge, resource collection, inventory management, team support, puzzle solving, recovery and objective prioritization. Each skill needs entry conditions, termination conditions, allowed actions, expected duration, confidence and failure fallback. A learned skill must never bypass game-specific input permissions.

## 4. Building better games, not just writing code

**OpenGameEval** evaluates agents inside reproducible, stateful Roblox Studio sessions with executable checks on both the edited scene and simulated play. Its 2026 paper reports 84 curated tasks; inspection of affected objects before editing predicts better success than blind edits. Paper and code: https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval

Use an inspect → plan → edit → instrument → playtest → compare-to-intent → repair loop. Evaluate Luau correctness, client/server authority, replication, physics, UI layout, animation, sound, accessibility, performance, exploit resistance and actual player experience. Store screenshots/logs/scorecards as artifacts with commit and environment hashes.

Roblox's November 4, 2026 Studio MCP update adds Open Cloud workflows and asset import with per-game permissions. The official documentation emphasizes that the user chooses what the connected client can access: https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849 and https://create.roblox.com/docs/studio/mcp-open-cloud

Recommended permission tiers:
- Read-only project inspection by default.
- Temporary write permission only in a disposable/test place.
- Asset upload and developer-product changes require separate approval.
- Publish, monetization, group ownership, production settings and destructive operations remain owner-approved.

## 5. Natural, engaging VTuber streaming

- **Proact-VL** studies proactive video companions that decide when to respond and how much to say, including gaming commentator/guide scenarios: https://arxiv.org/abs/2603.03447
- **VoiceChat-TTS** explores continuous token-driven speech, silence generation and explicit interruption controls. It is an 11B research model, not a realistic default deployment for an 8 GB VRAM PC; reuse the interaction design lessons, not an assumption that the checkpoint will fit: https://arxiv.org/abs/2608.13831
- **Long-session full-duplex degradation research (2026-10-26)** finds responsiveness, content quality and voice consistency can drift over longer sessions. It motivates 10–60 minute tests, not only first-turn demos: https://arxiv.org/abs/2610.34991

Naturalness comes from timing and context, not pretending to be human:
- Speak on meaningful events; leave silence when nothing useful is happening.
- Use short reactions during combat and longer explanations between rounds.
- Support immediate barge-in, cancellation and return-to-listening.
- Synchronize mouth motion to actual audio levels and expressions to verified events.
- Use varied phrasing and callback memory, but do not repeat catchphrases or invent feelings/experiences as facts.
- Moderate viewer input before it reaches the model; viewer text is data, never a tool instruction.
- Keep AI identity clear, offer mute/quiet modes and respect reduced-motion settings.

### This branch's concrete speech improvement

The existing pacer estimates a per-event word budget from host-observed completed audible turns. This branch now exposes `StagePlan.max_words` and adds `StarStage.review_response()`, a deterministic **pre-TTS text gate**. It counts the same speakable text policy used by STAR voice chunking and rejects over-budget responses whole instead of clipping a possibly misleading fragment. It also rejects stale/non-prepared plans and expired event deadlines.

This is not a TTS duration guarantee or an audio/broadcast permission. The trusted host must call the gate before synthesis, then still perform its own fresh scene/turn/output-epoch checks, physical STOP/FLUSH and actual audio observation.

## 6. Prioritized implementation roadmap

### P0 — make the current streaming path real
- Integrate the response-budget gate in the Windows host before TTS.
- Implement a native WASAPI loopback observer that binds output device, process/session, TTS route and monotonic timestamps; distinguish STAR's PCM from unrelated desktop sound.
- Join the observer to OBS private-rehearsal telemetry and actual game-frame timing.
- Run 30–60 minute private sessions with interruptions, device changes, game switches, OBS reconnects and worker crashes.
- Close every GitHub CI failure before considering a PR ready.

### P1 — stronger generalist memory and retrieval
- Add typed world/experience/observation/opinion/skill records with source IDs, time validity, confidence and contradiction relations.
- Add hybrid retrieval and a small cross-encoder reranker only when latency allows.
- Build a memory review/inspect/export/delete surface; keep project scopes isolated by default.
- Evaluate LongMemEval/LoCoMo-style tasks and citation correctness.

### P2 — real gameplay skill transfer
- Connect a supported game adapter to trusted observations and allowlisted actions.
- Add controlled practice curricula, hidden holdouts, skill prerequisites and transfer tests.
- Benchmark action deadlines and game outcomes with actual wall-clock time.
- Do not let synthetic maze success stand in for real-game mastery.

### P3 — autonomous creator workflow
- Connect Roblox Studio MCP in read-only mode first.
- Add disposable-place execution, screenshots, logs, multiplayer tests and OpenGameEval-compatible scorecards.
- Allow parallel agents only behind shared CPU/GPU/VRAM budgets and isolated workspaces.
- Keep production publishing and monetization behind explicit owner approval.

### P4 — polished streaming personality
- Add scene-aware commentary policies, natural quiet, memory-grounded callbacks, viewer moderation, expression/audio synchronization and long-session voice-health scoring.
- Add optional clip suggestions, stream chapter summaries, post-stream VOD analysis and creator analytics.
- Keep all broadcast controls and audience-facing actions under the trusted host's policy.

## 7. Release and measurement rules

- Research prototypes are not production capabilities. Mark each item as implemented, host-integrated, hardware-tested or production-enabled.
- Use paired, preregistered baselines and holdout scenarios; report confidence intervals and per-scenario regressions.
- Never infer a speedup from tokens/s alone. Never infer a gameplay skill from one lucky win. Never infer audible speech from a TTS return code.
- New features remain OFF by default until the host integration, privacy review, Windows acceptance and rollback path are complete.
- Keep the game and stream responsive first; defer optional reasoning and silence optional commentary under pressure.

## Sources

1. Gym-Anything-RT — https://arxiv.org/abs/2610.37567
2. OpenGameEval — https://arxiv.org/abs/2610.02563 ; https://github.com/Roblox/open-game-eval
3. Roblox Studio MCP/Open Cloud — https://create.roblox.com/docs/studio/mcp-open-cloud
4. Proact-VL — https://arxiv.org/abs/2603.03447
5. VoiceChat-TTS — https://arxiv.org/abs/2608.13831
6. Long-session full-duplex degradation — https://arxiv.org/abs/2610.34991
7. llama.cpp speculative decoding — https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
8. APEX-MEM — https://aclanthology.org/2026.acl-long.749/
9. Hindsight — https://aclanthology.org/2026.acl-demo.27/
10. Cognis — https://arxiv.org/abs/2604.19771