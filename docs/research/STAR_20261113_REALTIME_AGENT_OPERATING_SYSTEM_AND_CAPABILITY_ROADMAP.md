# STAR Real-Time Agent Operating System: Research, Architecture, and Delivery Plan

**Research date:** 2026-11-13  
**Scope:** local-first intelligence, real-time game control, game creation, VTuber streaming, speech, memory, inference performance, and safe autonomous work.

## Executive decision

STAR should be engineered as a **real-time agent operating system**, not as one oversized prompt or a collection of independent bots. The architecture needs a fast, bounded interaction path for speech and control, plus slower specialist workers for research, planning, creation, and learning. Both paths share typed events, versioned memory, skills, and one authoritative resource scheduler.

This document is a research and implementation plan. It does not claim that the proposed game controller, ASR provider, OBS/VTube Studio adapter, or model configuration is already installed. Each integration must be added behind an opt-in capability flag and pass the acceptance tests below before it is described as shipped.

## 1. Repository facts and integration constraints

The current development line already has important work in flight:

- PR #1140 is identified by the existing architecture audit as the lease-based multi-resource admission controller.
- PR #1142 composes that controller with stream-pressure governance.
- PR #1177 is the durable task/communication ledger dependency.
- PR #1178 is the current draft for voice floor-control semantics and streamer persona behavior.

**Do not create a second resource scheduler.** Route model, vision, audio, game, browser, and creator workers through the existing admission/lease authority. A worker must not start expensive work merely because a local heuristic says that resources look free; it must hold a lease and release it only after the host confirms termination.

The #1178 head is based on the task-communication-ledger development line, not directly on production `main`. Keep it draft-only until its dependency train is reviewed and verified.

## 2. Real-time control: separate the world clock from model reasoning

### Research

- [ROAR: Benchmarking LMM Agents under Real-Time Constraints in Multiplayer Action-Shooter Games](https://arxiv.org/abs/2610.24282) (2026-10-16) introduces a Multi-Agent Asynchronous Gym. The environment advances at a fixed interval while agents independently read the newest observation and publish actions. The environment does not wait for model inference.
- [GameWorld](https://arxiv.org/abs/2604.07429) (2026-04-08) studies standardized, verifiable multimodal game-agent evaluation and highlights latency, sparse feedback, long-horizon planning, and irreversible mistakes.
- [OpenGameEval](https://github.com/Roblox/open-game-eval), described in [its 2026 paper](https://arxiv.org/abs/2610.02563), runs agents in reproducible stateful Roblox Studio sessions and separately measures observation/exploration, edits, scene checks, and simulated Play-session outcomes.

### Architecture decision

Use an asynchronous, timestamped observation/action pipeline:

1. The game adapter publishes observations with session ID, sequence number, monotonic timestamp, game state version, and confidence.
2. A fast controller consumes the newest valid observation and maintains a bounded action proposal.
3. A tactical planner may replace the proposal when a higher-value decision is ready.
4. A policy gate validates the action against the active game adapter, permissions, action bounds, and current state version.
5. The game adapter consumes only a fresh action. Expired or state-mismatched actions are discarded rather than executed late.
6. The environment continues advancing independently of the planner.

Use a **latest-wins action mailbox** for continuous controls, not an unbounded FIFO of stale movement commands. Preserve FIFO ordering only for actions whose semantics require it (for example, a confirmed menu transaction). Every action needs a deadline/TTL and a source tag.

### Three-level Gamer Brain

| Layer | Job | Timing contract |
|---|---|---|
| Reflex/controller | Movement, camera, aim stabilization, jump timing, dodge, button release | Deterministic, bounded, no LLM round-trip |
| Tactical planner | Local objective, route choice, combat positioning, resource use | Asynchronous; can be interrupted by new state |
| Strategic learner | Map knowledge, long-term objectives, team strategy, skill selection | Background; never blocks the control loop |

The language model should select or compose skills and explain decisions; it should not be responsible for every frame-level input. Use deterministic game APIs or small controllers wherever available. For vision-only games, use a bounded controller with explicit action duration and frequent state refresh.

### Required invariants

- No action executes against a different game/session than the one that produced it.
- No action survives a death, respawn, scene transition, pause, focus loss, or disconnect unless the adapter explicitly revalidates it.
- A stale observation cannot overwrite a newer world state.
- The controller has a neutral/no-op fallback.
- Stop, pause, and user takeover override all agent proposals.
- The adapter records proposed, accepted, rejected, and executed actions for replay.

## 3. Learn to play, not merely describe games

### Research and reusable assets

- [Voyager](https://github.com/MineDojo/Voyager) demonstrates an open-ended Minecraft agent organized around an automatic curriculum, an executable skill library, and iterative improvement from environment feedback.
- [MineDojo](https://github.com/MineDojo/MineDojo) supplies a broad Minecraft task suite spanning programmatic, creative, and playthrough tasks. It is useful for curriculum design, not a drop-in production controller.
- [GameWorld](https://arxiv.org/abs/2604.07429) supplies cross-game evaluation ideas for visual observation and action.
- [ROAR](https://arxiv.org/abs/2610.24282) is useful for testing asynchronous, continuously evolving multiplayer environments.
- [OpenGameEval](https://github.com/Roblox/open-game-eval) is the most directly relevant evaluation path for Roblox Studio agent behavior.

### STAR skill lifecycle

A learned skill should be a typed, versioned artifact, not a free-form memory paragraph:

- Name, domain, supported game/version, prerequisites, input schema, output schema.
- Preconditions and postconditions.
- Expected duration and resource profile.
- Safety envelope and allowed action set.
- Source episodes and replay references.
- Known failure modes and confidence.
- Version, evaluator results, and rollback target.

Learning loop:

1. Generate a small practice curriculum from the current capability gap.
2. Collect a baseline run with a fixed seed/state where possible.
3. Produce one or more candidate strategies.
4. Execute in a sandbox or permitted practice environment.
5. Score objective outcome, time, damage/errors, resource cost, and constraint violations.
6. Replay failures and classify whether the issue was perception, planning, control, or tool execution.
7. Compare candidates on a sealed holdout set and unfamiliar variants.
8. Promote only if the candidate improves the primary metric without regressing safety or reliability.
9. Keep the previous skill version available for immediate rollback.

Do not let the model grade its own improvement. Use simulator state, deterministic checks, held-out tasks, human review for subjective creative outcomes, and replayable evidence. Track transfer to a new map/game version separately from memorization of the training scenario.

## 4. Game creation: close the visual feedback loop

[GameDevBench](https://github.com/waynchi/gamedevbench) (ICML 2026) contains 333 game-development tasks across gameplay logic, UI, 2D/3D graphics, and animation in Godot. The benchmark demonstrates why text-only code review is insufficient: visual assets, shaders, animations, and scene state need visual feedback.

For Roblox, use [OpenGameEval](https://github.com/Roblox/open-game-eval) and preserve its key separation between **observe** and **edit** actions.

### STAR Creator pipeline

1. Read project manifest, engine/version, scene hierarchy, scripts, assets, and current tests.
2. Build a dependency map before editing.
3. Create a minimal plan with file/scene ownership.
4. Edit in a disposable worktree/place copy.
5. Run static checks and unit tests.
6. Launch an actual Play session.
7. Capture structured state plus screenshots/video at key checkpoints.
8. Compare expected geometry, UI layout, animation, physics, audio, and gameplay behavior.
9. Repair only the failing layer.
10. Run the full regression suite and package a reproducible artifact.

Add a visual-diff harness for UI and scene changes. Use deterministic camera positions, fixed resolution, seeded worlds, and stable lighting where possible. Compare semantic properties (object count, bounds, anchors, collision, constraints) as well as image similarity; raw pixel equality alone is too brittle.

## 5. VTuber streaming: social presence with honest AI identity

The objective is not to deceive viewers into believing STAR is biologically human. The objective is a consistent, expressive AI character with good timing, conversational awareness, and reliable technical performance.

### Speech pipeline

- Streaming ASR emits partial hypotheses with timestamps and confidence.
- VAD and end-of-turn detection distinguish hesitation from a completed turn.
- Speaker attribution maps voices to session-local speaker IDs; identity claims remain unavailable unless an authorized platform identity supports them.
- Addressee and intent detection distinguish direct questions, viewer-to-viewer chat, game callouts, and background speech.
- A room director owns the floor: speak, queue, continue, interrupt, stop, or remain silent.
- LLM generation produces short, context-aware spoken text.
- Streaming TTS begins with the first complete clause.
- The avatar expression and mouth movement are synchronized to the actual audio timeline.

[LiveKit EoT-Bench](https://github.com/livekit/eot-bench) evaluates end-of-turn detection using real conversations in 14 languages. It measures the trade-off between response latency and false cutoffs, which is a better target than optimizing endpointing accuracy alone. [MP-Bench](https://www.fullduplex.ai/benchmarks/mp-bench) and [Full-Duplex-Bench v3](https://www.fullduplex.ai/benchmarks/fdb-v3) provide complementary measures for multi-party comprehension, appropriateness, turn-taking, tool execution, and latency.

### Natural streamer behavior

- Vary openings and sentence rhythm without relying on catchphrases.
- Use excitement only when supported by the event.
- Leave natural quiet instead of narrating every frame.
- Remember the current topic and recent viewer contributions within the session.
- Do not repeat a question that another participant already answered.
- Support playful reactions, curiosity, humor, and gentle teasing within the character's boundaries.
- Do not invent off-stream events, personal memories, physical experiences, or viewer relationships.
- Keep the AI identity clear in channel descriptions, first-run setup, and direct answers.

### Avatar and broadcast adapters

- [VTube Studio's official API development page](https://github.com/DenchiSoft/VTubeStudio) documents its public WebSocket API, including hotkeys, model state, tracking parameters, item control, and events. Build an adapter with explicit user authorization, reconnect handling, request timeouts, and a strict allowlist of supported operations.
- [OBS WebSocket](https://github.com/obsproject/obs-websocket) is bundled with OBS Studio 28+. Its project recommends password protection. Use an authenticated local connection, validate scene/source IDs, and restrict STAR to an allowlist of scenes and operations.
- [Twitch EventSub](https://dev.twitch.tv/docs/eventsub/) supports WebSocket, webhook, and conduit transports. Notifications may be duplicated, so persist processed message IDs and make handlers idempotent. On connection loss, reconnect and resubscribe; do not assume lost events are replayed.
- [YouTube LiveChatMessages](https://developers.google.com/youtube/v3/live/docs/liveChatMessages) supports list, insert, and low-latency server-streaming via `streamList`. Outbound messages have quota costs and permission requirements; use rate limits and a per-stream budget.

Platform adapters must not share OAuth tokens with model prompts. Store credentials in the OS credential store, scope them narrowly, redact logs, and make disconnect/revoke available. Chat moderation should default to recommendations or reversible actions; bans, deletions, title changes, and going live/offline require explicit configured authority.

## 6. Inference speed: measure the complete path

### Research

- [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) documents prompt/KV reuse and per-request timing support.
- [llama.cpp speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md) uses a draft/verification path; gains depend on draft acceptance and target-model compatibility.
- [vLLM Automatic Prefix Caching](https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/) reuses KV blocks for shared prefixes. Its documentation is explicit that this primarily reduces prefill work, not token-by-token decode time.

### STAR performance plan

1. Keep system prompts, tool schemas, and stable persona instructions in a deterministic prefix. Put volatile user/game context after that prefix.
2. Measure cache hits and actual prefill savings before tuning history length.
3. Test speculative decoding only with matched prompt sets and report draft acceptance, output quality, and end-to-end latency.
4. Compare quantization/KV-cache formats on the same model, context, hardware, and task set. Track quality regressions as well as speed.
5. Use smaller specialist models for bounded classification, routing, VAD, OCR, and state extraction; reserve the strongest model for planning and difficult reasoning.
6. Batch only background workloads. Do not let batching delay an interactive voice turn.
7. Offload long research, video indexing, model conversion, and training away from the active stream.
8. Preserve CPU/RAM performance paths so STAR remains usable when GPU resources are occupied by the game, encoder, or avatar.

### Required performance dashboard

| Metric | Why it matters |
|---|---|
| Time to first visible token (P50/P95) | Chat responsiveness |
| Time to first audio byte / audible word | Spoken responsiveness |
| End-of-turn decision latency and false-cutoff rate | Natural conversation |
| Prefill tokens/sec and decode tokens/sec | Separates prompt and generation bottlenecks |
| Inter-token latency (P50/P95) | Speech smoothness |
| Prefix/KV cache hit rate and saved prefill time | Validates caching |
| GPU VRAM, utilization, CPU, RAM, disk I/O | Detects contention |
| OBS render/encode lag and dropped frames | Stream stability |
| Audio underruns and output queue depth | Voice reliability |
| Game FPS and control-loop deadline misses | Gameplay responsiveness |
| Action age at execution | Detects stale controls |
| Task success and skill-transfer rate | Actual intelligence improvement |

Do not publish a single "tokens per second" number as proof that STAR became faster. Compare end-to-end P50/P95 under the same mixed workload: game + OBS + avatar + audio + chat + one background task.

## 7. Memory and general knowledge

Use separate memory classes with different retention and retrieval policies:

- **Session memory:** current speakers, topic, game state, recent events; expires after the session unless explicitly promoted.
- **Episodic memory:** timestamped experiences, decisions, outcomes, and evidence links.
- **Semantic memory:** facts with source, confidence, and last-verified date.
- **Procedural memory:** executable, versioned skills with preconditions and tests.
- **Project memory:** repository/scene architecture, decisions, current branch, tasks, and blockers.
- **Preference memory:** user-approved stable preferences only.

Retrieval should be query-adaptive: use keyword and semantic retrieval, metadata filters, graph relationships where useful, and reranking for high-value evidence. Return citations/evidence with retrieved facts. Detect contradictions and stale knowledge; never silently overwrite a verified fact with an unverified model summary.

For general knowledge, the pipeline should be: classify question → retrieve trusted sources → compare conflicting claims → use tools/calculations where appropriate → answer with provenance and uncertainty → save only durable, useful knowledge. Add freshness policies by domain; fast-changing software/API facts need revalidation more often than stable fundamentals.

## 8. Autonomous work and reliability

Use the existing durable task ledger and scheduler to implement:

- Idempotent task IDs and deduplicated event handling.
- Checkpointed plans with explicit dependencies.
- Worker leases with heartbeat and host-confirmed release.
- Cancellation propagation and cleanup.
- Retry policies that distinguish transient failures from permanent errors.
- Dead-letter handling for repeatedly failing tasks.
- Artifact provenance and content hashes.
- A rollback point before any self-modification.
- A supervisor that restarts services without duplicating work.
- Offline-first operation when network or providers are unavailable.

Self-improvement may propose code, skills, or prompt changes in an isolated branch/worktree. It must run tests, compare against a sealed holdout set, scan for secrets and unsafe permissions, and retain a rollback. Never let an agent rewrite its own safety gate or silently widen platform permissions.

## 9. Delivery plan and acceptance gates

### Phase A — Stabilize the current foundation

- Preserve one scheduler (#1140/#1142) and one durable task/communication authority (#1177).
- Fix the voice prompt compatibility regression without weakening the new streaming rules.
- Run exact-head Linux and Windows suites; inspect failures rather than suppressing tests.
- Publish a capability matrix: shipped, experimental, research-only, blocked.

**Gate:** no unexplained regression; current PR dependency chain is explicit; exact-head CI passes.

### Phase B — Complete streaming interaction

- Add opt-in ASR/diarization adapter and end-of-turn evaluation.
- Wire trusted speaker/addressee evidence into the existing room director.
- Add VTube Studio and OBS adapters with user authorization and allowlisted actions.
- Add Twitch/YouTube chat adapters with deduplication, reconnect, rate limits, and moderation policy.
- Run long-session tests with synthetic chat and consented audio.

**Gate:** low false-cutoff rate, bounded response latency, no repeated messages after reconnect, no secret leakage, stable audio/avatar sync, and no stream frame-loss regression under mixed load.

### Phase C — Build the Gamer Brain

- Start with deterministic environments and browser games.
- Add a Roblox adapter and OpenGameEval-compatible test harness.
- Add asynchronous observation/action mailboxes and stale-action rejection.
- Add skill storage, practice curricula, replay, and holdout evaluation.
- Add Minecraft/MineDojo or Voyager-inspired experiments as a separate adapter.

**Gate:** reproducible success on held-out scenarios; no action after stop/pause/scene change; control loop remains independent of LLM latency.

### Phase D — Build the Creator Brain

- Add Roblox Studio inspection/edit/play-session loop.
- Add Godot tasks and GameDevBench-style visual feedback.
- Add Blender asset inspection and render verification.
- Store reusable skills and tested project templates.

**Gate:** project opens, tests pass, Play session succeeds, visual checks pass, and artifact is reproducible.

### Phase E — Expand general knowledge and continual learning

- Add source-grounded research and freshness checks.
- Add session-to-episodic memory promotion with explicit retention rules.
- Add continual task streams and private holdouts.
- Track learning curves, forgetting, transfer, cost, and regressions over weeks.

**Gate:** measured improvement on unseen tasks, stable retention, evidence-backed answers, and no unacceptable privacy or safety regression.

## 10. Immediate engineering backlog

| Priority | Item | Type | Done when |
|---|---|---|---|
| P0 | Preserve legacy prompt API and opt into stream-only rules at live call sites | Runtime/tests | Linux + Windows voice tests pass |
| P0 | Reconcile PR #1178 base/head dependency chain | Integration | No hidden branch dependency |
| P1 | Mixed-load performance harness | Benchmark | Reproducible P50/P95 dashboard |
| P1 | Freshness-aware observation/action mailbox | Runtime | Stale actions are rejected and tested |
| P1 | ASR/EoT adapter contract | Interface | Can replay benchmark audio without platform credentials |
| P1 | VTube Studio/OBS adapter contracts | Interface | Mock protocol tests, auth and allowlist checks |
| P2 | Twitch/YouTube event adapters | Integration | Duplicate/reconnect/rate-limit tests |
| P2 | Gamer skill artifact schema | Runtime | Skill has preconditions, postconditions, replay and version |
| P2 | Roblox Studio inspect-edit-play loop | Integration | OpenGameEval-compatible tasks run locally |
| P2 | Game creator visual feedback loop | Integration | Scene/image and executable checks are recorded |
| P3 | General knowledge provenance store | Runtime | Answers retain sources and freshness |
| P3 | Continual learning/holdout harness | Evaluation | Promotion is based on external held-out results |

## 11. Source register

1. ROAR (2026-10-16): https://arxiv.org/abs/2610.24282
2. GameWorld (2026-04-08): https://arxiv.org/abs/2604.07429
3. OpenGameEval (2026-10): https://arxiv.org/abs/2610.02563
4. OpenGameEval code: https://github.com/Roblox/open-game-eval
5. GameDevBench (ICML 2026): https://github.com/waynchi/gamedevbench
6. Voyager: https://github.com/MineDojo/Voyager
7. MineDojo: https://github.com/MineDojo/MineDojo
8. Continual-ARC: https://continual-arc.unify.ai/
9. LiveKit EoT-Bench: https://github.com/livekit/eot-bench
10. MP-Bench: https://www.fullduplex.ai/benchmarks/mp-bench
11. Full-Duplex-Bench v3: https://www.fullduplex.ai/benchmarks/fdb-v3
12. VTube Studio API: https://github.com/DenchiSoft/VTubeStudio
13. OBS WebSocket: https://github.com/obsproject/obs-websocket
14. Twitch EventSub: https://dev.twitch.tv/docs/eventsub/
15. YouTube LiveChatMessages: https://developers.google.com/youtube/v3/live/docs/liveChatMessages
16. llama.cpp server: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
17. llama.cpp speculative decoding: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
18. vLLM Automatic Prefix Caching: https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/

## Evidence boundary

The research supports architecture choices and test plans; it does not prove STAR currently has these integrations. Benchmark scores are environment-specific and must not be compared across incompatible setups. No hardware speedup is claimed without target-machine measurements. No platform connection, credential, microphone, camera, game-control, or autonomous broadcast permission is enabled by this document.
